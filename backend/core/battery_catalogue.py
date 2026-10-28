"""Nominal battery data supplied by TVM, never a physical inspection.

Only explicit, whitelisted model references match. Generation, cabinet and
phase distinctions are retained; external battery cabinets are separate items.
The first anonymous VA-only table supplied by TVM has no family and is therefore
not usable for automatic identification.
"""
from copy import deepcopy
import re
import unicodedata


SOURCE = 'Tableau de configurations batteries fourni par TVM — 28/10/2026'
REFERENCE_VERSION = 'tvm-battery-table-20261028-v1'


def _key(value):
    text = unicodedata.normalize('NFKD', str(value or '')).upper()
    text = re.sub(r'^\s*EATON\s*', '', text)
    return ''.join(char for char in text if char.isascii() and char.isalnum())


def _spec(reference, count, ah, suppliers, aliases, *, volts='12', configuration=None,
          family='', generation='', external=False, required=()):
    return dict(reference=reference, nominal_count=count, voltage_v=volts if count else None,
                capacity_ah=str(ah) if count else None, suppliers=suppliers.split(' / '),
                configuration=configuration or (f'{count} × {volts} V / {ah} Ah' if count else 'Aucune batterie interne ; armoire EBM requise'),
                aliases=tuple(_key(alias) for alias in aliases), family=family,
                generation=generation, external_battery_required=not count,
                equipment_kind='external_battery_cabinet' if external else 'ups', required=required)


SPECS = []


def _add(*args, **kwargs):
    SPECS.append(_spec(*args, **kwargs))


for rating, count, ah in [(650, 1, 7), (850, 1, 9), (1200, 2, 7), (1600, 2, 9)]:
    for outlet in ('FR', 'DIN', 'IEC'):
        # The supplied IEC 850 row explicitly differs from FR/DIN.
        actual_count = 2 if rating == 850 and outlet == 'IEC' else count
        reference = f'ELP{rating}{outlet}'
        _add(reference, actual_count, ah, 'BB / Leoch / CSB', [reference], family='ELLIPSEPRO')

for rating, count, ah, suppliers in [(550, 1, 5, 'RITAR / Leoch'), (700, 1, 7, 'BB / Leoch'),
                                    (1000, 2, 7, 'BB / Leoch'), (1500, 2, 9, 'BB / CSB')]:
    _add(f'5S{rating}i', count, ah, suppliers, [f'5S{rating}i'], family='5S')

for rating, count, ah in [(500, 1, 9), (750, 2, 7), (1000, 2, 9), (1500, 3, 9)]:
    _add(f'5SC{rating}i', count, ah, 'BB / Yuasa', [f'5SC{rating}', f'5SC{rating}i'], family='5SC')
for rating, suffix, count, ah, suppliers in [(1000, 'IR', 2, 9, 'Yuasa / BB / Leoch'),
        (1500, 'IR', 3, 9, 'Yuasa / BB / Leoch'), (2200, 'IRT', 4, 9, 'Yuasa / BB'), (3000, 'IRT', 6, 9, 'Yuasa / BB')]:
    _add(f'5SC{rating}{suffix}', count, ah, suppliers, [f'5SC{rating}{suffix}'], family='5SC')

for rating, count, ah in [(550, 1, '4,5'), (700, 1, 7), (900, 1, 9), (1200, 2, 7), (1600, 2, 7), (2200, 2, 9)]:
    aliases = [f'5E{rating}G2', f'5E{rating}IG2', f'5E{rating}FG2', f'5E{rating}FRG2', f'5E{rating}UIG2', f'5E{rating}UDG2']
    _add(f'5E {rating} G2', count, ah, 'Leoch', aliases, family='5E', generation='G2')

for rating, count, ah in [(6000, 15, 9), (10000, 20, 9), (15000, 40, 7), (20000, 40, 9)]:
    _add(f'9E {rating} tour', count, ah, 'Yuasa', [f'9E{rating}', f'9E{rating}i', f'9E{rating // 1000}Ki'], family='9E')
