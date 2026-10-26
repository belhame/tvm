"""Deterministic diagnostic prices and PDFs built only from issued snapshots.

A quote is a proposal. Its frozen facts never inherit a later invoice, payment,
waiver note or staff identity from a mutable dossier.
"""
from copy import deepcopy
from datetime import date
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from io import BytesIO
import re
import unicodedata

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Spacer, TableStyle
from rest_framework.exceptions import ValidationError

from .pdf import _bar, _date, _document, _fields, _header, _p, _styles, _table


CURRENCY_PRECISION = {'TND': 3, 'EUR': 2, 'USD': 2}
_DECIMAL_TEXT = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z')


def _decimal(value, field, *, scale, maximum):
    if value is None or isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError({field: 'Indiquez une valeur décimale explicite, sous forme de texte.'})
    if isinstance(value, str):
        value = value.strip()
        if len(value) > 80 or not _DECIMAL_TEXT.fullmatch(value):
            raise ValidationError({field: 'Utilisez un nombre décimal, sans séparateur de milliers ni exposant.'})
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError({field: 'Valeur décimale invalide.'}) from exc
    if not number.is_finite() or number < 0 or number > maximum:
        raise ValidationError({field: f'Indiquez une valeur comprise entre 0 et {maximum}.'})
    # A DecimalField may pad a stored EUR amount to three places; insignificant
    # database zeros do not change its currency precision. Raw text stays strict.
    scale_value = number.normalize() if isinstance(value, Decimal) else number
    if scale_value.as_tuple().exponent < -scale:
        raise ValidationError({field: f'Ce champ accepte au maximum {scale} décimales.'})
    # A negative zero must never print as a credit or a negative quote.
    return Decimal(0) if number == 0 else number


def quote_amounts(amount_ht, vat_rate, currency='TND'):
    """Return canonical decimal strings; the VAT rate has no implicit default."""
    if not isinstance(currency, str) or currency.strip().upper() not in CURRENCY_PRECISION:
        raise ValidationError({'currency': 'Choisissez TND, EUR ou USD.'})
    currency = currency.strip().upper()
    precision = CURRENCY_PRECISION[currency]
    # Do not inherit another library's global Decimal precision or trap policy.
    with localcontext(Context(prec=96, rounding=ROUND_HALF_UP)):
        unit = Decimal(1).scaleb(-precision)
        maximum = Decimal('999999999') + Decimal(1) - unit
        amount = _decimal(amount_ht, 'price_ht', scale=precision, maximum=maximum)
        rate = _decimal(vat_rate, 'vat_rate', scale=2, maximum=Decimal('100'))
        amount = amount.quantize(unit, rounding=ROUND_HALF_UP)
        tax = (amount * rate / Decimal('100')).quantize(unit, rounding=ROUND_HALF_UP)
        total = (amount + tax).quantize(unit, rounding=ROUND_HALF_UP)
        return {
            'currency': currency,
            'precision': precision,
            'amount_ht': format(amount, f'.{precision}f'),
            'vat_rate': format(rate.normalize(), 'f'),
            'vat_amount': format(tax, f'.{precision}f'),
            'total_ttc': format(total, f'.{precision}f'),
        }


