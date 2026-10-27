"""Exact-model local retrieval, redacted technical requests and cited assistance."""
import hashlib
import json
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, Throttled, ValidationError

from .diagnostic_models import DiagnosticGate, DiagnosticRun
from .diagnostic_provider import DiagnosticProviderError, call_provider
from .knowledge_models import TechnicalDocument, KnowledgeChunk, RepairCase
from .knowledge_service import approved_cases, approved_chunks, case_is_eligible, normalized_key


CAUTION = 'Assistance technique à valider par un professionnel habilité. Consigner et suivre les procédures du fabricant ; ne contourner aucune protection.'
PRIVACY = 'Les filtres retirent les coordonnées et identifiants détectés ; vérifiez les champs libres avant de demander une analyse externe.'
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', re.UNICODE)
PHONE = re.compile(r'(?<![\w.])\+\d[\d ()/.-]{5,}\d(?![\w.])')
LABELLED = re.compile(r'(?im)\b(?:client|contact|adresse|e-?mail|t[eé]l(?:[eé]phone)?|s/?n|num[eé]ro\s+de\s+s[eé]rie|n[°o]\s*(?:appel|dossier))\s*[:=]\s*[^;\n]+')
REFERENCES = re.compile(r'\b(?:(?:INT|SAV|BL|FACT)-[A-Za-z0-9/-]{3,}|\d{2}-\d{5})\b', re.I)
UNSAFE = re.compile(r'(?:contourn(?:er|ez)|shunt(?:er|ez)|court[- ]?circuit(?:er|ez)|neutralis(?:er|ez)|d[eé]sactiv(?:er|ez)|bypass|defeat|disable).{0,55}(?:protect|s[eé]curit|interlock|interverrouillage)', re.I)


class DiagnosticConflict(APIException):
    status_code = 409
    default_detail = 'Cette clé d’analyse correspond à une autre demande.'


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _private_literals(record):
    if not record:
        return []
    client = record.equipment.client
    values = [record.equipment.serial_number, record.reference, record.client_reference, client.name,
              client.contact_name, client.email, client.phone, client.address, client.city, client.postal_code, client.country]
    values += [getattr(record, key, '') for key in ('end_customer', 'contact_name', 'contact_phone', 'contact_email', 'courier_name')]
    return sorted({value.strip() for value in values if isinstance(value, str) and len(value.strip()) >= 3}, key=len, reverse=True)


def redact(text, literals=(), *, remove_phones=True, remove_references=True):
    text = str(text or '')
    for value in literals:
        text = re.sub(re.escape(value), '[information retirée]', text, flags=re.I)
    text = EMAIL.sub('[e-mail retiré]', text)
    if remove_phones:
        text = PHONE.sub(lambda match: '[téléphone retiré]' if sum(c.isdigit() for c in match.group()) >= 7 and
            not re.fullmatch(r'\d{4}[-/]\d{2}[-/]\d{2}', match.group().strip()) else match.group(), text)
    text = LABELLED.sub('[identifiant contextuel retiré]', text)
    return REFERENCES.sub('[référence retirée]', text) if remove_references else text


def redact_identifier(text, literals=()):
    # Long numeric manufacturer references are not phone numbers. Typed lookup
    # identifiers keep their exact spelling; only detected contextual PII is
    # removed here, never an industrial number based solely on its length.
    return redact(text, literals, remove_phones=True, remove_references=False)


def prepare_input(data):
    from .models import ServiceRequest
    record = None
    if data.get('service_request'):
        record = ServiceRequest.objects.select_related('equipment__client').filter(pk=data['service_request']).first()
        if not record:
            raise NotFound('Dossier indisponible.')
    literals = _private_literals(record)
    technical = {key: data.get(key, '') for key in ('symptoms', 'measurements')}
    warnings = [PRIVACY]
    for key, value in list(technical.items()):
        technical[key] = redact(value, literals)
        if technical[key] != value and 'personal_information_redacted' not in warnings:
            warnings.append('personal_information_redacted')
    identifiers = {'brand': record.equipment.brand if record else data.get('brand', 'Eaton'),
                   'model': record.equipment.model if record else data.get('model', ''),
                   'fault_code': data.get('fault_code', ''),
                   'board_reference': data.get('board_reference', ''), 'revision': data.get('revision', '')}
    for field, value in identifiers.items():
        cleaned = redact_identifier(value, literals)
        if cleaned != value:
            raise ValidationError({field: 'Utilisez un identifiant technique sans coordonnées ni référence client.'})
        technical[field] = value
    if not normalized_key(technical['model']) or not normalized_key(technical['brand']):
        raise ValidationError({'model': 'Le modèle et la marque exacts doivent être renseignés.'})
    if record:
        warnings.append('equipment_brand_model_from_record')
    return technical, record, literals, warnings