for voltage, count, expression in [(180, 30, '2 × 15'), (240, 40, '2 × 20'), (480, 40, '40')]:
    _add(f'9E EBM {voltage}V', count, 9, 'Yuasa', [f'9E EBM {voltage}V'], family='9E', external=True,
         configuration=f'{expression} × 12 V / 9 Ah')

for rating, ah in [(1000, 7), (1500, 9), (2200, 7), (3000, 9)]:
    count = 4 if rating < 2000 else 6
    _add(f'9PX {rating}RT', count, ah, 'Leoch' if rating < 2000 else 'Leoch / Yuasa' if rating == 2200 else 'Leoch / CSB',
         [f'9PX{rating}RT', f'9PX{rating}IRT', f'9PX{rating}IRT2U'], family='9PX', generation='G1')
for voltage, count, expression, suppliers in [(48, 8, '2 × 4', 'Leoch'), (72, 12, '2 × 6', 'Leoch / CSB')]:
    _add(f'9PX EBM {voltage}V', count, 9, suppliers, [f'9PX EBM {voltage}V'], family='9PX', external=True,
         configuration=f'{expression} × 12 V / 9 Ah')

for rating, count, ah in [(700, 2, 9), (1000, 3, 9), (1500, 4, 9), (2000, 8, 7), (3000, 8, 9), (5000, 20, 7), (6000, 20, 7)]:
    _add(f'9SX {rating} tour', count, ah, 'Leoch', [f'9SX{rating}', f'9SX{rating}i'], family='9SX', generation='G1')
for rating, count, ah in [(1000, 3, 9), (1500, 4, 9), (2000, 6, 7), (3000, 6, 9)]:
    _add(f'9SX {rating}R', count, ah, 'Leoch', [f'9SX{rating}R', f'9SX{rating}IR'], family='9SX', generation='G1')
for label, count, ah, expression in [('36T', 6, 9, '2 × 3'), ('48T', 8, 9, '2 × 4'), ('96T', 16, 9, '2 × 8'),
        ('240T', 40, 7, '2 × 20'), ('36R', 6, 9, '2 × 3'), ('48R', 8, 9, '2 × 4'), ('72R', 12, 9, '2 × 6')]:
    _add(f'9SX EBM {label}', count, ah, 'Leoch', [f'9SX EBM {label}'], family='9SX', external=True,
         configuration=f'{expression} × 12 V / {ah} Ah')

for rating, count, ah in [(1000, 2, 9), (2000, 6, 7), (3000, 6, 9)]:
    _add(f'9E {rating} tour', count, ah, 'Leoch', [f'9E{rating}', f'9E{rating}i'], family='9E')
for rating, count, ah in [(1000, 3, 9), (2000, 6, 7), (3000, 6, 9)]:
    _add(f'9E {rating}R', count, ah, 'BAACE', [f'9E{rating}R', f'9E{rating}IR'], family='9E')
# Generic "EBM" entries do not identify a cabinet: keep only qualified aliases.
_add('9E 1-3kVA EBM tour', 12, 9, 'Leoch', ['9E 1-3kVA EBM tour'], family='9E', external=True,
     configuration='2 × 6 × 12 V / 9 Ah')
_add('9E 1-3kVA EBM rack', 12, 9, 'BAACE', ['9E 1-3kVA EBM rack'], family='9E', external=True,
     configuration='2 × 6 × 12 V / 9 Ah')

for rating, ah in [(450, '4,5'), (550, 5), (700, 7), (850, 9)]:
    aliases = [f'3S{rating}G2', f'3S{rating}FG2', f'3S{rating}IG2', f'3S {rating} 2019']
    _add(f'3S {rating} (2019)', 1, ah, 'Leoch', aliases, family='3S', generation='2019')

for rating, count, ah, units in [(1000, 4, 7, '2U'), (1500, 4, 9, '2U'), (2200, 6, 7, '2U'),
        (2200, 6, 7, '3U'), (3000, 6, 9, '2U'), (3000, 6, 9, '3U')]:
    _add(f'5PX {rating}VA RT {units} G2', count, ah, 'Leoch',
         [f'5PX{rating}RT{units}G2', f'5PX{rating}IRT{units}G2', f'5PX{rating}VA RT {units} G2'], family='5PX', generation='G2')
