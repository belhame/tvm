"""Atomic service-request intake, with server-side catalogue reconciliation."""

from __future__ import annotations

import calendar
from copy import deepcopy
import hashlib
import json
from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .catalogue_models import CatalogueProduct, CatalogueWarranty
from .catalogue_service import usable_code
from .models import AuditLog, Client, Equipment, ServiceRequest, Warranty
from .request_followup import FOLLOWUP_FIELD_NAMES, validate_followup


MAX_ID = 9_223_372_036_854_775_807


class IntakeConflict(APIException):
    status_code = 409
    default_detail = 'Cette demande entre en conflit avec une opération existante. Rechargez les données avant de réessayer.'


class IntakeInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    serial_number = serializers.CharField(max_length=120)
    subject = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=20_000, required=False, allow_blank=True, default='')
    priority = serializers.ChoiceField(choices=ServiceRequest.Priority.choices, default=ServiceRequest.Priority.NORMAL)
    equipment = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False, allow_null=True)
    client = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False, allow_null=True)
    profile = serializers.ChoiceField(choices=['Eaton', 'Pulsar', 'Powerware', 'NV DX'], required=False, allow_null=True)
    catalogue_import_id = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False, allow_null=True)
    product_id = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False, allow_null=True)
    warranty_reference_id = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False, allow_null=True)
    manual_model = serializers.CharField(max_length=120, required=False, allow_blank=True)
    manufactured_on_override = serializers.DateField(required=False, allow_null=True)
    duration_months_override = serializers.IntegerField(min_value=0, max_value=1200, required=False, allow_null=True)
    warranty_start_override = serializers.DateField(required=False, allow_null=True)
    manual_reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')
    arrived_at = serializers.DateTimeField(required=False, allow_null=True)
    client_reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    end_customer = serializers.CharField(max_length=200, required=False, allow_blank=True)
    return_flag = serializers.BooleanField(required=False)
    packaging = serializers.CharField(max_length=250, required=False, allow_blank=True)
    service_location = serializers.ChoiceField(choices=ServiceRequest.ServiceLocation.choices, required=False)
    delivered_by = serializers.ChoiceField(choices=ServiceRequest.DeliveredBy.choices, required=False)
    courier_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    accessories = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    warranty_status = serializers.ChoiceField(choices=ServiceRequest.WarrantyStatus.choices, required=False)
    contact_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise ValidationError({'detail': 'Le formulaire contient un champ non pris en charge.'})
        manual = bool(attrs.get('manual_model')) or any(
            attrs.get(field) is not None
            for field in ('manufactured_on_override', 'duration_months_override', 'warranty_start_override')
        )
        if manual and not attrs.get('manual_reason', '').strip():
            raise ValidationError({'manual_reason': 'Expliquez la correction ou la saisie manuelle avant de l’enregistrer.'})
        return validate_followup(attrs, user=self.context.get('actor'), initial_data=self.initial_data)


@dataclass(frozen=True)
class IntakeResult:
    request: ServiceRequest
    equipment: Equipment
    warranty: Warranty | None
    created: bool
    created_equipment: bool
    intake: dict


def add_calendar_months(day: date, months: int) -> date:
    """Calendar arithmetic; Jan 31 + one month is the last day of February."""
    year, month_zero = divmod(day.year * 12 + day.month - 1 + months, 12)
    month = month_zero + 1
    if not 1 <= year <= 9999:
        raise ValidationError({'duration_months_override': 'L’échéance calculée dépasse les limites du calendrier.'})
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _canonical_input(data):
    result = {}
    for key, value in data.items():
        if value is None:
            continue
        result[key] = value.isoformat() if isinstance(value, date) else str(value) if key == 'request_key' else value
    # Equipment serial uniqueness and catalogue matching are case-insensitive.
    result['serial_number'] = result['serial_number'].strip().lower()
    return result


