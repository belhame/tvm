"""Exact repair quote arithmetic, independent of mutable Decimal settings.

Round each line first, sum those displayed amounts, deduct the rounded HT
discount, then round VAT on the resulting net HT. A quote is never an invoice.
"""
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re
import unicodedata

from rest_framework.exceptions import ValidationError

from .diagnostic_quote import CURRENCY_PRECISION


MAX_LINES = 100
MAX_DESCRIPTION = 2000
MAX_QUANTITY = Decimal('999999.999')
_DECIMAL_TEXT = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z')


def _number(value, field, *, scale, maximum, positive=False):
    """Inspect exponents without normalizing arbitrarily tiny Decimal inputs."""
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError({field: 'Saisissez une valeur décimale explicite, sous forme de texte.'})
    raw_decimal = isinstance(value, Decimal)
    if isinstance(value, str):
        value = value.strip()
        if len(value) > 80 or not _DECIMAL_TEXT.fullmatch(value):
            raise ValidationError({field: 'Utilisez un nombre décimal sans exposant ni séparateur de milliers.'})
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError({field: 'Valeur décimale invalide.'}) from exc
    if not number.is_finite() or number < 0 or number > maximum or (positive and number == 0):
        minimum = 'strictement supérieure à 0' if positive else 'supérieure ou égale à 0'
        raise ValidationError({field: f'La valeur doit être {minimum} et au maximum {maximum}.'})
    if number == 0:
        # Raw zero text still obeys the announced input precision.
        if not raw_decimal and number.as_tuple().exponent < -scale:
            raise ValidationError({field: f'Ce champ accepte au maximum {scale} décimales.'})
        return Decimal(0)
    exponent, digits = number.as_tuple().exponent, number.as_tuple().digits
    if len(digits) > 120:
        raise ValidationError({field: 'La valeur décimale est trop longue.'})
    if raw_decimal:
        # Database DecimalFields may add harmless zeros; never round significant
        # precision or call normalize() on a potentially extreme exponent.
        index = len(digits) - 1
        while exponent < -scale and index >= 0 and digits[index] == 0:
            exponent += 1
            index -= 1
    if exponent < -scale:
        raise ValidationError({field: f'Ce champ accepte au maximum {scale} décimales.'})
    return number


def _description(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_DESCRIPTION:
        raise ValidationError({field: f'Une désignation de 1 à {MAX_DESCRIPTION} caractères est obligatoire.'})
    if any(unicodedata.category(char) in ('Cc', 'Cs') and char not in '\n\r\t' for char in value):
        raise ValidationError({field: 'La désignation contient un caractère interdit.'})
    return value.strip()


def _plain(number, scale):
    text = format(number.quantize(Decimal(1).scaleb(-scale)), f'.{scale}f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def repair_quote_amounts(lines, *, vat_rate, currency='TND', discount_kind='none', discount_value='0'):
    """Canonical JSON-friendly decimal strings; no float or implicit VAT rate."""
    if not isinstance(currency, str) or currency.strip().upper() not in CURRENCY_PRECISION:
        raise ValidationError({'currency': 'Choisissez TND, EUR ou USD.'})
    if not isinstance(discount_kind, str) or discount_kind not in ('none', 'percent', 'fixed'):
        raise ValidationError({'discount_kind': 'Choisissez aucune remise, un pourcentage ou un montant HT.'})
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise ValidationError({'lines': f'Le devis doit contenir entre 1 et {MAX_LINES} lignes.'})
    currency = currency.strip().upper()
    precision = CURRENCY_PRECISION[currency]
    with localcontext(Context(prec=96, rounding=ROUND_HALF_UP)):
        quantum = Decimal(1).scaleb(-precision)
        maximum = Decimal('1000000000') - quantum
        rate = _number(vat_rate, 'vat_rate', scale=2, maximum=Decimal('100'))
        values, subtotal = [], Decimal(0)
        for index, line in enumerate(lines):
            field = f'lines.{index}'
            if not isinstance(line, dict) or set(line) != {'description', 'quantity', 'unit_ht'}:
                raise ValidationError({field: 'Chaque ligne doit contenir uniquement description, quantity et unit_ht.'})
            description = _description(line['description'], field + '.description')
            quantity = _number(line['quantity'], field + '.quantity', scale=3, maximum=MAX_QUANTITY, positive=True)
            price = _number(line['unit_ht'], field + '.unit_ht', scale=precision, maximum=maximum)
            total = (quantity * price).quantize(quantum, rounding=ROUND_HALF_UP)
            if total > maximum:
                raise ValidationError({field + '.total_ht': 'Le montant de cette ligne dépasse la limite du devis.'})
            subtotal += total
            if subtotal > maximum:
                raise ValidationError({'lines': 'Le sous-total HT du devis dépasse la limite autorisée.'})
            values.append({'description': description, 'quantity': _plain(quantity, 3),
                'unit_ht': format(price.quantize(quantum), f'.{precision}f'),
                'total_ht': format(total, f'.{precision}f')})
        discount = _number(discount_value, 'discount_value', scale=2 if discount_kind in ('none', 'percent') else precision,
                           maximum=Decimal('100') if discount_kind in ('none', 'percent') else maximum)
        if discount_kind == 'none' and discount != 0:
            raise ValidationError({'discount_value': 'Une absence de remise exige une valeur nulle.'})
        reduction = ((subtotal * discount / Decimal('100')).quantize(quantum, rounding=ROUND_HALF_UP)
                     if discount_kind == 'percent' else discount.quantize(quantum))
        if reduction > subtotal:
            raise ValidationError({'discount_value': 'La remise HT ne peut pas dépasser le sous-total HT.'})
        net = (subtotal - reduction).quantize(quantum)
        tax = (net * rate / Decimal('100')).quantize(quantum, rounding=ROUND_HALF_UP)
        total = (net + tax).quantize(quantum)
        monetary = lambda value: format(value, f'.{precision}f')
        return {'currency': currency, 'precision': precision, 'lines': values,
                'subtotal_ht': monetary(subtotal), 'discount_kind': discount_kind,
                'discount_value': monetary(discount.quantize(quantum)) if discount_kind == 'fixed' else _plain(discount, 2),
                'discount_ht': monetary(reduction), 'net_ht': monetary(net), 'vat_rate': _plain(rate, 2),
                'vat_amount': monetary(tax), 'total_ttc': monetary(total),
                'fully_discounted': bool(subtotal > 0 and net == 0 and reduction > 0)}
