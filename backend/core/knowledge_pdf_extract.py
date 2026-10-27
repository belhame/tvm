"""Isolated PDF text worker. No rendering, OCR, external fetch or actions.

The web process sends bytes on stdin and enforces the wall-clock timeout.
This worker enforces CPU/address-space limits before importing pypdf and
emits a single bounded JSON response; PDF text remains untrusted content.
"""

import io
import json
import logging
import sys
import warnings


MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 500
MAX_PAGE_CHARS = 100_000
MAX_TEXT_CHARS = 1_000_000
MAX_RESPONSE_BYTES = 6 * 1024 * 1024
CPU_SECONDS = 5
MEMORY_BYTES = 384 * 1024 * 1024


def _limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


def _valid_text(text):
    return not any((ord(char) < 32 and char not in '\n\r\t') or 0xD800 <= ord(char) <= 0xDFFF for char in text)


def _emit(payload):
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_RESPONSE_BYTES:
        encoded = b'{"valid":false,"reason":"limits"}'
    sys.stdout.buffer.write(encoded)


def main():
    logging.disable(logging.CRITICAL)
    warnings.simplefilter('ignore')
    sys.setrecursionlimit(500)
    try:
        _limits()
    except (ImportError, ValueError, OSError):
        # Do not silently extract hostile content without memory/CPU bounds on
        # unsupported native platforms. The supported Docker server is Linux.
        _emit({'valid': False, 'reason': 'limits_unavailable'})
        return
    try:
        from pypdf import PdfReader
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES or not data.startswith(b'%PDF-'):
            raise ValueError()
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            _emit({'valid': False, 'reason': 'encrypted'})
            return
        count = len(reader.pages)
        if not 1 <= count <= MAX_PAGES:
            _emit({'valid': False, 'reason': 'pages'})
            return
        pages = []
        total = 0
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ''
            if not isinstance(text, str) or not _valid_text(text):
                raise ValueError()
            if len(text) > MAX_PAGE_CHARS:
                _emit({'valid': False, 'reason': 'text_limit'})
                return
            total += len(text)
            if total > MAX_TEXT_CHARS:
                _emit({'valid': False, 'reason': 'text_limit'})
                return
            pages.append({'page': number, 'text': text})
        _emit({'valid': True, 'page_count': count, 'pages': pages})
    except (MemoryError, RecursionError):
        _emit({'valid': False, 'reason': 'limits'})
    except Exception:
        # Never return a library exception or document content in an error.
        _emit({'valid': False, 'reason': 'format'})


if __name__ == '__main__':
    main()
