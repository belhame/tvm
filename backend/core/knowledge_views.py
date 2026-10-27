from django.db.models import Count, Q
from django.http import FileResponse
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .knowledge_models import RepairCase, TechnicalDocument
from .knowledge_serializers import CaseInput, DocumentInput
from .knowledge_service import case_is_eligible, create_repair_case, create_technical_document, ensure_internal, normalized_key, transition_source
from .knowledge_storage import knowledge_path
from .models import AuditLog


class KnowledgePermission(BasePermission):
    def has_permission(self, request, view):
        ensure_internal(request.user)
        return True


def source_metadata(source):
    return {'id': source.pk, 'brand': source.brand, 'model': source.model, 'board_reference': source.board_reference,
            'state': source.state, 'created_at': source.created_at.isoformat(), 'created_by_name': source.created_by_label,
            'approved_at': source.approved_at.isoformat() if source.approved_at else None,
            'approved_by_name': source.approved_by_label or None,
            'archived_at': source.archived_at.isoformat() if source.archived_at else None, 'warnings': source.warnings}


def document_metadata(document, *, detail=False):
    data = {**source_metadata(document), 'title': document.title, 'revision': document.revision,
            'kind': document.kind, 'original_name': document.original_name, 'mime_type': document.mime_type,
            'size_bytes': document.size_bytes, 'sha256': document.sha256, 'pages': document.pages,
            'text_status': document.text_status, 'chunk_count': getattr(document, 'chunk_count', None),
            'download_url': f'/api/knowledge/documents/{document.pk}/download/'}
    if data['chunk_count'] is None:
        data['chunk_count'] = document.chunks.count()
    if detail:
        data['chunks'] = [{'id': chunk.pk, 'page': chunk.page, 'ordinal': chunk.ordinal, 'text': chunk.text,
                           'source_id': f'D{document.pk}-P{chunk.page}-C{chunk.ordinal}'} for chunk in document.chunks.all()]
    return data


def case_metadata(case):
    return {**source_metadata(case), 'intervention': case.intervention_id,
            'revision': case.revision,
            'source_intervention_reference': case.intervention.reference,
            **{name: getattr(case, name) for name in ('symptoms', 'fault_code', 'measurements', 'confirmed_cause', 'repair', 'outcome')},
            'eligible_for_retrieval': case_is_eligible(case)}


