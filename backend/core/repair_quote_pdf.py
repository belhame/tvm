"""Repair quote PDFs rendered only from frozen public facts, never live records."""
from copy import deepcopy
from datetime import date, datetime
from io import BytesIO
import re
import unicodedata

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Spacer, TableStyle
from rest_framework.exceptions import ValidationError

from .pdf import BLUE, WIDTH, _bar, _date, _document, _fields, _header, _p, _styles, _table
from .repair_quote_money import repair_quote_amounts


_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')
_TIMESTAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z')


def _text(value, field, *, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValidationError({'quote': f'Le champ {field} du devis est invalide.'})
    if any(unicodedata.category(character) in ('Cc', 'Cs') and character not in '\n\r\t' for character in value):
        raise ValidationError({'quote': f'Caractère interdit dans {field}.'})
    return value


def _calendar(value, field):
    try:
        if not isinstance(value, str) or not _DATE.fullmatch(value):
            raise ValueError()
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({'quote': f'La date {field} du devis est invalide.'}) from exc


def validate_repair_quote_snapshot(snapshot):
    """Verify an issued snapshot exactly; no normalization of its financial facts."""
    if not isinstance(snapshot, dict) or type(snapshot.get('version')) is not int or snapshot['version'] != 1:
        raise ValidationError({'quote': 'Version du devis de réparation inconnue.'})
    allowed = {'version', 'reference', 'issued_on', 'issued_at', 'valid_until', 'service_request', 'equipment', 'client', 'amounts', 'terms'}
    if set(snapshot) - allowed:
        raise ValidationError({'quote': 'Le devis contient des données non prises en charge.'})
    result = deepcopy(snapshot)
    _text(result.get('reference'), 'reference', maximum=80, required=True)
    issued_on = _calendar(result.get('issued_on'), 'issued_on')
    try:
        issued_at = result.get('issued_at')
        if not isinstance(issued_at, str) or not _TIMESTAMP.fullmatch(issued_at):
            raise ValueError()
        if datetime.fromisoformat(issued_at).tzinfo is None:
            raise ValueError()
    except ValueError as exc:
        raise ValidationError({'quote': 'La date et l’heure d’émission du devis sont invalides.'}) from exc
    result.setdefault('valid_until', None)
    if result['valid_until'] is not None and _calendar(result['valid_until'], 'valid_until') < issued_on:
        raise ValidationError({'quote': 'La validité du devis ne peut pas précéder son émission.'})
    sections = {
        'service_request': {'id': None, 'call_number': 40, 'client_reference': 120, 'subject': 200},
        'equipment': {'id': None, 'serial_number': 120, 'model': 120, 'brand': 100},
        'client': {'id': None, 'name': 200, 'contact_name': 150, 'email': 254, 'phone': 40,
                   'address': 4000, 'city': 100, 'postal_code': 20, 'country': 80, 'tax_id': 80},
    }
    required = {('service_request', 'call_number'), ('equipment', 'serial_number'), ('equipment', 'model'), ('client', 'name')}
    for section, fields in sections.items():
        values = result.get(section)
        if not isinstance(values, dict) or set(values) - set(fields):
            raise ValidationError({'quote': f'Les informations {section} du devis sont invalides.'})
        for key, limit in fields.items():
            if key == 'id':
                if key in values and (type(values[key]) is not int or values[key] < 1):
                    raise ValidationError({'quote': f'Identifiant {section} invalide.'})
                continue
            values.setdefault(key, '')
            _text(values[key], f'{section}.{key}', maximum=limit, required=(section, key) in required)
    result.setdefault('terms', '')
    _text(result['terms'], 'terms', maximum=10000)
    amounts = result.get('amounts')
    if not isinstance(amounts, dict) or not isinstance(amounts.get('lines'), list):
        raise ValidationError({'quote': 'Les lignes et montants du devis sont absents.'})
    inputs = []
    for line in amounts['lines']:
        if not isinstance(line, dict) or set(line) != {'description', 'quantity', 'unit_ht', 'total_ht'}:
            raise ValidationError({'quote': 'Une ligne du devis émis est invalide.'})
        inputs.append({key: line[key] for key in ('description', 'quantity', 'unit_ht')})
    recomputed = repair_quote_amounts(inputs, vat_rate=amounts.get('vat_rate'), currency=amounts.get('currency'),
        discount_kind=amounts.get('discount_kind'), discount_value=amounts.get('discount_value'))
    if set(amounts) != set(recomputed) or amounts != recomputed or type(amounts.get('precision')) is not int or type(amounts.get('fully_discounted')) is not bool:
        raise ValidationError({'quote': 'Les montants du devis émis sont incohérents.'})
    return result


def repair_quote_pdf(snapshot):
    """Return deterministic A4 bytes; client decisions remain outside this file."""
    facts = validate_repair_quote_snapshot(snapshot)
    styles = _styles()
    styles['money'] = ParagraphStyle('TVMRepairQuoteMoney', parent=styles['body'], alignment=2)
    output = BytesIO()
    document, footer = _document(output, 'Devis de réparation', facts['reference'])
    record, equipment, client, amounts = (facts[key] for key in ('service_request', 'equipment', 'client', 'amounts'))
    issued_on = date.fromisoformat(facts['issued_on'])
    story = _header('Devis de réparation', record['call_number'], issued_on, styles, client_reference=record['client_reference'])
    metadata = [('N° de devis', facts['reference']), ('Émis le', _date(issued_on)), ('Objet', 'Réparation de l’onduleur hors garantie')]
    if facts['valid_until']:
        metadata.append(('Valable jusqu’au', _date(date.fromisoformat(facts['valid_until']))))
    story += [_bar('DEVIS DE RÉPARATION', styles), _fields(metadata, styles), Spacer(1, 9)]
    client_fields = [('Raison sociale', client['name'])]
    for key, label in [('tax_id', 'Matricule fiscal client'), ('contact_name', 'Contact'), ('email', 'E-mail'), ('phone', 'Téléphone'), ('address', 'Adresse')]:
        if client[key]:
            client_fields.append((label, client[key]))
    locality = ' '.join(filter(None, (client['postal_code'], client['city'])))
    if locality:
        client_fields.append(('Ville / code postal', locality))
    if client['country']:
        client_fields.append(('Pays', client['country']))
    story += [_bar('CLIENT', styles), _fields(client_fields, styles), Spacer(1, 9), _bar('ONDULEUR', styles), _fields([
        ('Numéro de série', equipment['serial_number']), ('Modèle', equipment['model']), ('Marque', equipment['brand']),
    ], styles), Spacer(1, 9)]
    currency = amounts['currency']
    rows = [[_p('Désignation', styles, 'white'), _p('Qté', styles, 'white'),
             _p(f'Prix unitaire HT ({currency})', styles, 'white'), _p(f'Total HT ({currency})', styles, 'white')]]
    for line in amounts['lines']:
        rows.append([_p(line['description'], styles), _p(line['quantity'], styles, 'money'),
                     _p(line['unit_ht'], styles, 'money'), _p(line['total_ht'], styles, 'money')])
    table = _table(rows, [95 * mm, 15 * mm, 38 * mm, 38 * mm], repeat=1)
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), BLUE)]))
    if amounts['discount_kind'] == 'percent':
        discount_label = f"Remise ({amounts['discount_value']} %)"
    elif amounts['discount_kind'] == 'fixed':
        discount_label = 'Remise HT (montant fixe)'
    else:
        discount_label = 'Remise HT'
    reduction = amounts['discount_ht']
    if reduction.strip('0.'):
        reduction = '-' + reduction
    totals = [('Sous-total HT', amounts['subtotal_ht']), (discount_label, reduction), ('Net HT', amounts['net_ht']),
              (f"TVA ({amounts['vat_rate']} %)", amounts['vat_amount']), ('Total TTC', amounts['total_ttc'])]
    totals_table = _table([[_p(label, styles, 'white'), _p(f'{value} {currency}', styles, 'money')] for label, value in totals],
                          [WIDTH - 58 * mm, 58 * mm])
    totals_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, -1), BLUE),
        ('BACKGROUND', (1, -1), (1, -1), colors.HexColor('#e0f1ff'))]))
    story += [table, Spacer(1, 9), totals_table, Spacer(1, 9)]
    if amounts['fully_discounted']:
        story += [_bar('REMISE TOTALE', styles), _p('Une remise totale est accordée sur les prestations de ce devis.', styles), Spacer(1, 9)]
    if facts['terms']:
        story += [_bar('CONDITIONS DU DEVIS', styles), _p(facts['terms'], styles), Spacer(1, 9)]
    story += [_p('Ce devis n’est pas une facture. Il présente une proposition de réparation et ne constitue ni une preuve de paiement, ni un accord signé du client.', styles, 'small'),
              _p('Les informations sont conservées telles qu’elles étaient lors de l’émission. Une décision client est enregistrée séparément.', styles, 'small')]
    def issued_canvas(*args, **kwargs):
        kwargs['invariant'] = 1
        canvas = Canvas(*args, **kwargs)
        canvas.setDateFormatter(lambda *parts: 'D:' + issued_on.strftime('%Y%m%d'))
        return canvas
    document.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=issued_canvas)
    return output.getvalue()
