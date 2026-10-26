"""Isolated local image decoding/OCR. Emits candidates, never the raw OCR text."""
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import warnings

from .serial_photo_rules import MAX_CANDIDATES, barcode_serials, ocr_serials


MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 12_000_000


def _limits():
    os.umask(0o077)
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ImportError, OSError, ValueError):
        # The parent still bounds wall time and deletes its private temp folder.
        pass


def recognize(data, folder):
    started = time.monotonic()
    from PIL import Image, ImageOps, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP') or getattr(source, 'n_frames', 1) != 1:
                    return {'error': 'format'}
                if source.width < 1 or source.height < 1 or source.width * source.height > MAX_PIXELS:
                    return {'error': 'pixels'}
                source.load()
                oriented = ImageOps.exif_transpose(source)
                # A newly allocated raster drops EXIF/GPS, filenames and comments.
                image = Image.new('RGB', oriented.size, 'white')
                if oriented.mode in ('RGBA', 'LA') or 'transparency' in oriented.info:
                    rgba = oriented.convert('RGBA')
                    image.paste(rgba, mask=rgba.getchannel('A'))
                else:
                    image.paste(oriented.convert('RGB'))
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        return {'error': 'pixels'}
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError):
        return {'error': 'image'}
    candidates = []
    try:
        import zxingcpp
        codes = zxingcpp.read_barcodes(image, try_rotate=True, try_downscale=True, try_invert=True)
        for code in codes:
            # EAN/UPC identify a commercial product, not an individual UPS.
            if any(label in str(code.format).upper() for label in ('EAN', 'UPC')):
                continue
            for serial in barcode_serials(code.text):
                if serial not in {entry['serial_number'] for entry in candidates}:
                    candidates.append({'serial_number': serial, 'source': 'barcode'})
                    if len(candidates) == MAX_CANDIDATES:
                        break
            if len(candidates) == MAX_CANDIDATES:
                break
    except (ImportError, RuntimeError, ValueError, TypeError):
        pass
    if candidates:
        return {'candidates': candidates, 'method': 'barcode'}
    binary = shutil.which('tesseract')
    if not binary:
        return {'candidates': [], 'method': 'none', 'unavailable': True}
    image_path, prefix = folder / 'label.png', folder / 'read'
    image.save(image_path, 'PNG')
    image_path.chmod(0o600)
    remaining = min(3.5, 4.5 - (time.monotonic() - started))
    if remaining <= 0:
        return {'candidates': [], 'method': 'none', 'timeout': True}
    try:
        result = subprocess.run(
            [binary, str(image_path), str(prefix), '-l', 'eng', '--psm', '11'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=remaining, check=False,
        )
    except subprocess.TimeoutExpired:
        return {'candidates': [], 'method': 'none', 'timeout': True}
    except OSError:
        return {'candidates': [], 'method': 'none', 'unavailable': True}
    if result.returncode:
        return {'candidates': [], 'method': 'none', 'unavailable': True}
    with prefix.with_suffix('.txt').open('rb') as output:
        text = output.read(65537).decode('utf-8', errors='replace')
    return {'candidates': [{'serial_number': serial, 'source': 'ocr'} for serial in ocr_serials(text)], 'method': 'ocr'}


def main():
    _limits()
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            result = {'error': 'size'}
        else:
            result = recognize(data, Path(sys.argv[1]))
    except Exception:
        # Decoder details and OCR text must not reach application logs.
        result = {'error': 'processing'}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