def private_response(data, *, status=200):
    response = Response(data, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def get_source(model, source_id):
    try:
        return model.objects.get(pk=source_id)
    except model.DoesNotExist as exc:
        raise NotFound('Source technique introuvable.') from exc


def filtered_sources(queryset, params, *, documents=False):
    allowed = {'brand', 'model', 'board_reference', 'state', 'q'} | ({'kind'} if documents else set())
    if set(params) - allowed or any(len(params.getlist(key)) != 1 for key in params):
        raise ValidationError('Les filtres contiennent un champ inconnu ou dupliqué.')
    for key in params:
        value = params[key]
        if len(value) > 200 or '\x00' in value or '\ufffd' in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValidationError({key: 'Un filtre valide de 200 caractères au maximum est requis.'})
    for key in ('brand', 'model', 'board_reference'):
        if params.get(key, '').strip():
            queryset = queryset.filter(**{f'{key}_key': normalized_key(params[key])})
    if params.get('state'):
        if params['state'] not in ('draft', 'approved', 'archived'):
            raise ValidationError({'state': 'État de source inconnu.'})
        queryset = queryset.filter(state=params['state'])
    if documents and params.get('kind'):
        if params['kind'] not in TechnicalDocument.Kind.values:
            raise ValidationError({'kind': 'Type de document inconnu.'})
        queryset = queryset.filter(kind=params['kind'])
    query = params.get('q', '').strip()
    if query:
        condition = Q(brand__icontains=query) | Q(model__icontains=query) | Q(board_reference__icontains=query)
        if documents:
            condition |= Q(title__icontains=query)
        else:
            condition |= Q(symptoms__icontains=query) | Q(fault_code__icontains=query) | Q(confirmed_cause__icontains=query)
        queryset = queryset.filter(condition)
    return queryset


@api_view(['GET', 'POST'])
@permission_classes([KnowledgePermission])
@parser_classes([MultiPartParser])
def knowledge_documents(request):
    if request.method == 'GET':
        queryset = filtered_sources(TechnicalDocument.objects.annotate(chunk_count=Count('chunks')), request.query_params, documents=True)
        return private_response([document_metadata(item) for item in queryset])
    if set(request.data) - {'file', *DocumentInput().fields} or any(len(request.data.getlist(key)) != 1 for key in request.data):
        raise ValidationError('Le formulaire contient un champ inconnu ou dupliqué.')
    files = request.FILES.getlist('file')
    if len(files) != 1:
        raise ValidationError({'file': 'Joignez exactement un fichier PDF ou TXT dans le champ file.'})
    serializer = DocumentInput(data={key: request.data[key] for key in request.data if key != 'file'})
    serializer.is_valid(raise_exception=True)
    document = create_technical_document(actor=request.user, uploaded=files[0], **serializer.validated_data)
    return private_response(document_metadata(document), status=201)


@api_view(['GET'])
@permission_classes([KnowledgePermission])
def knowledge_document_detail(request, document_id):
    return private_response(document_metadata(get_source(TechnicalDocument, document_id), detail=True))


@api_view(['GET'])
@permission_classes([KnowledgePermission])
def knowledge_document_download(request, document_id):
    document = get_source(TechnicalDocument, document_id)
    try:
        stream = knowledge_path(document.stored_name).open('rb')
    except (OSError, ValueError) as exc:
        raise NotFound('Le fichier technique privé n’est plus disponible.') from exc
    AuditLog.objects.create(actor=request.user, action='knowledge_download', resource='technicaldocument', resource_id=str(document.pk))
    response = FileResponse(stream, as_attachment=True, filename=document.original_name, content_type=document.mime_type)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@api_view(['GET', 'POST'])
@permission_classes([KnowledgePermission])
@parser_classes([JSONParser])
def knowledge_cases(request):
    if request.method == 'GET':
        queryset = RepairCase.objects.select_related('intervention__service_request__equipment')
        return private_response([case_metadata(case) for case in filtered_sources(queryset, request.query_params)])
    serializer = CaseInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    case = create_repair_case(actor=request.user, **serializer.validated_data)
    return private_response(case_metadata(case), status=201)


@api_view(['GET'])
@permission_classes([KnowledgePermission])
def knowledge_case_detail(request, case_id):
    return private_response(case_metadata(get_source(RepairCase, case_id)))


def transition_response(request, model, source_id, action):
    if not isinstance(request.data, dict) or request.data:
        raise ValidationError('Cette action accepte uniquement un objet JSON vide.')
    source = transition_source(actor=request.user, source=get_source(model, source_id), action=action)
    return private_response(document_metadata(source) if model is TechnicalDocument else case_metadata(source))


@api_view(['POST'])
@permission_classes([KnowledgePermission])
@parser_classes([JSONParser])
def knowledge_document_approve(request, document_id):
    return transition_response(request, TechnicalDocument, document_id, 'approve')


@api_view(['POST'])
@permission_classes([KnowledgePermission])
@parser_classes([JSONParser])
def knowledge_document_archive(request, document_id):
    return transition_response(request, TechnicalDocument, document_id, 'archive')


@api_view(['POST'])
@permission_classes([KnowledgePermission])
@parser_classes([JSONParser])
def knowledge_case_approve(request, case_id):
    return transition_response(request, RepairCase, case_id, 'approve')


@api_view(['POST'])
@permission_classes([KnowledgePermission])
@parser_classes([JSONParser])
def knowledge_case_archive(request, case_id):
    return transition_response(request, RepairCase, case_id, 'archive')
