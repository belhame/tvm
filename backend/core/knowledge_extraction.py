"""Bounded, page-traceable technical-document extraction.

Only embedded PDF text is extracted. Visual schematics and scanned pages are
not interpreted; callers must retain the returned warnings with the source.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

from rest_framework.exceptions import ValidationError

from .attachment_validation import check_attachment, safe_original_name


MAX_TEXT_CHARS = 1_000_000
MAX_PAGE_CHARS = 100_000
MAX_PAGES = 500
MAX_RESPONSE_BYTES = 6 * 1024 * 1024
WALL_TIMEOUT_SECONDS = 8


def _safe_text(value):
    return isinstance(value, str) and not any(
        (ord(char) < 32 and char not in '\n\r\t') or 0xD800 <= ord(char) <= 0xDFFF for char in value
    )


def _pdf_pages(data):
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'core.knowledge_pdf_extract'], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=WALL_TIMEOUT_SECONDS, check=False,
            cwd=Path(__file__).resolve().parent.parent,
            env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationError({'file': 'L’extraction du PDF a dépassé ses limites de temps ou de ressources.'}) from exc
    try:
        if result.returncode != 0 or len(result.stdout) > MAX_RESPONSE_BYTES:
            raise ValueError()
        payload = json.loads(result.stdout)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValidationError({'file': 'Le texte du PDF ne peut pas être extrait dans les limites de sécurité du serveur.'}) from exc
    if not isinstance(payload, dict) or payload.get('valid') is not True:
        reason = payload.get('reason') if isinstance(payload, dict) else None
        message = {
            'text_limit': 'Le texte du PDF dépasse 100 000 caractères par page ou 1 000 000 caractères au total. Découpez le document sans le tronquer.',
            'pages': 'Le PDF doit contenir entre 1 et 500 pages.',
            'encrypted': 'Le PDF doit être lisible sans mot de passe.',
            'limits_unavailable': 'L’extraction sécurisée des PDF est indisponible sur ce serveur.',
        }.get(reason, 'Le PDF est illisible ou trop complexe pour une extraction sûre de son texte.')
        raise ValidationError({'file': message})
    pages = payload.get('pages')
    count = payload.get('page_count')
    if type(count) is not int or not 1 <= count <= MAX_PAGES or not isinstance(pages, list) or len(pages) != count:
        raise ValidationError({'file': 'Le résultat d’extraction du PDF est invalide.'})
    total = 0
    for number, page in enumerate(pages, 1):
        if (not isinstance(page, dict) or set(page) != {'page', 'text'} or type(page['page']) is not int
                or page['page'] != number or not _safe_text(page['text']) or len(page['text']) > MAX_PAGE_CHARS):
            raise ValidationError({'file': 'Le résultat d’extraction du PDF est invalide.'})
        total += len(page['text'])
        if total > MAX_TEXT_CHARS:
            raise ValidationError({'file': 'Le résultat d’extraction dépasse la limite de texte autorisée.'})
    return pages


def extract_uploaded_document(uploaded):
    # Restrict the format before reading any bytes or invoking the generic
    # validator, which also accepts formats the knowledge library does not.
    _, extension = safe_original_name(uploaded.name)
    if extension not in ('pdf', 'txt'):
        raise ValidationError({'file': 'La bibliothèque technique accepte uniquement PDF et TXT UTF-8.'})
    checked = check_attachment(uploaded)
    if extension == 'txt':
        text = checked.data.decode('utf-8-sig')
        if len(text) > MAX_TEXT_CHARS:
            raise ValidationError({'file': 'Le TXT dépasse 1 000 000 caractères. Découpez le document sans le tronquer.'})
        if not _safe_text(text):
            raise ValidationError({'file': 'Le TXT contient des caractères invalides.'})
        pages = [{'page': 1, 'text': text}]
    else:
        pages = _pdf_pages(checked.data)
    text_pages = sum(bool(page['text'].strip()) for page in pages)
    warnings = []
    if not text_pages:
        status = 'no_text'
        warnings.append(
            'Aucun texte exploitable n’a été extrait. Un PDF scanné ou un schéma visuel nécessite une lecture humaine ; aucun OCR ni interprétation d’image n’a été effectué.'
            if extension == 'pdf' else 'Le TXT ne contient aucun texte exploitable au-delà des espaces et sauts de ligne ; aucun contenu ne peut être indexé.'
        )
    elif text_pages < len(pages):
        status = 'partial'
        warnings.append('Certaines pages ne contiennent aucun texte exploitable. Les pages scannées et les schémas visuels ne sont pas lus par cette extraction ; aucun OCR n’a été effectué.')
    else:
        status = 'extracted'
    if extension == 'pdf' and text_pages:
        warnings.append('Seul le texte intégré au PDF est extrait ; les schémas, tableaux graphiques et images demandent une vérification humaine.')
    return {'checked': checked, 'pages': pages, 'page_count': len(pages), 'text_status': status, 'warnings': warnings}
