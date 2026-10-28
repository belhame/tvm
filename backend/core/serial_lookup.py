"""Read-only serial lookup against a pinned catalogue and recorded SAV data."""
import calendar
from copy import deepcopy
from datetime import date
import re
import unicodedata

from django.db.models import Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .catalogue_models import CatalogueImport, CatalogueProduct, CatalogueWarranty
from .catalogue_serializers import CatalogueImportSerializer, CatalogueProductSerializer, CatalogueWarrantySerializer
from .catalogue_service import collision_counts, usable_code
from .models import Contract, Equipment, Intervention, ServiceRequest, Warranty
from .serializers import ContractSerializer, EquipmentSerializer, InterventionSerializer, ServiceRequestSerializer, WarrantySerializer


PROFILES = ('Eaton', 'Pulsar', 'Powerware', 'NV DX')
WARRANTY_RULE = {'code': 'manufacture_monday_plus_6_calendar_months', 'start_offset_months': 6}


def generation_family(value):
    """Recognize only an explicit terminal generation, never strip a variant.

    The workbook can list a G2 product under a generic family warranty. A
    rack/power/battery qualifier must not be discarded to obtain that match.
    """
    value = re.sub(r'\(\s*launched\s*\d{4}\s*\)', '', str(value or ''), flags=re.I).strip()
    match = re.fullmatch(r'(.+?)\s+(?:G|Gen(?:eration)?\s*)([1-9][0-9]?)', value, flags=re.I)
    return (match[1].strip(), f'Gen {match[2]}') if match else (value, '')


def warranty_matches(product, references):
    """Return family warranty alternatives with exact generations preferred."""
    family = canonical_range(product.range_name) if usable_code(product.range_name) else ''
    base, generation = generation_family(product.range_name)
    base_key = canonical_range(base) if generation else ''
    exact, generic, manual = [], [], []
    for reference in references:
        key = canonical_range(reference.product_name)
        if family and key == family:
            exact.append((reference, 'exact_range'))
        elif base_key and key == base_key:
            generic.append((reference, 'generation_family'))
        elif family and _manual_family_match(reference.product_name, product.range_name):
            manual.append((reference, 'related_manual'))
    # A qualified warranty for this generation prevents a generic family
    # shortcut even when the qualification needs a human choice.
    return exact or manual or generic


def build_warranty_check(*, product, snapshot, computed, manufactured_on,
                         reference=None, recorded=False, recorded_model='', recorded_brand='',
                         identity_consistent=True, manufacture_date_basis=None, warnings=()):
    """Minimal read-only tracker projection, safe for the simple intake."""
    product = product or {}
    if not identity_consistent:
        product = {}
    reference = reference or {}
    family = product.get('range_name') or ''
    _, generation = generation_family(family)
    if not generation:
        for value in (product.get('version'), product.get('product_name')):
            _, generation = generation_family(value)
            if generation:
                break
    status = computed.get('coverage_status', 'unknown')
    status = 'no_coverage' if status == 'not_covered' else status
    scope = computed.get('scope') or reference.get('scope') or 'unspecified'
    evidence = 'recorded' if recorded else 'catalogue' if product else 'unknown'
    return {
        'status': status, 'checked_on': timezone.localdate().isoformat(), 'basis': evidence,
        'provisional': not recorded or status == 'unknown' or scope == 'unspecified',
        'manufacturer': recorded_brand or (product.get('structure') if product.get('structure') in ('Eaton', 'Pulsar', 'Powerware') else ''),
        'profile': product.get('structure') or '', 'family': family, 'generation': generation,
        'catalogue_identity_consistent': identity_consistent,
        'model_name': recorded_model or product.get('product_name') or '',
        'industrial_part_number': product.get('manufacturing_part_number') or '',
        'commercial_part_number': product.get('catalogue_number') or '',
        'manufactured_on': manufactured_on, 'starts_on': computed.get('starts_on'),
        'manufacture_date_basis': deepcopy(manufacture_date_basis or {}),
        'ends_on': computed.get('ends_on'), 'duration_months': computed.get('duration_months'),
        'scope': scope, 'rule': deepcopy(WARRANTY_RULE),
        'source': {
            'catalogue_import_id': snapshot.pk if snapshot else None,
            'revision': snapshot.metadata.get('revision', '') if snapshot else '',
            'product_sheet': product.get('source_sheet') or '', 'product_row': product.get('source_row'),
            'warranty_sheet': reference.get('source_sheet') or '', 'warranty_row': reference.get('source_row'),
            'warranty_match_type': reference.get('match_type') or '',
        },
        'warnings': list(dict.fromkeys(warnings)),
    }