def _fingerprint(data):
    return hashlib.sha256(json.dumps(_canonical_input(data), sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def _replay(row, actor, fingerprint):
    saved = row.intake_data or {}
    if saved.get('actor_id') != actor.pk or saved.get('payload_hash') != fingerprint:
        # Do not disclose another actor, serial, client, or request reference.
        raise IntakeConflict('Cette clé de demande a déjà été utilisée. Créez une nouvelle clé pour une nouvelle opération.')
    summary = saved.get('summary', {})
    warranty = Warranty.objects.filter(pk=summary.get('created_warranty_id'), equipment_id=row.equipment_id).first()
    return IntakeResult(row, row.equipment, warranty, False, bool(summary.get('created_equipment')), summary)


def _date_from_lookup(value):
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({'serial_number': 'La date proposée par le catalogue n’est pas exploitable.'}) from exc


def _catalogue_choices(data, lookup, *, creating_equipment):
    selected = lookup.get('selected_product')
    candidates = lookup.get('product_candidates') or []
    if data.get('product_id') and (not selected or selected.get('id') != data['product_id']):
        raise ValidationError({'product_id': 'Sélectionnez un candidat correspondant à ce numéro de série et à cette version du catalogue.'})
    if creating_equipment and not selected and candidates:
        raise ValidationError({'product_id': 'Plusieurs modèles restent possibles. Sélectionnez explicitement la référence du produit.'})
    product = None
    if selected:
        product = CatalogueProduct.objects.filter(pk=selected['id'], snapshot_id=lookup.get('catalogue_import_id')).first()
        if product is None:
            raise ValidationError({'product_id': 'La référence sélectionnée n’appartient pas à la version du catalogue utilisée.'})
        detected_code = (lookup.get('detection') or {}).get('segments', {}).get('product_code')
        if creating_equipment:
            if usable_code(detected_code) and str(detected_code).strip().casefold() != product.product_code.strip().casefold():
                raise ValidationError({'product_id': 'Le produit choisi ne correspond pas au code reconnu dans la série.'})
            if not usable_code(detected_code) and not data.get('manual_reason', '').strip():
                raise ValidationError({'manual_reason': 'La série ne prouve pas le modèle choisi. Justifiez la référence vérifiée manuellement sur l’équipement.'})
    selected_warranty = lookup.get('selected_warranty')
    allowed_warranties = {item.get('id') for item in lookup.get('warranty_options', [])}
    if data.get('warranty_reference_id') and (
        not selected_warranty or selected_warranty.get('id') != data['warranty_reference_id']
        or data['warranty_reference_id'] not in allowed_warranties
    ):
        raise ValidationError({'warranty_reference_id': 'Choisissez une garantie proposée pour la référence sélectionnée.'})
    warranty_reference = None
    if selected_warranty:
        if selected_warranty.get('id') not in allowed_warranties:
            raise ValidationError({'warranty_reference_id': 'Cette garantie ne correspond pas à la sélection du catalogue.'})
        warranty_reference = CatalogueWarranty.objects.filter(
            pk=selected_warranty['id'], snapshot_id=lookup.get('catalogue_import_id'),
        ).first()
        if warranty_reference is None:
            raise ValidationError({'warranty_reference_id': 'La garantie sélectionnée n’appartient pas à la version du catalogue utilisée.'})
    return product, warranty_reference


def _snapshot_product(product):
    if product is None:
        return None
    return {
        'id': product.pk, 'import_id': product.snapshot_id,
        'source_sheet': product.source_sheet, 'source_row': product.source_row,
        'product_name': product.product_name, 'product_code': product.product_code,
        'structure': product.structure, 'catalogue_number': product.catalogue_number,
        'manufacturing_part_number': product.manufacturing_part_number,
    }


def _snapshot_warranty(reference):
    if reference is None:
        return None
    return {
        'id': reference.pk, 'import_id': reference.snapshot_id,
        'source_sheet': reference.source_sheet, 'source_row': reference.source_row,
        'source_column': reference.source_column, 'product_name': reference.product_name,
        'scope': reference.scope, 'category': reference.category,
        'duration_text': reference.duration_text, 'duration_months': reference.duration_months,
        'conditions': reference.conditions,
    }


def _resolve_dates(data, lookup, reference):
    manufactured = data.get('manufactured_on_override') or _date_from_lookup(lookup.get('manufactured_on'))
    basis = dict(lookup.get('manufacture_date_basis') or {})
    if data.get('manufactured_on_override'):
        basis = {'type': 'manual', 'reconstructed': False, 'precision': 'day', 'source': 'Saisie explicite de l’utilisateur', 'reason': data['manual_reason']}
    months = reference.duration_months if reference is not None else None
    manual_months = data.get('duration_months_override')
    if manual_months is not None:
        if months is not None and months != manual_months:
            raise ValidationError({'duration_months_override': 'La durée renseignée contredit la référence de garantie choisie.'})
        if reference is None and lookup.get('warranty_options'):
            raise ValidationError({'warranty_reference_id': 'Sélectionnez une référence de garantie avant de préciser sa durée.'})
        months = manual_months
    start = add_calendar_months(manufactured, 6) if manufactured else None
    if data.get('warranty_start_override') and data['warranty_start_override'] != start:
        raise ValidationError({'warranty_start_override': 'Le début doit correspondre à la date de fabrication augmentée de six mois calendaires.'})
    if months == 0:
        start = None
    # Zero months is an explicit absence of coverage, not a one-day warranty.
    end = add_calendar_months(start, months) if start and months is not None and months > 0 else None
    return manufactured, basis, months, start, end


def _lookup_serial(data):
    from .serial_lookup import lookup_serial
    return lookup_serial(
        data['serial_number'], profile=data.get('profile'), product_id=data.get('product_id'),
        catalogue_import_id=data.get('catalogue_import_id'), warranty_reference_id=data.get('warranty_reference_id'),
    )


def _perform_intake(data, *, actor, fingerprint):
    # The initial check is repeated inside the transaction before all writes.
    previous = ServiceRequest.objects.select_for_update().select_related('equipment__client').filter(intake_key=data['request_key']).first()
    if previous is not None:
        return _replay(previous, actor, fingerprint)

    supplied_equipment_id = data.get('equipment')
    # Keep concurrent intakes serialized while permitting FK KEY SHARE locks
    # from another request waiting behind the annual call-number allocation.
    equipment_qs = Equipment.objects.select_for_update(no_key=True).select_related('client')
    if supplied_equipment_id:
        equipment = equipment_qs.filter(pk=supplied_equipment_id).first()
        if equipment is None or equipment.serial_number.lower() != data['serial_number'].lower():
            raise ValidationError({'equipment': 'L’équipement choisi ne correspond pas au numéro de série saisi.'})
    else:
        equipment = equipment_qs.filter(serial_number__iexact=data['serial_number']).first()
    creating_equipment = equipment is None
    if creating_equipment and actor.effective_role not in ('admin', 'manager'):
        raise PermissionDenied('Un technicien peut ouvrir un dossier sur un équipement existant ; le responsable crée les nouveaux équipements.')
    client_id = data.get('client')
    if equipment is not None:
        if client_id and equipment.client_id != client_id:
            raise ValidationError({'client': 'Cet équipement appartient déjà à un autre client. Aucun transfert n’a été effectué.'})
        client = equipment.client
    else:
        if not client_id:
            raise ValidationError({'client': 'Choisissez le client propriétaire du nouvel équipement.'})
        client = Client.objects.filter(pk=client_id).first()
        if client is None:
            raise ValidationError({'client': 'Le client sélectionné n’existe pas.'})

    manual = bool(data.get('manual_model')) or any(data.get(field) is not None for field in ('manufactured_on_override', 'duration_months_override', 'warranty_start_override'))
    if manual and actor.effective_role not in ('admin', 'manager'):
        raise PermissionDenied('Les corrections de modèle, date ou durée sont réservées au responsable SAV et à l’administrateur.')
    lookup = _lookup_serial(data)
    product, reference = _catalogue_choices(data, lookup, creating_equipment=creating_equipment)
    manufactured, basis, months, warranty_start, warranty_end = _resolve_dates(data, lookup, reference)
    short_model = product.catalogue_number.strip() if product else ''
    model = (
        short_model if usable_code(short_model) and len(short_model) <= 120 else product.product_name
    ) if product else data.get('manual_model', '')
    if creating_equipment:
        if product and data.get('manual_model') and data['manual_model'] != model:
            if len(model) <= 120:
                raise ValidationError({'manual_model': 'Le modèle doit correspondre à la référence du catalogue sélectionnée.'})
            model = data['manual_model']  # Explicit short designation; full source is retained below.
        if not model:
            raise ValidationError({'manual_model': 'Aucun modèle certain n’est disponible. Saisissez le modèle observé et expliquez la saisie manuelle.'})
        if len(model) > 120:
            raise ValidationError({'manual_model': 'Le libellé du catalogue dépasse 120 caractères. Renseignez une désignation courte et sa justification ; la référence complète sera conservée.'})
        equipment = Equipment.objects.create(
            client=client, serial_number=data['serial_number'], model=model,
            brand='Eaton' if product else 'À confirmer',
            catalogue_product=product, manufactured_on=manufactured,
            warranty_until=warranty_end,
        )

    created_warranty = None
    if creating_equipment and warranty_start is not None and warranty_end is not None:
        scope = reference.scope if reference and reference.scope in Warranty.Scope.values else Warranty.Scope.UNSPECIFIED
        terms = [
            'Règle TVM : début = date de fabrication + 6 mois calendaires.',
            f'Durée : {months} mois. Fin = début + durée ; aucun arrondi en jours.',
            f'Base de fabrication : {basis.get("type", "non précisée")} ; précision : {basis.get("precision", "non précisée")}.',
        ]
        if basis.get('reconstructed'):
            terms.append('Date de fabrication reconstituée selon la règle documentée ; elle ne certifie pas le jour exact de fabrication.')
        if reference:
            terms.append(f'Catalogue import {reference.snapshot_id}, SHA-256 {reference.snapshot.sha256}, feuille {reference.source_sheet}, ligne {reference.source_row}, colonne {reference.source_column}.')
            terms.append(f'Portée : {scope}. Conditions source : {reference.conditions}')
        created_warranty = Warranty.objects.create(
            equipment=equipment, provider='Référence constructeur / règle TVM' if reference else 'Saisie manuelle validée',
            scope=scope, starts_on=warranty_start, ends_on=warranty_end, terms='\n'.join(terms),
        )

    summary = {
        'normalized_serial_number': lookup.get('normalized_serial_number', data['serial_number']),
        'created_equipment': creating_equipment, 'existing_equipment_preserved': not creating_equipment,
        'catalogue_import_id': lookup.get('catalogue_import_id'),
        'selected_product': _snapshot_product(product), 'selected_warranty': _snapshot_warranty(reference),
        'manufactured_on': manufactured.isoformat() if manufactured else None,
        'manufacture_date_basis': basis,
        'computed_warranty': {
            'starts_on': warranty_start.isoformat() if warranty_start else None,
            'ends_on': warranty_end.isoformat() if warranty_end else None,
            'duration_months': months, 'applied_to_equipment': bool(created_warranty),
            'status': (
                'no_coverage' if months == 0 else 'estimated' if warranty_end
                else 'manufacture_unknown' if manufactured is None else 'needs_choice'
                if lookup.get('warranty_options') and reference is None else 'unavailable'
            ),
            'coverage_status': (
                'not_covered' if months == 0 else 'unknown' if warranty_end is None
                else 'not_started' if warranty_start > timezone.localdate()
                else 'expired' if warranty_end < timezone.localdate() else 'active'
            ),
            'rule': {'code': 'manufactured_on_plus_6_calendar_months', 'start_offset_months': 6},
        },
        'created_warranty_id': created_warranty.pk if created_warranty else None,
        'warnings': lookup.get('warnings', []),
        'manual_reason': data.get('manual_reason', ''),
    }
    if not creating_equipment:
        # Keep the warranty actually recorded on the equipment as the retained
        # outcome. A catalogue estimate is a separate, unapplied proposal.
        summary['catalogue_estimate'] = {
            **summary['computed_warranty'],
            'manufactured_on': summary['manufactured_on'],
            'manufacture_date_basis': deepcopy(summary['manufacture_date_basis']),
        }
        summary['computed_warranty'] = {
            **deepcopy(lookup.get('computed_warranty') or {}),
            'applied_to_equipment': False,
        }
        summary['recorded_warranties'] = [
            {key: warranty.get(key) for key in ('id', 'scope', 'starts_on', 'ends_on', 'coverage_status', 'provider')}
            for warranty in lookup.get('recorded_warranties', [])
        ]
        summary['warnings'] = [*summary['warnings'], 'Le modèle, la garantie et les contrats de l’équipement existant ont été conservés sans modification.']
    saved = ServiceRequest.objects.create(
        equipment=equipment, subject=data['subject'], description=data['description'], priority=data['priority'],
        requested_by=actor, intake_key=data['request_key'],
        intake_data={'actor_id': actor.pk, 'payload_hash': fingerprint, 'input': _canonical_input(data), 'summary': summary},
        **{field: data[field] for field in FOLLOWUP_FIELD_NAMES if field in data},
    )
    for resource, instance in [('equipment', equipment)] if creating_equipment else []:
        AuditLog.objects.create(actor=actor, action='create_intake', resource=resource, resource_id=str(instance.pk))
    if created_warranty:
        AuditLog.objects.create(actor=actor, action='create_intake', resource='warranty', resource_id=str(created_warranty.pk))
    AuditLog.objects.create(actor=actor, action='create_intake', resource='servicerequest', resource_id=str(saved.pk))
    return IntakeResult(saved, equipment, created_warranty, True, creating_equipment, summary)


def create_intake(payload, *, actor):
    if not actor or not getattr(actor, 'pk', None) or not actor.is_active or actor.effective_role not in ('admin', 'manager', 'technician'):
        raise PermissionDenied('Cette opération est réservée aux utilisateurs internes actifs.')
    serializer = IntakeInputSerializer(data=payload, context={'actor': actor})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    fingerprint = _fingerprint(data)
    try:
        with transaction.atomic():
            return _perform_intake(data, actor=actor, fingerprint=fingerprint)
    except IntegrityError as exc:
        # Covers concurrent identical submissions even if they raced first on
        # the case-insensitive serial constraint before inserting the key.
        previous = ServiceRequest.objects.select_related('equipment__client').filter(intake_key=data['request_key']).first()
        if previous is not None:
            return _replay(previous, actor, fingerprint)
        raise IntakeConflict() from exc
