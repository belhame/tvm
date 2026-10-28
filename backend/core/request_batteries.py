"""Battery references and explicitly confirmed SAV counts.

Catalogue quantities are nominal. No stock, warranty or existing intervention
is changed by a lookup, acceptance or a change to the current request quantity.
"""
from copy import deepcopy
from types import SimpleNamespace

from .battery_catalogue import resolve_battery_configuration
from .request_assignment import assignment_is_accepted
from .workflow_events import append_event


def _configuration_with_product(equipment, product):
    if product is None:
        return resolve_battery_configuration(equipment)
    # A transient view is sufficient: neither the catalogue FK nor the model is
    # linked/saved as a side effect of identifying a serial number.
    view = SimpleNamespace(brand=equipment.brand, model=equipment.model, catalogue_product=product)
    result = resolve_battery_configuration(view)
    if result['status'] == 'matched':
        result['identified_catalogue_product_id'] = getattr(product, 'pk', None)
        result['identified_catalogue_import_id'] = getattr(product, 'snapshot_id', None)
        result['warnings'].append('Référence catalogue retrouvée par la série sans modifier la fiche de l’équipement ; vérifiez le modèle réellement présent.')
    return result


def equipment_battery_configuration(equipment):
    result = resolve_battery_configuration(equipment)
    if result['status'] == 'unknown' and not equipment.catalogue_product_id:
        from .serial_lookup import find_serial_product
        product = find_serial_product(equipment.serial_number)
        return _configuration_with_product(equipment, product)
    return result


def _recorded_counts(record):
    return list(record.interventions.filter(battery_count__isnull=False)
                .order_by('-created_at', '-pk').values('id', 'reference', 'battery_count')[:50])


def battery_configuration_payload(record, *, equipment=None, recorded_counts=None, live_configuration=None):
    if not assignment_is_accepted(record) and not record.battery_reference:
        return None
    saved = record.battery_reference or {}
    equipment = equipment or record.equipment
    # Historical accepted requests get an advisory read only. A stale saved
    # reference remains explicitly stale until an operator records a new count.
    configuration = deepcopy(saved) if saved.get('status') == 'matched' else deepcopy(live_configuration) if live_configuration is not None else equipment_battery_configuration(equipment)
    configuration['is_saved_reference'] = saved.get('status') == 'matched'
    configuration['recorded_intervention_counts'] = [
        {'intervention_id': row['id'], 'reference': row['reference'], 'battery_count': row['battery_count']}
        for row in (_recorded_counts(record) if recorded_counts is None else recorded_counts)
    ]
    if saved.get('equipment_model') and (saved['equipment_model'] != equipment.model
            or saved.get('equipment_brand') != equipment.brand
            or saved.get('catalogue_product_id') != equipment.catalogue_product_id):
        configuration['warnings'].append('Le modèle ou sa référence catalogue a changé depuis cette proposition ; revérifiez la configuration et le nombre constaté.')
        configuration['status'] = 'stale'
    if configuration['recorded_intervention_counts']:
        configuration['warnings'].append('Les fiches d’intervention possèdent leurs propres nombres enregistrés. Ils restent conservés ; le nombre courant du dossier ne les réécrit pas.')
    return configuration


