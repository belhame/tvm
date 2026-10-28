"""Render an issued logistics snapshot once; the service retains these bytes.

This form records preparation only. It does not render business records or
read current client/equipment data, and it never confirms a physical handoff.
"""

from datetime import datetime
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Spacer, TableStyle

from .pdf import TVMMark, _document, _p, _styles, _table


WIDTH = 186 * mm
BLUE = colors.HexColor('#117cbb')


def _text(record, key, limit, *, required=False):
    value = record.get(key, '')
    if value is None and not required:
        return ''
    if (not isinstance(value, str) or len(value) > limit
            or any((ord(char) < 32 and char not in '\n\r\t') or 0xD800 <= ord(char) <= 0xDFFF for char in value)
            or (required and not value.strip())):
        raise ValueError(f'Champ de bon de livraison invalide : {key}.')
    return value.replace('\r\n', '\n').replace('\r', '\n').replace('\t', '    ')


def _object(record, key):
    value = record.get(key)
    if not isinstance(value, dict):
        raise ValueError('Structure du bon de livraison invalide.')
    return value


def _fields(rows, styles):
    table = _table([[_p(label, styles, 'white'), _p(value, styles)] for label, value in rows],
                   [45 * mm, WIDTH - 45 * mm])
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), BLUE)]))
    return table


def _section(title, styles):
    table = _table([[_p(title, styles, 'section')]], [WIDTH], grid=False, padding=4)
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), BLUE)]))
    return table


def render_delivery_note(snapshot: dict) -> bytes:
    """Return a public, whitelist-only PDF from a version-one issued snapshot.

    IDs and private/financial extra keys are deliberately not printed. The
    calling service authorizes and validates the mission set before issuance.
    """
    if not isinstance(snapshot, dict) or type(snapshot.get('version')) is not int or snapshot['version'] != 1:
        raise ValueError('Version de bon de livraison non prise en charge.')
    lines = snapshot.get('lines')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise ValueError('Un bon de livraison contient de 1 à 100 matériels.')
    reference = _text(snapshot, 'reference', 80, required=True)
    issued_raw = _text(snapshot, 'issued_at', 64, required=True)
    try:
        issued_at = datetime.fromisoformat(issued_raw)
        if not timezone.is_aware(issued_at):
            raise ValueError()
    except (TypeError, ValueError) as exc:
        raise ValueError('La date d’émission doit préciser son fuseau horaire.') from exc
    client = _object(snapshot, 'client')
    courier = _object(snapshot, 'courier')
    prepared_by = _object(snapshot, 'prepared_by')
    client_name = _text(client, 'name', 200, required=True)
    client_address = _text(client, 'address', 4000)
    city = _text(client, 'city', 100)
    postal_code = _text(client, 'postal_code', 20)
    country = _text(client, 'country', 80)
    courier_name = _text(courier, 'name', 301, required=True)
    prepared_name = _text(prepared_by, 'name', 301, required=True)
    courier_kind = courier.get('courier_kind')
    if courier_kind not in ('internal', 'client'):
        raise ValueError('Type de livreur invalide.')
    comment = _text(snapshot, 'comment', 4000)

    styles = _styles()
    output = BytesIO()
    document, footer = _document(output, 'Bon de livraison', reference)
    header = _table([[TVMMark(), _p('BON DE LIVRAISON', styles, 'head')]], [45 * mm, WIDTH - 45 * mm], grid=False, padding=0)
    issued_local = timezone.localtime(issued_at)
    story = [header, Spacer(1, 6), _fields([
        ('N° de bon de livraison', reference),
        ('Émis le', f'{issued_local:%d/%m/%Y à %H:%M} ({issued_local.tzinfo})'),
        ('Préparé par', prepared_name),
        ('Livreur', f'{courier_name} · {"Livreur TVM" if courier_kind == "internal" else "Livreur client"}'),
    ], styles), Spacer(1, 6), _p('Préparé — ne vaut pas preuve de remise physique.', styles, 'danger'), Spacer(1, 7),
        _section('CLIENT DESTINATAIRE', styles), _fields([
            ('Client', client_name),
            ('Adresse client', '\n'.join(value for value in [client_address, ' '.join(value for value in [postal_code, city] if value), country] if value)),
        ], styles), Spacer(1, 7), _section(f'MATÉRIELS PRÉPARÉS · {len(lines)} ONDULEUR(S)', styles)]
    rows = [[_p('N°', styles, 'white'), _p('Références du dossier', styles, 'white'),
             _p('Matériel préparé', styles, 'white'), _p('Destination de cette ligne', styles, 'white')]]
    for index, line in enumerate(lines, 1):
        if not isinstance(line, dict):
            raise ValueError('Ligne de bon de livraison invalide.')
        kind = line.get('kind')
        if kind not in ('delivery', 'return'):
            raise ValueError('Nature de mission invalide.')
        call_number = _text(line, 'call_number', 120, required=True)
        client_reference = _text(line, 'client_reference', 120)
        serial = _text(line, 'serial_number', 120, required=True)
        original_serial = _text(line, 'original_serial_number', 120, required=True)
        brand = _text(line, 'brand', 100)
        model = _text(line, 'model', 120)
        destination = _text(line, 'delivery_address', 4000)
        dossier = f'N° d’appel TVM : {call_number}\nN° d’appel client : {client_reference or "Non renseigné"}'
        equipment = '\n'.join([
            'Livraison' if kind == 'delivery' else 'Retour au client',
            ' '.join(value for value in [brand, model] if value) or 'Modèle non renseigné',
            f'S/N à remettre : {serial}',
            *([f'S/N d’origine : {original_serial}'] if original_serial != serial else []),
            'Quantité : 1',
        ])
        rows.append([_p(index, styles), _p(dossier, styles), _p(equipment, styles), _p(destination, styles)])
    materials = _table(rows, [8 * mm, 46 * mm, 66 * mm, 66 * mm], repeat=1, padding=4)
    materials.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), BLUE)]))
    story += [materials, Spacer(1, 7)]
    if comment:
        story += [_section('COMMENTAIRE', styles), _p(comment, styles), Spacer(1, 7)]
    story += [_p('Ce bon décrit les matériels préparés à la date d’émission. La remise physique et son destinataire sont enregistrés séparément dans le suivi logistique.', styles, 'small')]
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
