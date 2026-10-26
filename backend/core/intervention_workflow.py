"""Controlled intervention sheets; checked fields are explicit operator input.

No warranty, billing, exchange, or equipment mutation is inferred from a
checkbox. The original equipment remains the service request's equipment.
"""

import json

from django.utils import timezone
from rest_framework.exceptions import ValidationError


INTERVENTION_KINDS = {
    'maintenance': 'Maintenance',
    'exchange': 'Échange',
    'commissioning': 'Mise en service',
    'preventive': 'Maintenance préventive',
}
CONCLUSIONS = {
    'follow_up': 'À suivre',
    'completed': 'Terminée',
    'not_applicable_billable': 'Garantie non applicable / à facturer',
}
CHECKLISTS = {
    'maintenance': {
        'title': 'Maintenance — pannes et actions',
        'checks': {
            'battery_failure': 'Défaillance des batteries',
            'electronics_failure': 'Défaillance électronique',
            'overload': 'Surcharge',
            'overvoltage': 'Surtension',
            'overheating': 'Surchauffe',
            'replace_batteries': 'Remplacement des batteries',
            'configure': 'Paramétrage',
            'replace_board': 'Remplacement de carte',
            'replace_ups': 'Remplacement de l’onduleur',
            'recover_ups': 'Récupération de l’onduleur',
            'repair_board': 'Réparation de carte',
        },
    },
    'commissioning': {
        'title': 'Mise en service — vérifications et essais',
        'checks': {
            'electrical_protection': 'Vérification de la protection électrique',
            'cable_section': 'Vérification de la section des câbles',
            'configure': 'Paramétrage',
            'connection': 'Branchement',
            'power_on': 'Mise sous tension',
            'normal_operation_test': 'Test de fonctionnement normal',
            'runtime_test': 'Test d’autonomie',
            'bypass_test': 'Test du by-pass',
            'alarm_test': 'Test des alarmes',
        },
    },
    'preventive': {
        'title': 'Travaux préventifs',
        'checks': {
            'environment': 'Contrôle de l’environnement de l’onduleur',
            'power_cables': 'Contrôle des câbles d’alimentation',
            'alarm_history': 'Contrôle de l’historique des alarmes',
            'runtime_test': 'Test de fonctionnement en autonomie',
            'bypass_test': 'Test du by-pass',
            'alarm_test': 'Test des alarmes',
            'dusting': 'Dépoussiérage',
        },
    },
}


def _value(serializer, attrs, name, default=None):
    if name in attrs:
        return attrs[name]
    return getattr(serializer.instance, name, default) if serializer.instance else default


def validate_structured_data(value):
    if not isinstance(value, dict):
        raise ValidationError({'structured_data': 'Un objet de checklists est requis.'})
    if set(value) - set(CHECKLISTS):
        raise ValidationError({'structured_data': 'Section non prise en charge dans les checklists.'})
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        encoded.encode('utf-8', errors='strict')
        if len(encoded) > 32_000:
            raise ValueError()
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise ValidationError({'structured_data': 'Les checklists sont trop volumineuses ou contiennent une valeur invalide.'}) from exc
    for section, fields in value.items():
        if not isinstance(fields, dict):
            raise ValidationError({'structured_data': f'La section {section} doit être un objet.'})
        allowed = set(CHECKLISTS[section]['checks']) | {'comment'}
        if section == 'maintenance':
            allowed.add('battery_replaced_count')
        if set(fields) - allowed:
            raise ValidationError({'structured_data': f'Champ non pris en charge dans la section {section}.'})
        for key, field in fields.items():
            if key in CHECKLISTS[section]['checks'] and type(field) is not bool:
                raise ValidationError({'structured_data': f'Les cases de la section {section} doivent être de vrais booléens JSON.'})
            if key == 'comment' and (not isinstance(field, str) or len(field) > 4000 or '\x00' in field):
                raise ValidationError({'structured_data': f'Le commentaire de la section {section} est limité à 4 000 caractères.'})
            if key == 'battery_replaced_count' and (type(field) is not int or not 0 <= field <= 100_000):
                raise ValidationError({'structured_data': 'Le nombre de batteries remplacées doit être un entier entre 0 et 100 000.'})
    return value