def _text(value, field, *, required=False, maximum=4000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValidationError({'quote': f'Le champ {field} du devis est invalide.'})
    for character in value:
        if unicodedata.category(character) in ('Cc', 'Cs') and character not in '\n\r\t':
            raise ValidationError({'quote': f'Caractère interdit dans {field}.'})
    if required and not value.strip():
        raise ValidationError({'quote': f'Le champ {field} du devis est obligatoire.'})
    return value


def validate_quote_snapshot(snapshot):
    """Validate stored facts without rewriting them or consulting current data."""
    if not isinstance(snapshot, dict) or type(snapshot.get('version')) is not int or snapshot['version'] != 1:
        raise ValidationError({'quote': 'Version du devis émis inconnue.'})
    allowed = {'version', 'reference', 'issued_on', 'service_request', 'equipment', 'client', 'diagnosis', 'amounts', 'fee_mode', 'free_status', 'quote_notes'}
    if set(snapshot) - allowed:
        raise ValidationError({'quote': 'Le devis contient des données non prises en charge.'})
    result = deepcopy(snapshot)
    _text(result.get('reference'), 'reference', required=True, maximum=80)
    issued_on = result.get('issued_on')
    try:
        if not isinstance(issued_on, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', issued_on):
            raise ValueError()
        date.fromisoformat(issued_on)
    except ValueError as exc:
        raise ValidationError({'quote': 'La date d’émission du devis est invalide.'}) from exc
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
            _text(values[key], f'{section}.{key}', required=(section, key) in required, maximum=limit)
    _text(result.get('diagnosis'), 'diagnosis', required=True, maximum=20000)
    result.setdefault('quote_notes', '')
    _text(result['quote_notes'], 'quote_notes', maximum=4000)
    amounts = result.get('amounts')
    if not isinstance(amounts, dict):
        raise ValidationError({'quote': 'Les montants du devis sont absents.'})
    recomputed = quote_amounts(amounts.get('amount_ht'), amounts.get('vat_rate'), amounts.get('currency'))
    if set(amounts) != set(recomputed) or amounts != recomputed or type(amounts.get('precision')) is not int:
        raise ValidationError({'quote': 'Les montants du devis émis sont incohérents.'})
    free_status = result.get('free_status')
    fee_mode = result.get('fee_mode')
    if fee_mode not in ('billable', 'free'):
        raise ValidationError({'quote': 'Le mode de frais du devis est invalide.'})
    if free_status not in (None, 'proposed', 'approved'):
        raise ValidationError({'quote': 'État de gratuité du devis inconnu.'})
    if free_status is not None and Decimal(amounts['total_ttc']) != 0:
        raise ValidationError({'quote': 'Un devis de diagnostic offert doit avoir des montants nuls.'})
    if free_status is None and Decimal(amounts['amount_ht']) == 0:
        raise ValidationError({'quote': 'Le devis nul doit préciser la proposition de gratuité.'})
    if (fee_mode == 'free') != (free_status is not None):
        raise ValidationError({'quote': 'Le mode de frais ne correspond pas à la gratuité du devis.'})
    return result


def diagnostic_quote_pdf(snapshot):
    """Render an A4 quote from its issued public snapshot, never the live case."""
    facts = validate_quote_snapshot(snapshot)
    styles = _styles()
    output = BytesIO()
    document, footer = _document(output, 'Devis de diagnostic', facts['reference'])
    request, equipment, client, amounts = (facts[key] for key in ('service_request', 'equipment', 'client', 'amounts'))
    issued_on = date.fromisoformat(facts['issued_on'])
    story = _header('Devis de diagnostic', request['call_number'], issued_on, styles,
                    client_reference=request['client_reference'])
    story += [_bar('DEVIS DE DIAGNOSTIC', styles), _fields([
        ('N° de devis', facts['reference']), ('Émis le', _date(issued_on)),
        ('Objet', 'Diagnostic de l’onduleur non réparable et préparation de son retour'),
    ], styles), Spacer(1, 9)]
    story += [_bar('CLIENT', styles), _fields([
        ('Raison sociale', client['name']), ('Matricule fiscal client', client['tax_id']),
        ('Contact', client['contact_name']), ('E-mail', client['email']), ('Téléphone', client['phone']),
        ('Adresse', client['address']), ('Ville / code postal', ' '.join(filter(None, (client['postal_code'], client['city'])))),
        ('Pays', client['country']),
    ], styles), Spacer(1, 9)]
    story += [_bar('ÉQUIPEMENT D’ORIGINE', styles), _fields([
        ('Numéro de série', equipment['serial_number']), ('Modèle', equipment['model']), ('Marque', equipment['brand']),
    ], styles), Spacer(1, 9), _bar('DIAGNOSTIC COMMUNIQUÉ', styles), _p(facts['diagnosis'], styles), Spacer(1, 9)]
    currency = amounts['currency']
    price = _table([
        [_p('Prestation', styles, 'white'), _p('Qté', styles, 'white'), _p(f'Prix HT ({currency})', styles, 'white'), _p('TVA', styles, 'white'), _p(f'Total HT ({currency})', styles, 'white')],
        [_p('Diagnostic de l’onduleur', styles), _p('1', styles), _p(amounts['amount_ht'], styles), _p(amounts['vat_rate'] + ' %', styles), _p(amounts['amount_ht'], styles)],
    ], [78 * mm, 12 * mm, 34 * mm, 22 * mm, 40 * mm], repeat=1)
    price.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#117cbb'))]))
    story += [price, Spacer(1, 7), _fields([
        ('Total HT', f"{amounts['amount_ht']} {currency}"),
        (f"TVA ({amounts['vat_rate']} %)", f"{amounts['vat_amount']} {currency}"),
        ('Total TTC', f"{amounts['total_ttc']} {currency}"),
    ], styles), Spacer(1, 9)]
    if facts['quote_notes']:
        story += [_bar('PRÉCISIONS DU DEVIS', styles), _p(facts['quote_notes'], styles), Spacer(1, 9)]
    if facts.get('free_status') == 'proposed':
        story += [_bar('GRATUITÉ PROPOSÉE', styles), _p('Diagnostic proposé à titre gratuit. La proposition était en attente de validation interne lors de l’émission de ce devis.', styles), Spacer(1, 7)]
    elif facts.get('free_status') == 'approved':
        story += [_bar('GRATUITÉ VALIDÉE', styles), _p('Diagnostic offert, avec gratuité validée lors de l’émission de ce devis.', styles), Spacer(1, 7)]
    story += [_p('Ce devis présente les frais de diagnostic proposés. Il ne vaut ni facture, ni preuve de paiement, ni accord signé du client.', styles, 'small'),
              _p('Les coordonnées légales détaillées de l’émetteur ne sont pas renseignées dans ce document.', styles, 'small'),
              _p('Les informations de ce devis sont conservées telles qu’elles ont été enregistrées à son émission.', styles, 'small')]
    def issued_canvas(*args, **kwargs):
        kwargs['invariant'] = 1
        canvas = Canvas(*args, **kwargs)
        # Stable PDF bytes, with the issued calendar date in metadata instead
        # of the time of a later download. No hour or timezone is invented.
        canvas.setDateFormatter(lambda *parts: 'D:' + issued_on.strftime('%Y%m%d'))
        return canvas
    document.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=issued_canvas)
    return output.getvalue()
