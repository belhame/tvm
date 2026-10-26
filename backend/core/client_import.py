"""Preview and import private client CSV files without merging business records.

Only new clients are written. Source files and contact details never become
repository fixtures; previews remain private authenticated API responses.
"""

import csv
import hashlib
import io
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction

from .models import AuditLog, Client
from .serializers import ClientSerializer


MAX_CLIENT_BYTES = 2 * 1024 * 1024
MAX_CLIENT_ROWS = 5000
CLIENT_COLUMNS = ('name', 'contact_name', 'tax_id', 'email', 'phone', 'address', 'city', 'postal_code', 'country', 'notes')
MULTILINE_COLUMNS = {'address', 'notes'}


class ClientImportError(ValueError):
    pass


def normalized_name(value):
    # Do not remove accents or punctuation: similarity is not a client identity.
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def normalized_tax_id(value):
    return ''.join(unicodedata.normalize('NFKC', value).split()).casefold()


def check_actor(actor):
    if actor is None or not actor.is_active or actor.effective_role not in ('admin', 'manager'):
        raise PermissionDenied('Seul un administrateur ou responsable SAV actif peut importer les clients.')


def _validate_cell(value, column):
    value = value.strip()
    for character in value:
        category = unicodedata.category(character)
        if category in ('Cc', 'Cs') and not (column in MULTILINE_COLUMNS and character in '\r\n\t'):
            raise ClientImportError('Caractère de contrôle interdit dans cette ligne.')
    if column in ('address', 'notes') and len(value) > 4000:
        raise ClientImportError(f'Le champ {column} est limité à 4000 caractères.')
    return value


def parse_clients_csv(data, filename):
    if len(data) > MAX_CLIENT_BYTES:
        raise ClientImportError('Le fichier clients dépasse la limite de 2 Mio.')
    if Path(filename).suffix.casefold() != '.csv':
        raise ClientImportError('Joignez un fichier CSV encodé en UTF-8.')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ClientImportError('Le fichier doit être encodé en UTF-8, avec ou sans BOM.') from exc
    if '\x00' in text:
        raise ClientImportError('Le fichier contient un caractère nul interdit.')
    first_line = text.splitlines()[0] if text.splitlines() else ''
    delimiter = ';' if first_line.count(';') >= first_line.count(',') else ','
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=True)
    try:
        header = [cell.strip().casefold() for cell in next(reader)]
    except (StopIteration, csv.Error) as exc:
        raise ClientImportError('Le fichier doit contenir un en-tête CSV et au moins un client.') from exc
    if len(header) != len(set(header)):
        raise ClientImportError('Les noms de colonnes ne doivent pas être dupliqués.')
    if 'name' not in header or any(column not in CLIENT_COLUMNS for column in header):
        raise ClientImportError('Colonnes autorisées : ' + ', '.join(CLIENT_COLUMNS) + '. La colonne name est obligatoire. Les identifiants et mots de passe ne sont jamais importés.')
    rows = []
    try:
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            if len(rows) >= MAX_CLIENT_ROWS:
                raise ClientImportError('Le fichier est limité à 5000 lignes clients.')
            line = reader.line_num
            row = {'line': line, 'status': 'create', 'name': '', 'data': {}, 'errors': [], 'existing_id': None}
            rows.append(row)
            if len(cells) != len(header):
                row.update(status='invalid', errors=['Le nombre de cellules ne correspond pas à l’en-tête.'])
                continue
            try:
                fields = {column: _validate_cell(value, column) for column, value in zip(header, cells)}
            except ClientImportError as exc:
                row.update(status='invalid', errors=[str(exc)])
                continue
            row['name'] = fields.get('name', '')[:200]
            # A missing country is unknown. Do not invent the model's ordinary
            # form default for an imported source with no country information.
            fields = {column: fields.get(column, '') for column in CLIENT_COLUMNS}
            serializer = ClientSerializer(data=fields)
            if not serializer.is_valid():
                row.update(status='invalid', errors=[f'{key} : {message}' for key, messages in serializer.errors.items() for message in messages])
                continue
            row['data'] = dict(serializer.validated_data)
    except csv.Error as exc:
        raise ClientImportError('Le fichier CSV est mal formé ou contient une cellule trop longue.') from exc
    if not rows:
        raise ClientImportError('Le fichier ne contient aucune ligne client.')
    return rows


