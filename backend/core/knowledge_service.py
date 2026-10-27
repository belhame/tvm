import re
from uuid import uuid4

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .knowledge_extraction import extract_uploaded_document
from .knowledge_models import KnowledgeChunk, KnowledgeSource, RepairCase, TechnicalDocument
from .knowledge_storage import knowledge_path, knowledge_storage
from .knowledge_normalization import normalized_key
from .models import AuditLog, Intervention


def ensure_internal(actor):
    if not actor or not actor.is_authenticated or not actor.is_active or actor.role in ('client', 'courier') or actor.effective_role not in ('admin', 'manager', 'technician'):
        raise PermissionDenied('Cette bibliothèque est réservée à l’équipe technique interne.')


def ensure_manager(actor):
    ensure_internal(actor)
    if actor.effective_role not in ('admin', 'manager'):
        raise PermissionDenied('L’approbation et l’archivage sont réservés au responsable SAV.')


def source_keys(brand, model, board_reference=''):
    keys = dict(brand_key=normalized_key(brand), model_key=normalized_key(model), board_reference_key=normalized_key(board_reference))
    for field, maximum in [('brand_key', 200), ('model_key', 240), ('board_reference_key', 240)]:
        if len(keys[field]) > maximum:
            raise ValidationError({'model': 'La référence normalisée est trop longue. Utilisez une désignation technique plus courte.'})
    return keys


def label(actor):
    return actor.get_full_name() or actor.username


def audit(actor, source, action):
    AuditLog.objects.create(actor=actor, action=action, resource=source._meta.model_name, resource_id=str(source.pk))


def text_chunks(pages):
    for page in pages:
        text = page['text'].strip()
        ordinal = 1
        while text:
            boundary = min(1800, len(text))
            if boundary < len(text):
                split = max(text.rfind('\n', 0, boundary), text.rfind(' ', 0, boundary))
                if split >= 900:
                    boundary = split
            excerpt = text[:boundary].strip()
            if excerpt:
                yield {'page': page['page'], 'ordinal': ordinal, 'text': excerpt}
                ordinal += 1
            text = text[boundary:].lstrip()


def create_technical_document(*, actor, uploaded, **fields):
    ensure_internal(actor)
    extracted = extract_uploaded_document(uploaded)
    checked = extracted['checked']
    keys = source_keys(fields['brand'], fields['model'], fields.get('board_reference', ''))
    if not keys['brand_key'] or not keys['model_key']:
        raise ValidationError({'model': 'Renseignez une marque et un modèle exacts exploitables.'})
    storage = knowledge_storage()
    name = f'knowledge/{uuid4().hex}.{checked.extension}'
    knowledge_path(name)  # Reject a pre-existing symlink in the private tree.
    saved_name = None
    try:
        saved_name = storage.save(name, ContentFile(checked.data))
        if saved_name != name:
            raise ValidationError({'file': 'Le chemin privé généré ne peut pas être réservé.'})
        with transaction.atomic():
            document = TechnicalDocument.objects.create(
                **fields, **keys, stored_name=name, original_name=checked.original_name,
                mime_type=checked.mime_type, size_bytes=len(checked.data), sha256=checked.sha256,
                pages=extracted['page_count'], text_status=extracted['text_status'], warnings=extracted['warnings'],
                created_by=actor, created_by_label=label(actor),
            )
            KnowledgeChunk.objects.bulk_create([KnowledgeChunk(document=document, **chunk) for chunk in text_chunks(extracted['pages'])])
            audit(actor, document, 'knowledge_upload')
        return document
    except Exception:
        if saved_name:
            try:
                storage.delete(saved_name)
            except OSError:
                pass
        raise


EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[a-z]{2,}', re.I)
PHONE = re.compile(r'(?<![\w])\+?\d(?:[ .()/-]*\d){8,14}(?![\w])')


def validate_anonymized(fields, intervention):
    narrative = '\n'.join(str(fields.get(key, '')) for key in ('symptoms', 'fault_code', 'measurements', 'confirmed_cause', 'repair', 'outcome', 'board_reference', 'revision'))
    if EMAIL.search(narrative) or PHONE.search(narrative):
        raise ValidationError({'detail': 'Retirez les adresses e-mail et numéros de téléphone avant de partager ce retour technique.'})
    request = intervention.service_request
    equipment = request.equipment
    company = equipment.client
    identifiers = [company.name, company.contact_name, company.email, company.phone, company.address,
                   equipment.serial_number, request.reference, request.client_reference]
    key = normalized_key(narrative)
    for identifier in identifiers:
        candidate = normalized_key(identifier)
        if len(candidate) >= 3 and re.search(r'(?<!\w)' + re.escape(candidate) + r'(?!\w)', key):
            raise ValidationError({'detail': 'Ce retour contient un identifiant ou une coordonnée du dossier source. Conservez uniquement les faits techniques anonymisés.'})


