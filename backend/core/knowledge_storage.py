from pathlib import Path
import re

from django.conf import settings
from django.core.files.storage import FileSystemStorage


STORED_NAME = re.compile(r'^knowledge/[0-9a-f]{32}\.(pdf|txt)$')


def knowledge_storage():
    return FileSystemStorage(location=settings.MEDIA_ROOT, file_permissions_mode=0o600, directory_permissions_mode=0o700)


def knowledge_path(name):
    if not isinstance(name, str) or not STORED_NAME.fullmatch(name):
        raise ValueError('Invalid generated knowledge path')
    root = Path(knowledge_storage().location).resolve()
    candidate = root
    for component in name.split('/'):
        candidate = candidate / component
        if candidate.is_symlink():
            raise ValueError('Symlink knowledge paths are not permitted')
    candidate.resolve().relative_to(root)
    return candidate