def _tokens(text):
    return {part for part in re.findall(r'[\w]+(?:[-_/][\w]+)*', normalized_key(text)) if len(part) > 1 and part not in
            {'les', 'des', 'une', 'pour', 'avec', 'dans', 'sur', 'the', 'and', 'information', 'retiree', 'retire', 'identifiant', 'contextuel', 'email', 'telephone'}}


def _score(text, technical):
    value = normalized_key(text)
    tokens = _tokens(text)
    score = len(tokens & _tokens(technical['symptoms'])) * 3 + len(tokens & _tokens(technical['measurements']))
    code = normalized_key(technical['fault_code'])
    if code and re.search(r'(?<!\w)' + re.escape(code) + r'(?!\w)', value):
        score += 20
    return score


def _metadata_allowed(source, technical, *, generic_manual=False):
    board, revision = normalized_key(technical['board_reference']), normalized_key(technical['revision'])
    source_board = source.board_reference_key
    if board and source_board != board and not (generic_manual and not source_board):
        return False
    if revision and normalized_key(source.revision) != revision and not (generic_manual and not source_board):
        return False
    return True


def _document_source(chunk, literals):
    document = chunk.document
    return {'id': f'D{document.pk}-P{chunk.page}-C{chunk.ordinal}', 'kind': 'document',
        'document_id': document.pk, 'case_id': None, 'title': redact(document.title, literals),
        'brand': redact_identifier(document.brand, literals), 'model': redact_identifier(document.model, literals), 'board_reference': redact_identifier(document.board_reference, literals),
        'revision': redact_identifier(document.revision, literals), 'page': chunk.page, 'excerpt': redact(chunk.text, literals)[:1800]}


def _case_source(case, literals):
    own_literals = _private_literals(case.intervention.service_request)
    parts = [f'{label}: {(redact_identifier if key == "fault_code" else redact)(getattr(case, key), [*literals, *own_literals])[:250]}' for key, label in (
        ('symptoms', 'Symptômes'), ('fault_code', 'Code défaut'), ('measurements', 'Mesures'),
        ('confirmed_cause', 'Cause confirmée'), ('repair', 'Réparation'), ('outcome', 'Résultat'))]
    all_literals = [*literals, *own_literals]
    return {'id': f'R{case.pk}', 'kind': 'case', 'document_id': None, 'case_id': case.pk,
        'title': f'Cas de réparation approuvé {case.pk}', 'brand': case.brand, 'model': case.model,
        'board_reference': redact_identifier(case.board_reference, all_literals), 'revision': redact_identifier(case.revision, all_literals), 'page': None, 'excerpt': '\n'.join(parts)[:1800]}


def retrieve_sources(technical, literals=()):
    ranked = []
    for chunk in approved_chunks(brand=technical['brand'], model=technical['model']).iterator(chunk_size=100):
        if not _metadata_allowed(chunk.document, technical, generic_manual=chunk.document.kind == 'manual'):
            continue
        source = _document_source(chunk, literals)
        score = _score(source['excerpt'], technical)
        if score:
            ranked.append((score, source))
    cases = approved_cases(brand=technical['brand'], model=technical['model']).select_related('intervention__service_request__equipment__client')
    for case in cases.iterator(chunk_size=100):
        if not _metadata_allowed(case, technical):
            continue
        source = _case_source(case, literals)
        score = _score(source['excerpt'], technical)
        if score:
            ranked.append((score, source))
    ranked.sort(key=lambda entry: (-entry[0], entry[1]['id']))
    return [source for _, source in ranked[:6]]


def source_warnings(sources, technical):
    warnings = []
    if not technical['board_reference'] and any(source['board_reference'] for source in sources):
        warnings.append('board_reference_requires_confirmation')
    if not technical['revision'] and any(source['revision'] for source in sources):
        warnings.append('revision_requires_confirmation')
    if any(not source['board_reference'] for source in sources):
        warnings.append('generic_source_verify_board_and_revision_before_procedure')
    if technical['revision'] and any(not source['board_reference'] and normalized_key(source['revision']) != normalized_key(technical['revision']) for source in sources):
        warnings.append('generic_manual_revision_differs_verify_applicability')
    return warnings


def search(data):
    technical, record, literals, warnings = prepare_input(data)
    sources = retrieve_sources(technical, literals)
    return {'status': 'sources_found' if sources else 'no_sources', 'input': technical, 'sources': sources,
            'warnings': [*warnings, *source_warnings(sources, technical), CAUTION]}