for voltage, count, expression in [(48, 8, '2 × 4'), (72, 12, '2 × 6')]:
    _add(f'5PX G2 EBM {voltage}V', count, 9, 'Leoch', [f'5PX G2 EBM {voltage}V', f'5PX EBM {voltage}V G2'], family='5PX', generation='G2', external=True,
         configuration=f'{expression} × 12 V / 9 Ah')

for rating, count, ah in [(650, 1, 9), (850, 2, 7), (1150, 2, 9), (1500, 3, 9)]:
    _add(f'5P {rating}VA tour G2', count, ah, 'BAACE',
         [f'5P{rating}IG2', f'5P{rating}VA Tower G2', f'5P{rating}VA Tour G2'], family='5P', generation='G2')
for rating, count, ah in [(650, 2, 9), (850, 4, 7), (1150, 4, 9), (1500, 6, 9)]:
    _add(f'5P {rating}VA 1U G2', count, ah, 'Leoch',
         [f'5P{rating}IRG2', f'5P{rating}VA1UG2', f'5P{rating}1UG2'], volts='6', family='5P', generation='G2')

for family, top_ah in [('9SX', 7), ('9PX', 9)]:
    for rating, count, ah in [(5, 15, 5), (6, 15, 5), (8, 20, top_ah), (11, 20, top_ah)]:
        _add(f'{family} {rating}kVA 1:1 G2', count, ah, 'BAACE',
             [f'{family}{rating}kVA1:1G2', f'{family}{rating}kVA G2 1:1'], family=family, generation='G2', required=('phase11',))
    _add(f'{family} G2 EBM 180V', 30, 5, 'BAACE', [f'{family} G2 EBM 180V', f'{family} EBM 180V G2'],
         family=family, generation='G2', external=True, configuration='2 × 15 × 12 V / 5 Ah')
    _add(f'{family} G2 EBM 240V', 20, top_ah, 'BAACE', [f'{family} G2 EBM 240V', f'{family} EBM 240V G2'],
         family=family, generation='G2', external=True)

for rating in (6, 8, 11):
    _add(f'9PX {rating}kVA 3:1', 0, None, 'Not Applicable', [f'9PX{rating}kVA3:1'], family='9PX', generation='G1', required=('phase31',))
_add('9E 6kVA rack', 15, 5, 'BAACE', ['9E6kVA Rack', '9E6000IR', '9E6KIR'], family='9E')
_add('9E 11kVA rack', 0, None, 'BAACE', ['9E11kVA Rack', '9E11000IR', '9E11KIR'], family='9E')
_add('9E rack EBM 180V', 30, 5, 'BAACE', ['9E Rack EBM 180V'], family='9E', external=True, configuration='2 × 15 × 12 V / 5 Ah')
_add('9E rack EBM 240V', 20, 7, 'BAACE', ['9E Rack EBM 240V'], family='9E', external=True)


def _generation(text, *, allow_2019=False):
    if re.search(r'\b(?:G(?:EN(?:ERATION)?)?\s*2|GEN\s*2)\b|G2\b', text, re.I):
        return 'G2'
    if re.search(r'\b(?:G(?:EN(?:ERATION)?)?\s*1|GEN\s*1)\b|G1\b', text, re.I):
        return 'G1'
    if allow_2019 and re.search(r'\b2019\b', text):
        return '2019'
    return ''


def _empty(status='unknown', warning=None):
    return dict(status=status, reference=None, configuration=None, nominal_count=None,
                voltage_v=None, capacity_ah=None, suppliers=[], source=SOURCE,
                reference_version=REFERENCE_VERSION, external_battery_required=False,
                equipment_kind=None, warnings=[warning or 'Modèle ou variante non identifié avec certitude dans le tableau ; renseignez le nombre constaté.'])