def _mark_file_conflicts(rows):
    names = defaultdict(list)
    tax_ids = defaultdict(list)
    for row in rows:
        if row['status'] == 'invalid':
            continue
        names[normalized_name(row['data']['name'])].append(row)
        if tax_id := normalized_tax_id(row['data'].get('tax_id', '')):
            tax_ids[tax_id].append(row)
    for group in names.values():
        if len(group) < 2:
            continue
        if all(row['data'] == group[0]['data'] for row in group[1:]):
            for row in group[1:]:
                row.update(status='duplicate', errors=['Ligne identique déjà présente dans ce fichier.'])
        else:
            for row in group:
                row.update(status='conflict', errors=['Plusieurs lignes portent ce nom avec des données différentes. Aucun rapprochement automatique.'])
    for group in tax_ids.values():
        if len({normalized_name(row['data']['name']) for row in group}) > 1:
            for row in group:
                row.update(status='conflict', errors=['Ce matricule fiscal figure sous plusieurs noms dans le fichier. Vérifiez ces fiches.'])


def _mark_existing(rows):
    names = defaultdict(list)
    tax_ids = defaultdict(list)
    for client in Client.objects.all().values('id', *CLIENT_COLUMNS):
        names[normalized_name(client['name'])].append(client)
        if tax_id := normalized_tax_id(client['tax_id']):
            tax_ids[tax_id].append(client)
    for row in rows:
        if row['status'] != 'create':
            continue
        values = row['data']
        matches = names.get(normalized_name(values['name']), [])
        tax_matches = tax_ids.get(normalized_tax_id(values.get('tax_id', '')), [])
        if len(matches) > 1 or any(client['id'] not in {match['id'] for match in matches} for client in tax_matches):
            row.update(status='conflict', errors=['Nom ambigu ou matricule fiscal déjà présent sous un autre nom. Vérifiez les fiches existantes.'])
            continue
        if not matches:
            continue
        existing = matches[0]
        row['existing_id'] = existing['id']
        differing = [key for key, value in values.items() if key != 'name' and value and existing[key] and value != existing[key]]
        missing = [key for key, value in values.items() if key != 'name' and value and not existing[key]]
        if differing:
            row.update(status='conflict', errors=['Ce client existe avec des valeurs différentes : ' + ', '.join(differing) + '. Aucune donnée écrasée.'])
        else:
            row['status'] = 'existing'
            if missing:
                row['errors'] = ['Ce client existe. Informations à compléter manuellement : ' + ', '.join(missing) + '. Aucune donnée modifiée.']


def import_clients_csv(data, filename, *, actor, apply=False, expected_sha256=None):
    check_actor(actor)
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and expected_sha256 != digest:
        raise ClientImportError('Le fichier a changé depuis l’aperçu. Relancez la vérification.')
    rows = parse_clients_csv(data, filename)
    _mark_file_conflicts(rows)
    created = 0
    with transaction.atomic():
        if apply:
            # Cross-worker serialization avoids a duplicate created by two
            # imports reviewed at the same time; existing rows are never edited.
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_advisory_xact_lock(%s)', [845230107])
        _mark_existing(rows)
        if apply:
            for row in rows:
                if row['status'] != 'create':
                    continue
                client = Client.objects.create(**row['data'])
                row['created_id'] = client.pk
                AuditLog.objects.create(actor=actor, action='import_create', resource='client', resource_id=str(client.pk))
                created += 1
    counts = Counter(row['status'] for row in rows)
    return {
        'mode': 'apply' if apply else 'preview', 'sha256': digest, 'applied': apply,
        'summary': {'total': len(rows), **{key: counts.get(key, 0) for key in ('create', 'existing', 'duplicate', 'conflict', 'invalid')}, 'created': created, 'skipped': len(rows) - created if apply else 0},
        'rows': rows,
    }