def _configuration():
    enabled = bool(getattr(settings, 'TVM_AI_ENABLED', False))
    model = getattr(settings, 'TVM_AI_MODEL', 'gpt-4.1-mini')
    model_valid = isinstance(model, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', model)
    key = getattr(settings, 'TVM_AI_API_KEY', '')
    key_valid = isinstance(key, str) and 1 <= len(key.strip()) <= 4096 and all(32 < ord(character) < 127 for character in key.strip())
    return enabled, bool(model_valid and key_valid), model if model_valid else ''


def diagnostic_status():
    enabled, configured, model = _configuration()
    cases = RepairCase.objects.filter(state='approved', intervention__status='completed').select_related('intervention__service_request__equipment')
    return {'enabled': enabled, 'configured': configured, 'operational': enabled and configured,
        'configuration_only': True, 'provider': 'openai_responses', 'model': model,
        'library': {'documents': TechnicalDocument.objects.filter(state='approved').count(),
                    'passages': KnowledgeChunk.objects.filter(document__state='approved', document__text_status__in=['extracted', 'partial']).count(),
                    'cases': sum(case_is_eligible(case) for case in cases)},
        'message': 'Configuration prête à tenter une analyse, sans test du fournisseur.' if enabled and configured else 'Analyse externe désactivée ou non configurée. Recherche locale disponible.'}


def _checked_text(value, limit, literals):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value or any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError('invalid_text')
    unsafe = any(not re.search(r'(?:ne\s+pas|ne\s+jamais|jamais|do not|never)\s*$', value[max(0, match.start()-30):match.start()], re.I) for match in UNSAFE.finditer(value))
    if unsafe or re.search(r'(?:confiance|confidence|probabilit[eé]).{0,35}\d+(?:[.,]\d+)?\s*%', value, re.I):
        raise ValueError('unsafe_or_unfounded_output')
    return redact(value, literals)


def validate_output(output, sources, literals):
    expected = {'summary', 'hypotheses', 'checks', 'missing_information', 'uncertainties'}
    if not isinstance(output, dict) or set(output) != expected:
        raise ValueError('invalid_schema')
    allowed = {source['id'] for source in sources}
    result = {'summary': _checked_text(output['summary'], 4000, literals)}
    for field, keys, maximum in [('hypotheses', {'title', 'explanation', 'source_ids'}, 6), ('checks', {'instructions', 'source_ids'}, 8)]:
        values = output[field]
        if not isinstance(values, list) or len(values) > maximum:
            raise ValueError('invalid_schema')
        result[field] = []
        for item in values:
            if not isinstance(item, dict) or set(item) != keys or not isinstance(item['source_ids'], list) or not 1 <= len(item['source_ids']) <= 6:
                raise ValueError('missing_citations')
            if any(not isinstance(identifier, str) or identifier not in allowed for identifier in item['source_ids']):
                raise ValueError('unknown_citation')
            cleaned = {key: _checked_text(item[key], 200 if key == 'title' else 2000, literals) for key in keys - {'source_ids'}}
            if any(not value.strip() for value in cleaned.values()):
                raise ValueError('empty_output')
            if field == 'checks' and re.search(r'(?i)(?:sous tension|energized|\blive\b)', cleaned['instructions']) and not re.search(r'(?i)(?:hors tension|ne pas|jamais|do not|never)', cleaned['instructions']):
                raise ValueError('energized_work_not_allowed')
            result[field].append({**cleaned, 'source_ids': list(dict.fromkeys(item['source_ids']))})
    for field in ('missing_information', 'uncertainties'):
        if not isinstance(output[field], list) or len(output[field]) > 12:
            raise ValueError('invalid_schema')
        result[field] = [_checked_text(item, 1000, literals) for item in output[field]]
    return result


def _current_source(snapshot, technical, literals):
    if snapshot['kind'] == 'document':
        match = re.fullmatch(r'D(\d+)-P(\d+)-C(\d+)', snapshot['id'])
        if not match:
            return None
        chunk = approved_chunks(brand=technical['brand'], model=technical['model']).filter(document_id=match[1], page=match[2], ordinal=match[3]).first()
        if chunk and _metadata_allowed(chunk.document, technical, generic_manual=chunk.document.kind == 'manual'):
            return _document_source(chunk, literals)
    else:
        case = approved_cases(brand=technical['brand'], model=technical['model']).filter(pk=snapshot['case_id']).select_related('intervention__service_request__equipment__client').first()
        if case and _metadata_allowed(case, technical):
            return _case_source(case, literals)
    return None


def _source_availability(run):
    literals = _private_literals(run.service_request) if run.service_request_id else []
    result = []
    for source in run.source_snapshots:
        current = _current_source(source, run.technical_input, literals)
        result.append({**source, 'available': bool(current and current == source)})
    return result


def run_payload(run):
    sources = _source_availability(run)
    warnings = list(run.warnings)
    if any(not source['available'] for source in sources):
        warnings.append('historical_sources_no_longer_current')
    return {'id': run.pk, 'status': run.status, 'created_at': run.created_at, 'finished_at': run.finished_at,
        'service_request': run.service_request_id, 'input': run.technical_input, 'sources': sources,
        'output': run.output, 'warnings': warnings, 'error_code': run.error_code,
        'usage': {'input_tokens': run.input_tokens, 'output_tokens': run.output_tokens},
        'provider': run.provider, 'model': run.provider_model}


@transaction.atomic
def _start(actor, data, technical, record, sources, warnings):
    DiagnosticGate.objects.get_or_create(pk=1)
    DiagnosticGate.objects.select_for_update().get(pk=1)
    fingerprint = _fingerprint({key: value for key, value in data.items() if key != 'request_key'})
    previous = DiagnosticRun.objects.filter(actor=actor, request_key=data['request_key']).first()
    if previous:
        if previous.request_fingerprint != fingerprint:
            raise DiagnosticConflict()
        return previous, False
    now = timezone.now()
    DiagnosticRun.objects.filter(status='running', created_at__lt=now - timedelta(minutes=2)).update(
        status='provider_error', error_code='analysis_interrupted', finished_at=now)
    if DiagnosticRun.objects.filter(actor=actor, created_at__gte=now - timedelta(hours=1)).count() >= 10:
        raise Throttled(wait=3600, detail='Limite de dix analyses par heure atteinte pour ce compte.')
    if DiagnosticRun.objects.filter(status='running').count() >= 2 or DiagnosticRun.objects.filter(actor=actor, status='running').exists():
        raise Throttled(wait=20, detail='Une analyse est déjà en cours. Réessayez après sa fin.')
    enabled, configured, provider_model = _configuration()
    status = 'abstained' if not sources else 'requires_configuration' if not (enabled and configured) else 'running'
    run = DiagnosticRun.objects.create(actor=actor, actor_label=actor.get_full_name() or actor.username,
        service_request=record, request_key=data['request_key'], request_fingerprint=fingerprint, status=status,
        technical_input=technical, source_snapshots=sources, warnings=warnings,
        provider_model=provider_model, finished_at=None if status == 'running' else now)
    return run, True


def analyze(actor, data):
    technical, record, literals, warnings = prepare_input(data)
    sources = retrieve_sources(technical, literals)
    warnings += [*source_warnings(sources, technical), CAUTION]
    run, created = _start(actor, data, technical, record, sources, warnings)
    if not created or run.status != 'running':
        return run
    try:
        response = call_provider(technical, sources)
        output = validate_output(response['output'], sources, literals)
    except DiagnosticProviderError:
        run.status, run.error_code = 'provider_error', 'provider_unavailable'
    except (ValueError, TypeError, KeyError, AttributeError):
        run.status, run.error_code = 'invalid_response', 'unverified_provider_output'
    except Exception:
        run.status, run.error_code = 'provider_error', 'analysis_interrupted'
    else:
        # Sources and a linked model may change during network I/O. Never publish
        # an answer based on a source that is no longer eligible.
        current_literals = literals
        model_changed = False
        if record:
            record.refresh_from_db()
            record._state.fields_cache.pop('equipment', None)
            model_changed = normalized_key(record.equipment.brand) != normalized_key(technical['brand']) or normalized_key(record.equipment.model) != normalized_key(technical['model'])
            current_literals = [*literals, *_private_literals(record)]
        if model_changed or any(_current_source(source, technical, current_literals) != source for source in sources):
            run.status, run.error_code = 'sources_changed', 'source_no_longer_eligible'
        else:
            try:
                run.output = validate_output(output, sources, current_literals)
            except (ValueError, TypeError):
                run.status, run.error_code = 'invalid_response', 'unverified_provider_output'
            else:
                run.status = 'completed'
                usage = response.get('usage', {})
                if isinstance(usage, dict):
                    run.input_tokens = usage.get('input_tokens', 0) if type(usage.get('input_tokens', 0)) is int and 0 <= usage.get('input_tokens', 0) <= 10000000 else 0
                    run.output_tokens = usage.get('output_tokens', 0) if type(usage.get('output_tokens', 0)) is int and 0 <= usage.get('output_tokens', 0) <= 10000000 else 0
    run.finished_at = timezone.now()
    run.save(update_fields=['status', 'error_code', 'output', 'input_tokens', 'output_tokens', 'finished_at'])
    return run