def resolve_battery_configuration(equipment):
    """Read-only exact reference resolution; never match a wattage alone."""
    if not equipment or _key(getattr(equipment, 'brand', 'Eaton')) not in ('', 'EATON'):
        # _key removes the Eaton prefix, hence the empty result for Eaton.
        return _empty()
    model = str(getattr(equipment, 'model', '') or '')
    product = getattr(equipment, 'catalogue_product', None)
    product_text = ' '.join(str(getattr(product, field, '') or '') for field in ('product_name', 'range_name', 'version')) if product else ''
    model_key = _key(model)
    # In the supplied table, 2019 qualifies only the 3S generation. A launch
    # annotation on another family must never turn its old model into G2.
    allow_2019 = bool(re.match(r'^3S[0-9]', model_key))
    model_generation = _generation(model, allow_2019=allow_2019)
    product_keys = set()
    if product:
        product_keys.update((_key(product.catalogue_number), _key(product.product_name)))
    product_generation = _generation(product_text, allow_2019=allow_2019)
    if model_generation and product_generation and model_generation != product_generation and {model_generation, product_generation} != {'G2', '2019'}:
        return _empty('ambiguous', 'La génération du modèle enregistré diffère du catalogue lié ; vérifiez cette référence avant de choisir les batteries.')
    # A stale catalogue FK must not qualify an unrelated edited model. Its
    # literal generation may qualify only that same commercial reference.
    same_commercial_reference = bool(product and model_key and model_key in product_keys)
    generation = model_generation or (product_generation if same_commercial_reference else '')
    direct_keys = {model_key}
    # Only a literal G2/2019 from the linked catalogue can qualify an otherwise
    # generation-free commercial reference. A numeric version "2" is not G2.
    if generation:
        for key in tuple(direct_keys):
            if not key.endswith(('G1', 'G2', '2019')):
                direct_keys.add(key + ('G2' if generation == '2019' else generation))
    text = model + (' ' + product_text if same_commercial_reference else '')
    phase11 = bool(re.search(r'1\s*[:/]\s*1', text))
    phase31 = bool(re.search(r'3\s*[:/]\s*1', text))
    candidates = []
    for specification in SPECS:
        if not direct_keys.intersection(specification['aliases']):
            continue
        spec_generation = specification['generation']
        if generation == 'G2' and not spec_generation:
            continue
        if generation and spec_generation and generation != spec_generation and {generation, spec_generation} != {'G2', '2019'}:
            continue
        if ('phase11' in specification['required'] and not phase11) or ('phase31' in specification['required'] and not phase31):
            continue
        candidates.append(specification)
    identities = {candidate['reference'] for candidate in candidates}
    # If both the current model and the linked product independently identify
    # incompatible configurations, return ambiguity rather than choosing one.
    linked_keys = set(product_keys)
    if product_generation:
        linked_keys.update(key + ('G2' if product_generation == '2019' else product_generation)
                           for key in product_keys if not key.endswith(('G1', 'G2', '2019')))
    linked_identities = {row['reference'] for row in SPECS if linked_keys.intersection(row['aliases'])}
    if identities and linked_identities and not identities.intersection(linked_identities):
        return _empty('ambiguous', 'Le modèle enregistré et le produit catalogue lié indiquent des configurations différentes ; vérifiez la référence réelle.')
    if len(identities) != 1:
        return _empty('ambiguous' if identities else 'unknown', 'Plusieurs configurations sont possibles ; vérifiez la variante avant de renseigner le nombre constaté.' if identities else None)
    chosen = deepcopy(candidates[0])
    for field in ('aliases', 'required', 'family', 'generation'):
        chosen.pop(field, None)
    chosen.update(status='matched', source=SOURCE, reference_version=REFERENCE_VERSION,
                  warnings=['Configuration nominale fournie par TVM, à vérifier sur l’équipement ; elle ne confirme pas la présence ni l’état réel des batteries.'])
    if chosen['equipment_kind'] == 'external_battery_cabinet':
        chosen['warnings'].append('Armoire EBM séparée : ce nombre ne s’ajoute pas automatiquement aux batteries internes de l’onduleur.')
    if chosen['external_battery_required']:
        chosen['warnings'].append('Le module de puissance ne contient aucune batterie interne ; identifier séparément l’armoire EBM 240V réellement installée.')
    return chosen
