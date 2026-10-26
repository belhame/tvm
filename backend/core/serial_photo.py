"""Bounded local photograph recognition; no equipment or dossier is written."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory

from rest_framework.exceptions import APIException, ValidationError

from .serial_photo_rules import MAX_CANDIDATES, serial_candidate


MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_TIMEOUT_SECONDS = 5


class SerialPhotoTooLarge(APIException):
    status_code = 413
    default_detail = 'La photo dépasse la limite de 8 Mio.'


class SerialPhotoDimensionsTooLarge(APIException):
    status_code = 413
    default_detail = 'La photo dépasse 12 millions de pixels. Réduisez sa résolution.'


def recognize_serial_photo(data):
    if len(data) > MAX_PHOTO_BYTES:
        raise SerialPhotoTooLarge()
    env = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'OMP_THREAD_LIMIT': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
    result = None
    timed_out = False
    with TemporaryDirectory(prefix='tvm-serial-') as temporary:
        # The parent owns cleanup even if an image decoder hangs or is killed.
        kwargs = {'start_new_session': True} if os.name == 'posix' else {}
        try:
            process = subprocess.Popen(
                [sys.executable, '-m', 'core.serial_photo_worker', temporary],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=Path(__file__).resolve().parent.parent, env=env, **kwargs,
            )
        except OSError:
            result = {'unavailable': True}
        else:
            try:
                output, _ = process.communicate(input=data, timeout=PHOTO_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                if os.name == 'posix':
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.communicate()
                timed_out = True
                result = {'timeout': True}
            else:
                if process.returncode == 0 and len(output) <= 16384:
                    try:
                        result = json.loads(output)
                    except (ValueError, UnicodeError):
                        pass
    if not isinstance(result, dict):
        result = {'timeout': True}
    if result.get('error') == 'size':
        raise SerialPhotoTooLarge()
    if result.get('error') == 'pixels':
        raise SerialPhotoDimensionsTooLarge()
    if result.get('error'):
        raise ValidationError({'file': 'Photo invalide ou trop complexe. Formats acceptés : JPEG, PNG et WEBP, 12 millions de pixels maximum.'})
    candidates = []
    entries = result.get('candidates', [])
    if not isinstance(entries, list):
        entries = []
    for entry in entries[:MAX_CANDIDATES]:
        if not isinstance(entry, dict) or entry.get('source') not in ('barcode', 'ocr'):
            continue
        serial = serial_candidate(entry.get('serial_number', ''), labeled=True)
        if serial and serial not in {item['serial_number'] for item in candidates}:
            candidates.append({'serial_number': serial, 'source': entry['source']})
    status = 'ambiguous' if len(candidates) > 1 else 'recognized' if candidates else 'unavailable' if result.get('unavailable') else 'not_found'
    if candidates:
        message = 'Vérifiez le numéro proposé sur l’étiquette avant de rechercher la mission.' if len(candidates) == 1 else 'Plusieurs numéros sont proposés. Choisissez et vérifiez celui de l’étiquette de l’onduleur.'
    elif result.get('unavailable'):
        message = 'La lecture de texte est indisponible sur ce serveur. Utilisez le scanner USB ou saisissez le numéro.'
    elif timed_out or result.get('timeout'):
        message = 'La photo n’a pas pu être lue dans le temps disponible. Reprenez une photo nette ou saisissez le numéro.'
    else:
        message = 'Aucun numéro de série lisible. Reprenez une photo de l’étiquette ou saisissez le numéro.'
    method = result.get('method', 'none')
    return {'candidates': candidates, 'method': method if method in ('barcode', 'ocr', 'none') else 'none', 'status': status, 'message': message}
