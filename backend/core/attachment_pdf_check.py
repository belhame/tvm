"""Bounded PDF structure check in a separate process; no links/actions run.

Called with PDF bytes on stdin. It deliberately does not render pages, fetch
external resources, execute JavaScript, or claim malware/antivirus scanning.
"""

import io
import json
import logging
import sys
import warnings


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    except (ImportError, ValueError, OSError):
        # The caller still imposes a five-second wall-clock timeout. The
        # recommended Linux/Docker deployment also enforces memory/CPU limits.
        pass
    logging.disable(logging.CRITICAL)
    warnings.simplefilter('ignore')
    sys.setrecursionlimit(500)
    try:
        from pypdf import PdfReader
        data = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
        if not data.startswith(b'%PDF-') or len(data) > 10 * 1024 * 1024:
            raise ValueError()
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            print(json.dumps({'valid': False, 'reason': 'encrypted'}))
            return
        pages = len(reader.pages)
        if not 1 <= pages <= 500:
            print(json.dumps({'valid': False, 'reason': 'pages'}))
            return
        # Access only the page tree and page dictionaries, not content streams
        # or attached files. pypdf does not execute embedded actions here.
        for page in reader.pages:
            if page.get('/Type') != '/Page':
                raise ValueError()
        print(json.dumps({'valid': True, 'page_count': pages}))
    except Exception:
        print(json.dumps({'valid': False, 'reason': 'format'}))


if __name__ == '__main__':
    main()
