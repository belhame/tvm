"""Record future changes only. Migration 0005 marks existing rows honestly."""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Contract, DeliveryNote, Equipment, Intervention, ServiceRequest, StockMovement, Warranty
from .workflow_events import append_event


TRACKED_MODELS = (Equipment, ServiceRequest, Intervention, Contract, Warranty, DeliveryNote)
IGNORED = {'id', 'created_at', 'updated_at', 'completed_at', 'intake_data', 'intake_key'}
PRIVATE = {'internal_notes'}


@receiver(pre_save, dispatch_uid='workflow_previous_values')
def remember_previous(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw or sender not in TRACKED_MODELS:
        return
    instance._operation_previous = sender.objects.filter(pk=instance.pk).values().first() if instance.pk else None
    if sender is ServiceRequest:
        previous = instance._operation_previous or {}
        persisted_status = instance.status if update_fields is None or 'status' in update_fields else previous.get('status', instance.status)
        if persisted_status == 'closed':
            if previous.get('status') != 'closed':
                from django.utils import timezone
                instance.closed_at = timezone.now()
            elif previous.get('closed_at') is not None:
                instance.closed_at = previous['closed_at']
        else:
            instance.closed_at = None


@receiver(post_save, dispatch_uid='workflow_record_future_change')
def record_change(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw or sender not in TRACKED_MODELS:
        return
    if getattr(instance, '_operation_manual_event', False):
        return
    old = getattr(instance, '_operation_previous', None) or {}
    changed = {field.name for field in instance._meta.concrete_fields
               if field.name not in IGNORED and (update_fields is None or field.name in update_fields or field.attname in update_fields)
               and (created or old.get(field.attname) != getattr(instance, field.attname))}
    if not changed:
        return
    service_request = instance if sender is ServiceRequest else getattr(instance, 'service_request', None)
    intervention = instance if sender is Intervention else getattr(instance, 'intervention', None)
    if intervention and not service_request:
        service_request = intervention.service_request
    equipment = instance if sender is Equipment else (service_request.equipment if service_request else getattr(instance, 'equipment', None))
    if equipment is None:
        # Client-wide contracts have no individual equipment operation.
        return
    related = getattr(instance, 'replacement_equipment', None) if sender is Intervention else None
    common = dict(equipment=equipment, service_request=service_request, intervention=intervention, related_equipment=related)
    public_changes = changed - PRIVATE
    if public_changes:
        label = {'Equipment': 'Onduleur', 'ServiceRequest': 'Demande SAV', 'Intervention': 'Intervention',
                 'Contract': 'Contrat', 'Warranty': 'Garantie', 'DeliveryNote': 'Bon de livraison'}[sender.__name__]
        if sender is Equipment:
            kind = 'created' if created else 'updated'
        elif sender is ServiceRequest:
            kind = 'created' if created else ('status_changed' if 'status' in changed else 'updated')
        else:
            prefix = {'Intervention': 'intervention', 'Contract': 'contract', 'Warranty': 'warranty', 'DeliveryNote': 'delivery'}[sender.__name__]
            kind = f'{prefix}_{"created" if created else "updated"}'
        observation = ''
        if sender is Intervention:
            fragments = []
            for field, title in [('diagnosis', 'Diagnostic'), ('work_done', 'Travaux réalisés'), ('recommendations', 'Recommandations'), ('summary', 'Synthèse'), ('conclusion_notes', 'Conclusion')]:
                if field in public_changes and getattr(instance, field, ''):
                    fragments.append(f'{title} : {getattr(instance, field)}')
            observation = '\n\n'.join(fragments)
        summary = f'{label} {"créé" if created else "mis à jour"}.'
        details = []
        if sender is Equipment:
            if created:
                details.append(f'{instance.brand} {instance.model} — S/N {instance.serial_number}.')
            else:
                for field, title in [('serial_number', 'Numéro de série'), ('model', 'Modèle'), ('brand', 'Marque'), ('location', 'Emplacement')]:
                    if field in public_changes:
                        details.append(f'{title} : {old.get(field, "") or "non renseigné"} → {getattr(instance, field) or "non renseigné"}.')
        if 'status' in public_changes:
            choices = dict(instance._meta.get_field('status').choices)
            previous = choices.get(old.get('status'), old.get('status', ''))
            current = choices.get(instance.status, instance.status)
            details.append(f'État : {previous + " → " if previous else ""}{current}.')
        if sender is Intervention:
            from .intervention_workflow import CHECKLISTS, CONCLUSIONS, INTERVENTION_KINDS
            if 'kind' in public_changes:
                details.append(f'Fiche : {INTERVENTION_KINDS.get(instance.kind, instance.kind)}.')
            if 'replacement_equipment' in public_changes and (instance.replacement_equipment_id or old.get('replacement_equipment_id')):
                old_replacement = Equipment.objects.filter(pk=old.get('replacement_equipment_id')).values_list('serial_number', flat=True).first()
                details.append(f'Échange : matériel d’origine S/N {equipment.serial_number} ; remplacement {old_replacement or "non renseigné"} → {related.serial_number if related else "non renseigné"}.')
            for field, title in [('scheduled_at', 'Planification'), ('performed_on', 'Réalisation')]:
                if field in public_changes and (getattr(instance, field) or old.get(field)):
                    details.append(f'{title} : {old.get(field) or "non renseignée"} → {getattr(instance, field) or "non renseignée"}.')
            if 'technician' in public_changes:
                name = (instance.technician.get_full_name() or instance.technician.username) if instance.technician else 'Non affecté'
                details.append(f'Technicien affecté : {name}.')
            if 'conclusion' in public_changes and instance.conclusion:
                details.append(f'Conclusion : {CONCLUSIONS.get(instance.conclusion, instance.conclusion)}.')
            if 'structured_data' in public_changes:
                previous_data = old.get('structured_data') or {}
                for section, specification in CHECKLISTS.items():
                    previous_section = previous_data.get(section, {}) if isinstance(previous_data, dict) else {}
                    current_section = (instance.structured_data or {}).get(section, {})
                    if not isinstance(previous_section, dict):
                        previous_section = {}
                    for key, title in specification['checks'].items():
                        before_checked = previous_section.get(key) is True
                        after_checked = current_section.get(key) is True
                        if before_checked != after_checked:
                            details.append(f'{title} : {"coché" if after_checked else "décoché"}.')
                    if current_section.get('comment', '') != previous_section.get('comment', ''):
                        details.append(f'{specification["title"]} — commentaire : {current_section.get("comment") or "effacé"}.')
                    if section == 'maintenance' and current_section.get('battery_replaced_count') != previous_section.get('battery_replaced_count'):
                        details.append(f'Batteries remplacées : {current_section.get("battery_replaced_count", 0)}.')
        if sender is ServiceRequest and not created:
            if 'assigned_technician' in changed:
                assigned = instance.assigned_technician
                assigned_name = (assigned.get_full_name() or assigned.username) if assigned else 'Non affecté'
                details.append(f'Affectation : {assigned_name}.')
            if 'due_on' in changed:
                details.append(f'Échéance : {old.get("due_on") or "non renseignée"} → {instance.due_on or "non renseignée"}.')
            for field, title in [('arrived_at', 'Arrivée réelle'), ('closed_at', 'Clôture réelle')]:
                if field in changed:
                    details.append(f'{title} : {old.get(field) or "non renseignée"} → {getattr(instance, field) or "non renseignée"}.')
        summary = ' '.join([summary, *details])
        append_event(**common, kind=kind, status_before=old.get('status', ''),
                     status_after=getattr(instance, 'status', ''), observation=observation, summary=summary)
    if 'internal_notes' in changed and (getattr(instance, 'internal_notes', '') or old.get('internal_notes')):
        append_event(**common, kind='observation', observation=instance.internal_notes,
                     summary='Note interne de l’intervention.' if instance.internal_notes else 'Note interne effacée dans la fiche ; sa version antérieure reste conservée dans l’historique privé.', is_internal=True)


@receiver(post_save, sender=StockMovement, dispatch_uid='workflow_record_part_use')
def record_part_use(sender, instance, created, raw=False, **kwargs):
    if raw or not created or not instance.intervention_id:
        return
    intervention = instance.intervention
    append_event(equipment=intervention.service_request.equipment, service_request=intervention.service_request,
                 intervention=intervention, related_equipment=intervention.replacement_equipment,
                 actor=instance.created_by, kind='part_used',
                 summary=f'Pièce {instance.part.sku} : {abs(instance.quantity)} unité(s), {instance.get_kind_display().lower()}.')
