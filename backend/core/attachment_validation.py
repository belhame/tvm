"""File-format checks only. These checks are not an antivirus service."""

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import unicodedata
import warnings
import zipfile
import xml.etree.ElementTree as ET

from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import APIException, ValidationError


MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = ('pdf', 'jpg', 'jpeg', 'png', 'docx', 'xlsx', 'txt')
MIME_TYPES = {
    'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'txt': 'text/plain',
}


class AttachmentTooLarge(APIException):
    status_code = 413
    default_detail = 'La pièce jointe dépasse la limite de 10 Mio.'


@dataclass(frozen=True)
class CheckedAttachment:
    original_name: str
    extension: str
    mime_type: str
    data: bytes
    sha256: str


def safe_original_name(value):
    name = str(value or '').replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(character for character in unicodedata.normalize('NFC', name) if ord(character) >= 32 and ord(character) != 127)
    name = name.strip(' .')
    if not name or '.' not in name or '\x00' in name or any(0xD800 <= ord(character) <= 0xDFFF for character in name):
        raise ValidationError({'file': 'Le fichier doit posséder un nom et une extension pris en charge.'})
    extension = name.rsplit('.', 1)[-1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError({'file': 'Formats acceptés : PDF, JPEG, PNG, DOCX, XLSX et TXT UTF-8.'})
    if len(name) > 200:
        name = name[:199 - len(extension)].rstrip(' .') + '.' + extension
    return name, extension


def _check_pdf(data):
    if not data.startswith(b'%PDF-'):
        raise ValidationError({'file': 'Le contenu du fichier ne correspond pas à un PDF.'})
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'core.attachment_pdf_check'], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False,
            cwd=Path(__file__).resolve().parent.parent,
            env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationError({'file': 'Le PDF est trop complexe ou sa vérification a dépassé la limite de temps.'}) from exc
    try:
        checked = json.loads(result.stdout) if result.returncode == 0 else {}
    except (ValueError, UnicodeError):
        checked = {}
    if checked.get('valid') is not True:
        message = {
            'encrypted': 'Les PDF chiffrés ne sont pas acceptés. Fournissez une copie lisible sans mot de passe.',
            'pages': 'Le PDF doit contenir entre 1 et 500 pages.',
        }.get(checked.get('reason'), 'Le PDF est mal formé ou dépasse les limites de vérification.')
        raise ValidationError({'file': message})


def _check_image(data, extension):
    expected = 'PNG' if extension == 'png' else 'JPEG'
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format != expected or image.width < 1 or image.height < 1 or image.width * image.height > 25_000_000:
                    raise ValueError()
                image.load()
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValidationError({'file': 'Image invalide ou trop volumineuse : JPEG/PNG, 25 millions de pixels maximum.'}) from exc


def _check_xml_start(data, expected_tag):
    parser = ET.XMLPullParser(events=['start'])
    prefix = b''
    try:
        for offset in range(0, min(len(data), 1024 * 1024), 4096):
            block = data[offset:offset + 4096]
            prefix += block
            if b'<!DOCTYPE' in prefix.upper() or b'<!ENTITY' in prefix.upper():
                raise ValueError()
            parser.feed(block)
            for _, element in parser.read_events():
                if element.tag != expected_tag:
                    raise ValueError()
                return
    except (ET.ParseError, ValueError) as exc:
        raise ValidationError({'file': 'Structure XML Office invalide ou déclarations externes non prises en charge.'}) from exc
    raise ValidationError({'file': 'Structure principale Office absente ou invalide.'})


def _check_office(data, extension):
    main_path, main_type, root_tag = {
        'docx': ('word/document.xml', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml', '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document'),
        'xlsx': ('xl/workbook.xml', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml', '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook'),
    }[extension]
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 2000:
                raise ValueError()
            names, total = set(), 0
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                if (name in names or '\\' in name or path.is_absolute() or '..' in path.parts
                    or any(ord(character) < 32 for character in name)
                    or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1
                    or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError()
                if any(part.casefold().startswith('vba') or part.casefold() in ('activex', 'embeddings') for part in path.parts):
                    raise ValidationError({'file': 'Les macros, contrôles ActiveX et objets Office incorporés ne sont pas acceptés.'})
                if entry.file_size > 20 * 1024 * 1024 or (entry.file_size and entry.file_size > max(entry.compress_size, 1) * 200):
                    raise ValueError()
                total += entry.file_size
                if total > 40 * 1024 * 1024:
                    raise ValueError()
                names.add(name)
                # Read in bounded chunks to check CRC without extracting paths.
                with archive.open(entry) as stream:
                    read = 0
                    while block := stream.read(64 * 1024):
                        read += len(block)
                        if read > entry.file_size or read > 20 * 1024 * 1024:
                            raise ValueError()
            if '[Content_Types].xml' not in names or main_path not in names:
                raise ValueError()
            if archive.getinfo('[Content_Types].xml').file_size > 1024 * 1024:
                raise ValueError()
            types = archive.read('[Content_Types].xml')
            if b'<!DOCTYPE' in types.upper() or b'<!ENTITY' in types.upper():
                raise ValueError()
            root = ET.fromstring(types)
            if root.tag != '{http://schemas.openxmlformats.org/package/2006/content-types}Types':
                raise ValueError()
            main_found = False
            for element in root:
                content_type = element.attrib.get('ContentType', '')
                if 'macroenabled' in content_type.casefold() or 'vba' in content_type.casefold():
                    raise ValidationError({'file': 'Les formats Office avec macros ne sont pas acceptés.'})
                if element.attrib.get('PartName') == '/' + main_path and content_type == main_type:
                    main_found = True
            if not main_found:
                raise ValueError()
            _check_xml_start(archive.read(main_path), root_tag)
    except ValidationError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, ET.ParseError, NotImplementedError) as exc:
        raise ValidationError({'file': 'Document Office invalide, chiffré ou trop complexe. Seuls DOCX/XLSX non macro sont acceptés.'}) from exc


def check_attachment(uploaded):
    original_name, extension = safe_original_name(uploaded.name)
    if uploaded.size > MAX_FILE_SIZE:
        raise AttachmentTooLarge()
    data = bytearray()
    for chunk in uploaded.chunks():
        data.extend(chunk)
        if len(data) > MAX_FILE_SIZE:
            raise AttachmentTooLarge()
    if not data:
        raise ValidationError({'file': 'Le fichier est vide.'})
    content = bytes(data)
    if extension == 'pdf':
        _check_pdf(content)
    elif extension in ('jpg', 'jpeg', 'png'):
        _check_image(content, extension)
    elif extension in ('docx', 'xlsx'):
        _check_office(content, extension)
    else:
        try:
            text = content.decode('utf-8-sig')
            if any(ord(character) < 32 and character not in '\n\r\t' for character in text):
                raise ValueError()
        except (UnicodeError, ValueError) as exc:
            raise ValidationError({'file': 'Le document TXT doit être du texte UTF-8 sans contenu binaire.'}) from exc
    return CheckedAttachment(original_name, extension, MIME_TYPES[extension], content, hashlib.sha256(content).hexdigest())