@transaction.atomic
def create_repair_case(*, actor, **fields):
    ensure_internal(actor)
    intervention_id = fields.pop('intervention')
    try:
        intervention = Intervention.objects.select_for_update(of=('self',)).select_related('service_request__equipment__client').get(pk=intervention_id)
    except Intervention.DoesNotExist as exc:
        raise NotFound('Intervention introuvable.') from exc
    if actor.effective_role == 'technician' and intervention.technician_id != actor.pk:
        raise PermissionDenied('Un technicien contribue uniquement depuis ses propres interventions terminées.')
    if intervention.status != 'completed':
        raise ValidationError({'intervention': 'Terminez réellement l’intervention avant de proposer un retour de réparation.'})
    validate_anonymized(fields, intervention)
    equipment = intervention.service_request.equipment
    case = RepairCase.objects.create(
        intervention=intervention, brand=equipment.brand, model=equipment.model,
        **fields, **source_keys(equipment.brand, equipment.model, fields.get('board_reference', '')),
        created_by=actor, created_by_label=label(actor),
        warnings=['Retour déclaratif à vérifier humainement : cause, mesures, réparation et résultat doivent être confirmés.',
                  'Les contrôles automatiques ne garantissent pas une anonymisation complète.'],
    )
    audit(actor, case, 'knowledge_contribution')
    return case


def case_is_eligible(case):
    equipment = case.intervention.service_request.equipment
    return (case.state == KnowledgeSource.State.APPROVED and case.intervention.status == 'completed'
            and case.brand_key == normalized_key(equipment.brand) and case.model_key == normalized_key(equipment.model))


def approved_chunks(*, brand, model, board_reference='', revision=''):
    filters = {'document__state': 'approved', 'document__brand_key': normalized_key(brand),
               'document__model_key': normalized_key(model), 'document__text_status__in': ['extracted', 'partial']}
    if not filters['document__brand_key'] or not filters['document__model_key']:
        return KnowledgeChunk.objects.none()
    queryset = KnowledgeChunk.objects.filter(**filters).exclude(text='').select_related('document')
    from django.db.models import Q
    if board_reference:
        queryset = queryset.filter(Q(document__board_reference_key=normalized_key(board_reference)) | Q(document__board_reference_key=''))
    if revision:
        versions = queryset.order_by().values_list('document_id', 'document__revision').distinct()
        allowed = [document_id for document_id, version in versions if not version or normalized_key(version) == normalized_key(revision)]
        queryset = queryset.filter(document_id__in=allowed)
    return queryset


def approved_cases(*, brand, model, board_reference='', revision=''):
    filters = {'state': 'approved', 'brand_key': normalized_key(brand), 'model_key': normalized_key(model), 'intervention__status': 'completed'}
    if not filters['brand_key'] or not filters['model_key']:
        return RepairCase.objects.none()
    queryset = RepairCase.objects.filter(**filters).select_related('intervention__service_request__equipment')
    from django.db.models import Q
    if board_reference:
        queryset = queryset.filter(Q(board_reference_key=normalized_key(board_reference)) | Q(board_reference_key=''))
    ids = [case.pk for case in queryset if case_is_eligible(case) and (not revision or not case.revision or normalized_key(case.revision) == normalized_key(revision))]
    return queryset.filter(pk__in=ids)


@transaction.atomic
def transition_source(*, actor, source, action):
    ensure_manager(actor)
    source = type(source).objects.select_for_update().get(pk=source.pk)
    if action == 'approve':
        if source.state != 'draft':
            raise ValidationError({'state': 'Seul un brouillon peut être approuvé.'})
        if isinstance(source, RepairCase):
            intervention = Intervention.objects.select_for_update().select_related('service_request__equipment__client').get(pk=source.intervention_id)
            if intervention.status != 'completed':
                raise ValidationError({'intervention': 'L’intervention source n’est plus terminée ; ce retour ne peut pas être approuvé.'})
            fields = {key: getattr(source, key) for key in ('symptoms', 'fault_code', 'measurements', 'confirmed_cause', 'repair', 'outcome', 'board_reference', 'revision')}
            validate_anonymized(fields, intervention)
            equipment = intervention.service_request.equipment
            if source.brand_key != normalized_key(equipment.brand) or source.model_key != normalized_key(equipment.model):
                raise ValidationError({'model': 'Le modèle source a changé. Créez un nouveau retour correctement rattaché.'})
        source.state = 'approved'
        source.approved_at = timezone.now()
        source.approved_by = actor
        source.approved_by_label = label(actor)
        source.save(update_fields=['state', 'approved_at', 'approved_by', 'approved_by_label'])
    elif action == 'archive':
        if source.state == 'archived':
            return source
        source.state = 'archived'
        source.archived_at = timezone.now()
        source.save(update_fields=['state', 'archived_at'])
    else:
        raise ValidationError('Action inconnue.')
    audit(actor, source, f'knowledge_{action}')
    return source
