"""Storage helpers that expose no public URL and reject non-generated paths."""

from pathlib import Path
import re

from django.conf import settings
from django.core.files.storage import FileSystemStorage


STORED_NAME = re.compile(r'^requests/[1-9][0-9]*/[0-9a-f]{32}\.(pdf|jpg|jpeg|png|docx|xlsx|txt)$')


def private_storage():
    return FileSystemStorage(
        location=getattr(settings, 'MEDIA_ROOT', settings.BASE_DIR / 'media'),
        file_permissions_mode=0o600, directory_permissions_mode=0o700,
    )


def private_path(name):
    if not isinstance(name, str) or not STORED_NAME.fullmatch(name):
        raise ValueError('Invalid generated document path')
    root = Path(private_storage().location).resolve()
    candidate = root
    for component in name.split('/'):
        candidate = candidate / component
        if candidate.is_symlink():
            raise ValueError('Symlink document paths are not permitted')
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError('Document path leaves private storage') from exc
    return candidate