def serializer_battery_payload(serializer, record):
    """Two batched reads, plus at most two serial-reference reads per list."""
    if not assignment_is_accepted(record) and not record.battery_reference:
        return None
    from django.db.models import F, Window
    from django.db.models.functions import RowNumber
    from .models import Equipment, Intervention, ServiceRequest
    cache = serializer.context.setdefault('_battery_reference_payloads', {})
    if record.pk not in cache:
        parent = getattr(serializer, 'parent', None)
        rows = list(parent.instance) if parent is not None and getattr(parent, 'instance', None) is not None else [record]
        selected = {row.pk: row for row in rows if isinstance(row, ServiceRequest)
                    and row.pk not in cache and (assignment_is_accepted(row) or row.battery_reference)}
        selected.setdefault(record.pk, record)
        equipment = {unit.pk: unit for unit in Equipment.objects.filter(pk__in={row.equipment_id for row in selected.values()}).select_related('catalogue_product')}
        live = {identifier: resolve_battery_configuration(unit) for identifier, unit in equipment.items()}
        unresolved = {identifier: unit for identifier, unit in equipment.items()
                      if live[identifier]['status'] == 'unknown' and not unit.catalogue_product_id
                      and not all(row.battery_reference.get('status') == 'matched' for row in selected.values() if row.equipment_id == identifier)}
        if unresolved:
            from .serial_lookup import find_serial_products
            products = find_serial_products([unit.serial_number for unit in unresolved.values()])
            for identifier, unit in unresolved.items():
                live[identifier] = _configuration_with_product(unit, products.get(unit.serial_number))
        counts = {identifier: [] for identifier in selected}
        observed = Intervention.objects.filter(service_request_id__in=selected, battery_count__isnull=False).annotate(
            _battery_rank=Window(expression=RowNumber(), partition_by=[F('service_request_id')],
                                 order_by=[F('created_at').desc(), F('pk').desc()])
        ).filter(_battery_rank__lte=50).values('id', 'reference', 'battery_count', 'service_request_id').order_by('-created_at', '-pk')
        for row in observed:
            counts[row['service_request_id']].append(row)
        for identifier, row in selected.items():
            cache[identifier] = battery_configuration_payload(row, equipment=equipment.get(row.equipment_id), recorded_counts=counts[identifier], live_configuration=live[row.equipment_id])
    return deepcopy(cache[record.pk])


def initialize_request_batteries(record, *, actor):
    """Called under the existing request lock, only on a NEW acceptance."""
    if record.battery_reference or record.battery_count_source or record.battery_count is not None:
        return
    reference = equipment_battery_configuration(record.equipment)
    reference.update(equipment_model=record.equipment.model, equipment_brand=record.equipment.brand, catalogue_product_id=record.equipment.catalogue_product_id)
    record.battery_reference = reference
    # Zero internal cells is not zero installed cells when an external bank is
    # required. Existing observed intervention values also block nominal fill.
    if reference['status'] == 'matched' and reference['nominal_count'] > 0 and not _recorded_counts(record):
        record.battery_count = reference['nominal_count']
        record.battery_count_source = 'reference'
    record._operation_manual_event = True
    try:
        record.save(update_fields=['battery_reference', 'battery_count', 'battery_count_source', 'updated_at'])
    finally:
        record._operation_manual_event = False
    if reference['status'] == 'matched':
        append_event(equipment=record.equipment, service_request=record, actor=actor,
                     kind='battery_reference', source='battery_reference', is_internal=True,
                     summary=f"Configuration nominale proposée : {reference['reference']} · {reference['configuration']}. Quantité à confirmer sur l’équipement.")


def apply_request_battery_count(record, value, *, actor):
    """Set an operator supplied count; caller checks assignment and CAS first."""
    old = record.battery_count
    old_source = record.battery_count_source
    reference = equipment_battery_configuration(record.equipment)
    reference.update(equipment_model=record.equipment.model, equipment_brand=record.equipment.brand, catalogue_product_id=record.equipment.catalogue_product_id)
    changed = old != value or old_source != 'manual' or reference != record.battery_reference
    record.battery_reference = reference
    record.battery_count = value
    record.battery_count_source = 'manual'
    if not changed:
        return None
    before = 'non renseigné' if old is None else str(old)
    after = 'non renseigné' if value is None else str(value)
    return append_event(equipment=record.equipment, service_request=record, actor=actor,
                        kind='battery_count', source='followup', is_internal=True,
                        summary=f'Nombre de batteries du dossier confirmé : {before} → {after}. Le nombre des fiches d’intervention existantes reste conservé.')