def add_calendar_months(value, months):
    """Add calendar months, clamping the day at the destination month end."""
    total = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(total, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def canonical_range(value):
    # Only the dated launch annotation is ignored for automatic matching.
    value = re.sub(r'\(\s*launched\s*\d{4}\s*\)', '', str(value or ''), flags=re.I)
    return ''.join(c for c in unicodedata.normalize('NFKD', value).casefold() if c.isalnum() and not unicodedata.combining(c))


def _manual_family_match(label, family):
    """List qualified alternatives only; never turn a prefix into an auto match."""
    key = canonical_range(family)
    text = re.sub(r'\(\s*launched\s*\d{4}\s*\)', '', str(label or ''), flags=re.I)
    text = ''.join(c for c in unicodedata.normalize('NFKD', text).casefold() if not unicodedata.combining(c))
    prefix = ''
    for index, char in enumerate(text):
        if not char.isalnum():
            continue
        prefix += char
        if len(prefix) != len(key):
            continue
        if prefix != key:
            return False
        suffix = text[index + 1:]
        if not suffix:
            return False  # Exact matches have their own stricter path.
        if not suffix[0].isalnum():
            return True
        # A directly appended numeric power class is documented in labels such
        # as a family followed by 1-3 kVA. A letter suffix denotes another model.
        return bool(re.match(r'[0-9][0-9\s.,/\-–—]*(?:kva|kw)\b', suffix))
    return False


def _coverage(start, end, today):
    if start and today < start:
        return 'not_started'
    if end and today > end:
        return 'expired'
    return 'active' if end else 'unknown'


def _computed(manufactured_on, reference=None, *, needs_choice=False):
    result = {
        'status': 'needs_choice' if needs_choice else 'unavailable',
        'starts_on': None, 'ends_on': None, 'duration_months': None,
        'warranty_id': reference['id'] if reference else None,
        'coverage_status': 'unknown', 'rule': deepcopy(WARRANTY_RULE),
    }
    if not reference:
        return result
    duration = reference.get('duration_months')
    result['duration_months'] = duration
    # Zero months means no computed coverage, never one active calendar day.
    if duration == 0 and not isinstance(duration, bool):
        result.update(status='no_coverage', coverage_status='not_covered')
        return result
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        return result
    if not manufactured_on:
        result['status'] = 'manufacture_unknown'
        return result
    try:
        manufactured = date.fromisoformat(manufactured_on)
        start = add_calendar_months(manufactured, 6)
        end = add_calendar_months(start, duration)
    except (TypeError, ValueError, OverflowError):
        return result
    result.update(status='estimated', starts_on=start.isoformat(), ends_on=end.isoformat(), coverage_status=_coverage(start, end, timezone.localdate()))
    return result


def _identifier(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 9223372036854775807:
        raise ValidationError({name: 'Un identifiant entier positif est requis.'})
    return value


def _profile(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 32:
        raise ValidationError({'profile': 'Profil fabricant invalide.'})
    normalized = ''.join(c for c in value.casefold() if c.isalnum())
    for candidate in PROFILES:
        if ''.join(c for c in candidate.casefold() if c.isalnum()) == normalized:
            return candidate
    raise ValidationError({'profile': 'Choisissez Eaton, Pulsar, Powerware ou NV DX.'})


def _products(snapshot, profile, code):
    if not snapshot or not profile or not code or not usable_code(code):
        return CatalogueProduct.objects.none()
    return CatalogueProduct.objects.filter(snapshot=snapshot, structure=profile).annotate(code_key=Lower(Trim('product_code'))).filter(code_key=code.strip().lower())


def find_serial_product(serial_number, *, snapshot=None):
    """Bounded identification suggestion without SAV/history or any writes.

    Callers must still compare the recorded model to this catalogue reference;
    a code on its own must never qualify an unrelated model or battery variant.
    """
    if not isinstance(serial_number, str) or not serial_number.strip() or len(serial_number) > 120:
        return None
    return find_serial_products([serial_number], snapshot=snapshot)[serial_number]


def find_serial_products(serial_numbers, *, snapshot=None):
    """Batch version: one snapshot query and one product query, no history."""
    results = {value: None for value in serial_numbers if isinstance(value, str)}
    if snapshot is None:
        snapshot = CatalogueImport.objects.filter(is_active=True).first()
    if snapshot is None:
        return results
    from .serial_geometry import decode_profiles
    pairs, by_profile = {}, {}
    for serial in results:
        if not serial.strip() or len(serial) > 120:
            continue
        geometries = decode_profiles(serial, snapshot.metadata.get('year_tables', []))
        if len(geometries) != 1:
            continue
        geometry = geometries[0]
        code = geometry['segments'].get('product_code')
        if not code or not usable_code(code):
            continue
        code = code.strip().lower()
        profile = geometry['profile']
        pairs[serial] = (profile, code)
        by_profile.setdefault(profile, set()).add(code)
    if not pairs:
        return results
    conditions = Q()
    for profile, codes in by_profile.items():
        conditions |= Q(structure=profile, code_key__in=codes)
    query = CatalogueProduct.objects.filter(snapshot=snapshot).annotate(code_key=Lower(Trim('product_code'))).filter(conditions)
    products = {}
    for product in query:
        # Cache the already-loaded version so callers can inspect provenance.
        product.snapshot = snapshot
        products.setdefault((product.structure, product.product_code.strip().lower()), []).append(product)
    for serial, pair in pairs.items():
        candidates = products.get(pair, [])
        if len(candidates) == 1:
            results[serial] = candidates[0]
    return results


def _product_data(product, collisions):
    result = dict(CatalogueProductSerializer(product, context={'collision_counts': collisions}).data)
    short = product.catalogue_number.strip()
    result['short_model'] = short if usable_code(short) and len(short) <= 120 else None
    result['equipment_model_suggestion'] = result['short_model'] or (product.product_name if len(product.product_name) <= 120 else None)
    return result


def _recorded(equipment):
    empty_history = {'requests': [], 'interventions': [], 'request_count': 0, 'intervention_count': 0, 'truncated': False}
    if not equipment:
        return None, empty_history, [], []
    requests = ServiceRequest.objects.filter(equipment=equipment).select_related('equipment__client')
    interventions = Intervention.objects.filter(service_request__equipment=equipment).select_related('service_request__equipment__client', 'technician')
    request_count, intervention_count = requests.count(), interventions.count()
    history = {
        'requests': ServiceRequestSerializer(requests[:100], many=True).data,
        'interventions': InterventionSerializer(interventions[:100], many=True).data,
        'request_count': request_count, 'intervention_count': intervention_count,
        'truncated': request_count > 100 or intervention_count > 100,
    }
    today = timezone.localdate()
    recorded = []
    for warranty in Warranty.objects.filter(equipment=equipment).select_related('equipment__client'):
        item = dict(WarrantySerializer(warranty).data)
        item.update(scope=getattr(warranty, 'scope', 'unspecified'), coverage_status=_coverage(warranty.starts_on, warranty.ends_on, today))
        recorded.append(item)
    contracts = Contract.objects.filter(client=equipment.client, status='active', starts_on__lte=today, ends_on__gte=today).filter(Q(equipment=equipment) | Q(equipment__isnull=True)).select_related('client', 'equipment')
    return dict(EquipmentSerializer(equipment).data), history, recorded, ContractSerializer(contracts, many=True).data


def lookup_serial(serial_number, *, profile=None, product_id=None, catalogue_import_id=None, warranty_reference_id=None):
    """Return suggestions and recorded evidence without creating or changing rows."""
    if not isinstance(serial_number, str) or not serial_number.strip() or len(serial_number) > 120:
        raise ValidationError({'serial_number': 'Une série texte non vide de 120 caractères maximum est requise.'})
    try:
        serial_number.encode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise ValidationError({'serial_number': 'Le numéro contient un caractère Unicode invalide.'}) from exc
    if '\x00' in serial_number:
        raise ValidationError({'serial_number': 'Le numéro contient un caractère nul non autorisé.'})
    serial = serial_number.strip()
    normalized = serial.upper() if serial.isascii() else serial
    profile = _profile(profile)
    product_id = _identifier(product_id, 'product_id')
    catalogue_import_id = _identifier(catalogue_import_id, 'catalogue_import_id')
    warranty_reference_id = _identifier(warranty_reference_id, 'warranty_reference_id')
    equipment = Equipment.objects.select_related('client', 'catalogue_product__snapshot').filter(serial_number__iexact=serial).first()
    if catalogue_import_id:
        snapshot = CatalogueImport.objects.select_related('imported_by').filter(pk=catalogue_import_id).first()
        if snapshot is None:
            raise ValidationError({'catalogue_import_id': 'Cette version du catalogue n’existe pas.'})
    elif equipment and equipment.catalogue_product_id and product_id is None:
        snapshot = equipment.catalogue_product.snapshot
    else:
        snapshot = CatalogueImport.objects.select_related('imported_by').filter(is_active=True).first()
    if not snapshot and (product_id or warranty_reference_id):
        raise ValidationError({'catalogue_import_id': 'Aucun catalogue disponible pour vérifier ce choix.'})

    from .serial_geometry import decode_profiles
    geometries = decode_profiles(normalized, snapshot.metadata.get('year_tables', []) if snapshot else [], profile=profile)
    warnings = []
    chosen = None
    if product_id:
        chosen = CatalogueProduct.objects.filter(pk=product_id, snapshot=snapshot).first()
        if chosen is None:
            raise ValidationError({'product_id': 'Le produit n’appartient pas à cette version du catalogue.'})
        if profile and chosen.structure != profile:
            raise ValidationError({'product_id': 'Le produit ne correspond pas au profil choisi.'})
        geometries = [item for item in geometries if item['profile'] == chosen.structure]
        if not geometries:
            geometries = decode_profiles(normalized, snapshot.metadata.get('year_tables', []), profile=chosen.structure)
        profile = chosen.structure
    elif equipment and equipment.catalogue_product_id and equipment.catalogue_product.snapshot_id == (snapshot.pk if snapshot else None):
        chosen = equipment.catalogue_product
        geometries = [item for item in geometries if item['profile'] == chosen.structure]
        profile = chosen.structure

    # A catalogue code can accidentally equal another profile's year/week.
    # Preserve every plausible profile until the operator makes a choice.
    profile_options = list(dict.fromkeys(item['profile'] for item in geometries))
    geometry = geometries[0] if len(geometries) == 1 else None
    candidates = []
    if geometry:
        candidates = list(_products(snapshot, geometry['profile'], geometry['segments'].get('product_code')))
        if chosen and geometry['segments'].get('product_code') and chosen.pk not in {item.pk for item in candidates}:
            if equipment and equipment.catalogue_product_id == chosen.pk:
                warnings.append('La référence enregistrée diffère du code décodé ; les données réelles sont conservées et cette divergence doit être vérifiée.')
            else:
                raise ValidationError({'product_id': 'Le produit choisi ne correspond pas au code de cette série.'})
    if chosen and not candidates:
        candidates = [chosen]
        warnings.append('Le produit est un choix explicite ou enregistré ; la série seule ne l’identifie pas automatiquement.')
    if chosen is None and len(candidates) == 1:
        chosen = candidates[0]
    if not snapshot:
        warnings.append('Aucun catalogue n’est chargé ; aucun modèle, année ou durée de garantie n’est inventé.')
    if geometry:
        warnings.extend(geometry['warnings'])
    elif geometries:
        warnings.append('Plusieurs profils sont compatibles. Choisissez explicitement le profil avant toute datation ou identification.')
    else:
        warnings.append('Cette série ne correspond pas à une géométrie documentée disponible. Une saisie manuelle justifiée reste possible.')
    if len(candidates) > 1 and chosen is None:
        warnings.append('Ce code correspond à plusieurs produits ; choisissez la référence exacte, aucun premier résultat n’est retenu.')
    if geometry and not candidates:
        warnings.append('Le code de série n’identifie aucun produit unique dans ce catalogue. Aucun modèle n’est inventé.')

    collisions = collision_counts(snapshot.products.values_list('structure', 'product_code')) if snapshot else {}
    selected_product = _product_data(chosen, collisions) if chosen else None
    candidate_data = [_product_data(item, collisions) for item in candidates]
    manufactured_on = geometry['manufactured_on'] if geometry else None
    catalogue_manufactured_on = manufactured_on
    basis = deepcopy(geometry['manufacture_date_basis']) if geometry else {'type': None, 'reconstructed': False, 'source': '', 'precision': 'unknown', 'blocked_reason': 'Profil ou date non déterminé.'}
    existing, history, recorded, contracts = _recorded(equipment)
    if equipment:
        warnings.append('Équipement existant : le modèle, les dates et garanties enregistrés restent prioritaires ; cette recherche ne les modifie pas.')
        if equipment.manufactured_on:
            manufactured_on = equipment.manufactured_on.isoformat()
            basis = {'type': 'recorded', 'reconstructed': False, 'source': 'Date enregistrée sur l’équipement.', 'precision': 'day', 'blocked_reason': None}
    if manufactured_on and date.fromisoformat(manufactured_on) > timezone.localdate():
        warnings.append('La fabrication obtenue est future : vérifiez le code année et un éventuel cycle non documenté. Aucune couverture ne sera active avant son début.')

    options = []
    if chosen:
        for reference, match_type in warranty_matches(chosen, CatalogueWarranty.objects.filter(snapshot=snapshot)):
            item = dict(CatalogueWarrantySerializer(reference).data)
            item['match_type'] = match_type
            item['computed_warranty'] = _computed(manufactured_on, item)
            options.append(item)
    default_id = options[0]['id'] if len(options) == 1 and (
        options[0]['match_type'] == 'exact_range'
        or options[0]['match_type'] == 'generation_family' and options[0]['scope'] in ('unspecified', 'electronics_and_batteries')
    ) else None
    selected_warranty = None
    if warranty_reference_id:
        selected_warranty = next((item for item in options if item['id'] == warranty_reference_id), None)
        if selected_warranty is None:
            raise ValidationError({'warranty_reference_id': 'La référence de garantie ne correspond pas à la gamme et à la version du produit choisi.'})
    elif default_id:
        selected_warranty = options[0]
    if len(options) > 1 and selected_warranty is None:
        warnings.append('Plusieurs garanties ou composants sont possibles ; choisissez la portée exacte, sans retenir automatiquement la durée la plus longue.')
    if selected_warranty and selected_warranty['match_type'] == 'related_manual':
        warnings.append('Cette garantie qualifiée exige une validation explicite de sa portée ; le rapprochement n’est pas automatique.')
    if selected_warranty and selected_warranty['match_type'] == 'generation_family':
        warnings.append('Le catalogue ne donne pas de garantie distincte pour cette génération : la durée de la gamme générale est proposée à titre indicatif, avec une couverture à confirmer.')
    if selected_warranty and selected_warranty['duration_months'] == 0:
        warnings.append('La référence indique zéro mois : aucune couverture calculée ni garantie active n’est créée.')
    computed = deepcopy(selected_warranty['computed_warranty']) if selected_warranty else _computed(manufactured_on, needs_choice=bool(options))
    catalogue_computed = _computed(catalogue_manufactured_on, selected_warranty, needs_choice=bool(options) and selected_warranty is None)
    identity_consistent = product_matches_equipment(chosen, equipment)
    if equipment and chosen and not identity_consistent:
        warnings.append('La référence décodée dans le catalogue diffère du modèle enregistré. Vérifiez l’étiquette ; les références et la garantie du catalogue ne sont pas attribuées automatiquement au matériel réel.')
        if not recorded and not equipment.warranty_until:
            computed = _computed(None)
    if recorded or (equipment and equipment.warranty_until):
        computed = _computed(None)
        computed['status'] = 'recorded_priority'
        # Older TVM guarantees are recorded for the equipment without a
        # component scope. Their dates remain usable for the same general
        # lookup, while a battery guarantee cannot cover electronics.
        wanted_scope = selected_warranty.get('scope') if selected_warranty else 'unspecified'
        matching_recorded = [
            item for item in recorded
            if wanted_scope in ('unspecified', 'electronics', 'batteries', 'electronics_and_batteries')
            and (item['scope'] == wanted_scope or item['scope'] == 'electronics_and_batteries' and wanted_scope in ('unspecified', 'electronics', 'batteries'))
        ]
        active_periods = [item for item in matching_recorded if item['coverage_status'] == 'active']
        actual = active_periods[0] if len(active_periods) == 1 else matching_recorded[0] if len(matching_recorded) == 1 else None
        if actual is not None:
            computed.update(starts_on=actual['starts_on'], ends_on=actual['ends_on'], coverage_status=actual['coverage_status'], scope=actual['scope'])
        elif not recorded and wanted_scope == 'unspecified':
            computed.update(ends_on=equipment.warranty_until.isoformat(), coverage_status=_coverage(None, equipment.warranty_until, timezone.localdate()), scope='unspecified')
            warnings.append('La fin de garantie globale enregistrée est affichée ; elle ne précise pas une couverture par composant.')
        elif not recorded:
            warnings.append('La fin de garantie globale enregistrée reste visible sur l’équipement ; sa portée n’est pas attribuée automatiquement à un composant.')
        else:
            warnings.append('Aucune période enregistrée unique de portée compatible n’est déterminée ; consultez les garanties réelles séparément sans transférer leurs dates à un autre composant.')
    status = 'matched' if geometry else ('ambiguous' if geometries else 'not_applicable')
    if len(candidates) > 1 and chosen is None:
        status = 'ambiguous'
    if not snapshot:
        status = 'catalogue_unavailable'
    warranty_check = build_warranty_check(
        product=selected_product, snapshot=snapshot, computed=computed,
        manufactured_on=manufactured_on if identity_consistent or equipment and equipment.manufactured_on else None,
        reference=selected_warranty if identity_consistent else None, recorded=computed['status'] == 'recorded_priority',
        recorded_model=equipment.model if equipment else '', recorded_brand=equipment.brand if equipment else '',
        identity_consistent=identity_consistent,
        manufacture_date_basis=basis if identity_consistent or equipment and equipment.manufactured_on else {}, warnings=warnings,
    )
    return {
        'serial_number': serial, 'normalized_serial_number': normalized,
        'catalogue_import_id': snapshot.pk if snapshot else None,
        'catalogue_import': dict(CatalogueImportSerializer(snapshot).data) if snapshot else None,
        'existing_equipment': existing, 'history': history,
        'product_candidates': candidate_data, 'selected_product': selected_product,
        'selected_product_id': chosen.pk if chosen else None,
        'detection': {
            'status': status, 'profile': geometry['profile'] if geometry else profile,
            'profile_options': profile_options, 'format': geometry['format'] if geometry else None,
            'segments': geometry['segments'] if geometry else {},
            'year': geometry['year'] if geometry else None, 'week': geometry['week'] if geometry else None,
            'requires_product_choice': chosen is None,
            'requires_profile_choice': len(geometries) > 1,
        },
        'manufactured_on': manufactured_on, 'manufacture_date_basis': basis,
        'warranty_options': options, 'selected_warranty': selected_warranty,
        'default_warranty_id': default_id, 'computed_warranty': computed,
        'catalogue_manufactured_on': catalogue_manufactured_on,
        'catalogue_computed_warranty': catalogue_computed, 'warranty_check': warranty_check,
        'recorded_warranties': recorded, 'active_contracts': list(contracts),
        'warnings': list(dict.fromkeys(warnings)),
    }


def product_matches_equipment(product, equipment, suggestion=None):
    if equipment is None:
        return True
    if product is None:
        return False
    if equipment.catalogue_product_id == product.pk:
        return True
    names = {product.product_name.strip().casefold(), product.catalogue_number.strip().casefold()}
    if suggestion:
        names.add(suggestion.strip().casefold())
    return equipment.model.strip().casefold() in names