def validate_intervention_workflow(serializer, attrs):
    """Called after the existing InterventionSerializer permission validation."""
    kind = _value(serializer, attrs, 'kind', 'maintenance')
    if kind not in INTERVENTION_KINDS:
        raise ValidationError({'kind': 'Choisissez un type d’intervention pris en charge.'})
    state = _value(serializer, attrs, 'status', 'scheduled')
    performed = _value(serializer, attrs, 'performed_on')
    if performed is not None and performed > timezone.localdate():
        raise ValidationError({'performed_on': 'La date de réalisation ne peut pas être future. Utilisez la date planifiée pour une visite à venir.'})
    if state == 'completed' and kind != 'maintenance' and performed is None:
        raise ValidationError({'performed_on': 'Renseignez la date de réalisation avant de terminer cette fiche.'})
    count = _value(serializer, attrs, 'battery_count')
    if count is not None and (type(count) is not int or not 0 <= count <= 100_000):
        raise ValidationError({'battery_count': 'Le nombre de batteries doit être compris entre 0 et 100 000.'})
    for field, limit in [('summary', 10_000), ('conclusion_notes', 4000)]:
        text = _value(serializer, attrs, field, '')
        if not isinstance(text, str) or len(text) > limit:
            raise ValidationError({field: f'Ce texte est limité à {limit} caractères.'})
    conclusion = _value(serializer, attrs, 'conclusion', '')
    if conclusion and conclusion not in CONCLUSIONS:
        raise ValidationError({'conclusion': 'Choisissez une conclusion prise en charge.'})
    if conclusion == 'not_applicable_billable' and not _value(serializer, attrs, 'conclusion_notes', '').strip():
        raise ValidationError({'conclusion_notes': 'Justifiez cette appréciation manuelle. Les dates de garantie ne prennent pas cette décision à votre place.'})
    structured = validate_structured_data(_value(serializer, attrs, 'structured_data', {}))
    maintenance = structured.get('maintenance', {})
    replaced_count = maintenance.get('battery_replaced_count', 0)
    if replaced_count and not maintenance.get('replace_batteries', False):
        raise ValidationError({'structured_data': 'Cochez le remplacement des batteries pour renseigner leur nombre.'})
    if state == 'completed' and maintenance.get('replace_batteries') and replaced_count < 1:
        raise ValidationError({'structured_data': 'Précisez le nombre de batteries remplacées avant de terminer l’intervention.'})
    service_request = _value(serializer, attrs, 'service_request')
    if service_request is None:
        return attrs  # The model serializer reports the required FK itself.
    original = service_request.equipment
    replacement = _value(serializer, attrs, 'replacement_equipment')
    if replacement is not None:
        if kind != 'exchange':
            raise ValidationError({'replacement_equipment': 'Un matériel de remplacement se renseigne sur une fiche d’échange.'})
        if replacement.pk == original.pk:
            raise ValidationError({'replacement_equipment': 'Le nouveau matériel doit être différent du matériel d’origine.'})
        if replacement.client_id != original.client_id:
            raise ValidationError({'replacement_equipment': 'Le nouveau matériel doit appartenir au même client que le matériel d’origine.'})
    if kind == 'exchange' and state == 'completed' and replacement is None:
        raise ValidationError({'replacement_equipment': 'Choisissez le nouvel équipement avant de terminer l’échange.'})
    contract = _value(serializer, attrs, 'contract')
    if contract is not None and (
        contract.client_id != original.client_id or contract.equipment_id not in (None, original.pk)
    ):
        raise ValidationError({'contract': 'Le contrat doit concerner ce client et cet équipement, ou l’ensemble du client.'})
    extension = _value(serializer, attrs, 'extension_warranty')
    if extension is not None and extension.equipment_id != original.pk:
        raise ValidationError({'extension_warranty': 'L’extension sélectionnée doit concerner le matériel d’origine du dossier SAV.'})
    return attrs


def report_checklists(data):
    """Whitelist-only representation: unknown legacy JSON keys are never printed."""
    if not isinstance(data, dict):
        return []
    result = []
    for key, specification in CHECKLISTS.items():
        fields = data.get(key)
        if not isinstance(fields, dict):
            continue
        checks = [
            {'label': label, 'checked': fields[name]}
            for name, label in specification['checks'].items()
            if type(fields.get(name)) is bool
        ]
        comment = fields.get('comment') if isinstance(fields.get('comment'), str) else ''
        count = fields.get('battery_replaced_count') if key == 'maintenance' and type(fields.get('battery_replaced_count')) is int else None
        if checks or comment or count is not None:
            result.append({'title': specification['title'], 'checks': checks, 'comment': comment, 'battery_replaced_count': count})
    return result
