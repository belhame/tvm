"""Current, revisioned SAV assignments and explicit acceptance."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from .workflow_events import actor_context, append_event, current_actor


MAX_REVISION = 9_223_372_036_854_775_807
ASSIGNMENT_FIELDS = {'assignment_revision', 'assigned_at', 'assignment_accepted_at',
                     'assignment_accepted_by_id', 'assignment_accepted_revision'}
_CONFIRMATION_TOKEN = object()
_SELF_ASSIGNMENT_TOKEN = object()


class AssignmentConflict(APIException):
    status_code = 409
    default_detail = 'L’affectation a changé. Rechargez le dossier avant de confirmer ou de réaffecter.'


def _expected_revision(value):
    if type(value) is not int or not 0 <= value <= MAX_REVISION:
        raise ValidationError({'expected_revision': 'Une révision entière positive ou nulle est obligatoire.'})
    return value


def _reason(value):
    if not isinstance(value, str) or len(value) > 2000 or '\x00' in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValidationError({'reason': 'Le motif doit être un texte valide de 2 000 caractères au maximum.'})
    return value.strip()


def _locked_users(*identifiers):
    User = get_user_model()
    return {user.pk: user for user in User.objects.select_for_update().filter(pk__in={pk for pk in identifiers if pk}).order_by('pk')}


def _internal(actor):
    if actor is None or not actor.is_active or actor.role in ('client', 'courier') or actor.effective_role not in ('admin', 'manager', 'technician'):
        raise PermissionDenied('Cette opération est réservée aux utilisateurs internes actifs.')
    return actor


def _fresh_actor(actor, *, lock=False):
    User = get_user_model()
    query = User.objects.select_for_update() if lock else User.objects.all()
    fresh = query.filter(pk=getattr(actor, 'pk', None)).first()
    return _internal(fresh)


def require_internal_actor(actor):
    """Re-read an internal actor, locking it within a mutation transaction."""
    return _fresh_actor(actor, lock=transaction.get_connection().in_atomic_block)


def _display(user):
    return (user.get_full_name() or user.username) if user else 'Non affecté'


def _target_user(user):
    if user is None or not user.is_active or user.role in ('client', 'courier') or user.effective_role not in ('admin', 'manager', 'technician'):
        raise ValidationError({'technician': 'Choisissez un utilisateur interne actif.'})
    return user


def assignment_is_accepted(record):
    return bool(record.assigned_technician_id and record.assignment_accepted_at
                and record.assignment_accepted_by_id is not None
                and record.assignment_accepted_revision == record.assignment_revision)


def technician_has_accepted_assignment(actor, record):
    """Read-only capability hint; mutation paths must call require_* below.

    The HTTP authentication layer already loaded this actor. Avoid a user
    query per row while rendering lists or workflow capability hints.
    """
    try:
        actor = _internal(actor)
    except PermissionDenied:
        return False
    return bool(actor.effective_role == 'technician' and record.assigned_technician_id == actor.pk and assignment_is_accepted(record))


def require_accepted_assignment(actor, record):
    """Call after locking/re-fetching the request in mutation services."""
    actor = _fresh_actor(actor, lock=transaction.get_connection().in_atomic_block)
    if actor.effective_role in ('admin', 'manager'):
        return actor
    if record.assigned_technician_id != actor.pk or not assignment_is_accepted(record):
        raise PermissionDenied('Confirmez votre affectation courante avant de modifier le suivi SAV.')
    return actor


def assignment_payload(record, actor):
    assigned = record.assigned_technician
    accepted = assignment_is_accepted(record)
    try:
        fresh = _internal(actor)
    except PermissionDenied:
        fresh = None
    can_confirm = bool(fresh and assigned and fresh.pk == assigned.pk and not accepted)
    can_write = bool(fresh and (fresh.effective_role in ('admin', 'manager') or
                     (fresh.pk == record.assigned_technician_id and accepted)))
    self_service = bool(fresh and fresh.effective_role == 'technician' and record.status != 'closed')
    accepted_by = record.assignment_accepted_by if record.assignment_accepted_by_id else None
    public_actor = getattr(actor, 'role', None) in ('client', 'courier')
    return {'revision': record.assignment_revision, 'technician': record.assigned_technician_id,
            'technician_name': _display(assigned), 'assigned_at': record.assigned_at.isoformat() if record.assigned_at else None,
            'accepted': accepted, 'accepted_at': record.assignment_accepted_at.isoformat() if record.assignment_accepted_at else None,
            'accepted_by': None if public_actor else record.assignment_accepted_by_id,
            'accepted_by_name': ('Équipe SAV' if public_actor else _display(accepted_by)) if accepted_by else None,
            'can_confirm': can_confirm, 'can_write_followup': can_write,
            'can_claim': bool(self_service and record.assigned_technician_id is None),
            'can_takeover': bool(self_service and record.assigned_technician_id is not None and record.assigned_technician_id != fresh.pk)}


def prepare_assignment_save(instance, update_fields=None):
    """Model save hook: every assignment path invalidates old acceptance."""
    from .models import ServiceRequest
    old = ServiceRequest.objects.select_for_update().filter(pk=instance.pk).first() if instance.pk and not instance._state.adding else None
    assignment_written = update_fields is None or bool({'assigned_technician', 'assigned_technician_id'} & set(update_fields))
    previous_id = old.assigned_technician_id if old else None
    target_id = instance.assigned_technician_id if assignment_written else previous_id
    changed = target_id != previous_id
    context = {'changed': changed, 'old': old, 'actor': None, 'before_status': old.status if old else '', 'fields': set()}
    if changed:
        actor = getattr(instance, '_assignment_actor', None) or current_actor()
        users = _locked_users(getattr(actor, 'pk', None), target_id)
        if actor is not None:
            actor = _internal(users.get(actor.pk))
            self_service = getattr(instance, '_self_assignment_token', None) is _SELF_ASSIGNMENT_TOKEN
            if self_service:
                if actor.effective_role != 'technician' or target_id != actor.pk or old is None:
                    raise PermissionDenied('La prise en charge personnelle doit viser le technicien connecté.')
                if old.status == 'closed' or old.assignment_revision != getattr(instance, '_self_assignment_revision', None):
                    raise AssignmentConflict()
                mode = getattr(instance, '_self_assignment_mode', None)
                if ((mode == 'claim' and previous_id is not None)
                    or (mode == 'takeover' and (previous_id is None or previous_id == actor.pk))
                    or mode not in ('claim', 'takeover')):
                    raise AssignmentConflict('Le dossier ne correspond plus à la prise en charge demandée.')
            elif actor.effective_role not in ('admin', 'manager'):
                raise PermissionDenied('Le responsable SAV gère les affectations.')
        target = users.get(target_id)
        if target_id and (target is None or not target.is_active or target.role in ('client', 'courier') or target.effective_role not in ('admin', 'manager', 'technician')):
            raise ValidationError({'technician': 'Choisissez un utilisateur interne actif.'})
        revision = old.assignment_revision if old else 0
        if revision >= MAX_REVISION:
            raise ValidationError({'assignment': 'La révision d’affectation a atteint sa limite. Contactez l’administrateur.'})
        instance.assigned_technician_id = target_id
        instance.assignment_revision = revision + 1
        instance.assigned_at = timezone.now() if target_id else None
        instance.assignment_accepted_at = None
        instance.assignment_accepted_by_id = None
        instance.assignment_accepted_revision = None
        instance._state.fields_cache.pop('assigned_technician', None)
        instance._state.fields_cache.pop('assignment_accepted_by', None)
        if target_id and instance.status == 'new':
            instance.status = 'pending'
            context['fields'].add('status')
        context['fields'].update(ASSIGNMENT_FIELDS)
        context['actor'] = actor
    elif old is not None:
        confirming = getattr(instance, '_assignment_confirmation_token', None) is _CONFIRMATION_TOKEN
        for field in ASSIGNMENT_FIELDS:
            is_written = update_fields is None or field in update_fields or field.removesuffix('_id') in update_fields
            if confirming and field in {'assignment_accepted_at', 'assignment_accepted_by_id', 'assignment_accepted_revision'}:
                continue
            if is_written and getattr(instance, field) != getattr(old, field):
                raise AssignmentConflict('Les métadonnées de prise en charge ne peuvent pas être remplacées. Utilisez la confirmation de l’affectation courante.')
            setattr(instance, field, getattr(old, field))
        if not assignment_written:
            instance.assigned_technician_id = old.assigned_technician_id
            instance._state.fields_cache.pop('assigned_technician', None)
    elif any(getattr(instance, field) for field in ASSIGNMENT_FIELDS):
        raise ValidationError({'assignment': 'La prise en charge ne peut pas être préremplie lors de la création.'})
    return context


def finish_assignment_save(instance, context):
    if not context['changed']:
        return
    old = context['old']
    before = _display(old.assigned_technician) if old else 'Non affecté'
    after = _display(instance.assigned_technician)
    immediate = getattr(instance, '_self_assignment_token', None) is _SELF_ASSIGNMENT_TOKEN
    confirmation = 'Prise en charge personnelle confirmée dans la même opération.' if immediate else 'Confirmation de prise en charge requise.'
    append_event(equipment=instance.equipment, service_request=instance, actor=context['actor'],
                 kind='assignment_changed', status_before=context['before_status'], status_after=instance.status,
                 summary=f'Affectation révision {instance.assignment_revision} : {before} → {after}. {confirmation}' if instance.assigned_technician_id else f'Affectation révision {instance.assignment_revision} : {before} → Non affecté.',
                 observation=getattr(instance, '_assignment_reason', ''), is_internal=True)


def _locked_request(request_id):
    from .models import ServiceRequest
    if type(request_id) is not int or request_id < 1 or request_id > MAX_REVISION:
        raise ValidationError({'request': 'Identifiant de dossier invalide.'})
    record = ServiceRequest.objects.select_for_update().filter(pk=request_id).first()
    if record is None:
        raise NotFound('Dossier SAV introuvable.')
    return record


@transaction.atomic
def assign_request(request_id, *, actor, technician_id, expected_revision, reason=''):
    expected_revision = _expected_revision(expected_revision)
    reason = _reason(reason)
    if technician_id is not None and (type(technician_id) is not int or not 1 <= technician_id <= MAX_REVISION):
        raise ValidationError({'technician': 'Un identifiant entier ou null est requis.'})
    record = _locked_request(request_id)
    users = _locked_users(getattr(actor, 'pk', None), technician_id)
    actor = _internal(users.get(getattr(actor, 'pk', None)))
    if actor.effective_role not in ('admin', 'manager'):
        raise PermissionDenied('Le responsable SAV gère les affectations.')
    if record.assignment_revision != expected_revision:
        raise AssignmentConflict()
    if technician_id:
        _target_user(users.get(technician_id))
    if record.assigned_technician_id == technician_id:
        return record
    record.assigned_technician_id = technician_id
    record._assignment_actor = actor
    record._assignment_reason = reason
    record.save(update_fields=['assigned_technician', 'updated_at'])
    return record


@transaction.atomic
def confirm_assignment(request_id, *, actor, expected_revision, accept, on_behalf=False, reason=''):
    expected_revision = _expected_revision(expected_revision)
    if type(accept) is not bool or type(on_behalf) is not bool:
        raise ValidationError({'accept': 'Utilisez un vrai booléen JSON pour confirmer ou annuler.'})
    reason = _reason(reason)
    record = _locked_request(request_id)
    users = _locked_users(getattr(actor, 'pk', None), record.assigned_technician_id)
    actor = _internal(users.get(getattr(actor, 'pk', None)))
    if record.assignment_revision != expected_revision:
        raise AssignmentConflict()
    if record.assigned_technician_id is None:
        raise ValidationError({'assignment': 'Ce dossier n’est affecté à aucun technicien.'})
    _target_user(users.get(record.assigned_technician_id))
    if on_behalf:
        if actor.effective_role != 'admin':
            raise PermissionDenied('Seul un administrateur peut confirmer au nom du technicien.')
        if accept and not reason:
            raise ValidationError({'reason': 'Expliquez la confirmation au nom du technicien.'})
    elif record.assigned_technician_id != actor.pk:
        raise PermissionDenied('Seul l’utilisateur actuellement affecté peut confirmer sa prise en charge.')
    if not accept or assignment_is_accepted(record):
        return record
    record.assignment_accepted_at = timezone.now()
    record.assignment_accepted_by = actor
    record.assignment_accepted_revision = record.assignment_revision
    record._assignment_confirmation_token = _CONFIRMATION_TOKEN
    try:
        record.save(update_fields=['assignment_accepted_at', 'assignment_accepted_by', 'assignment_accepted_revision', 'updated_at'])
    finally:
        del record._assignment_confirmation_token
    append_event(equipment=record.equipment, service_request=record, actor=actor, kind='assignment_accepted',
                 status_before=record.status, status_after=record.status,
                 summary=f'Prise en charge confirmée pour l’affectation révision {record.assignment_revision} de {_display(record.assigned_technician)}.', is_internal=True)
    if on_behalf:
        append_event(equipment=record.equipment, service_request=record, actor=actor, kind='assignment_override',
                     summary='Confirmation enregistrée par un administrateur au nom du technicien affecté.', observation=reason, is_internal=True)
    return record


@transaction.atomic
def _self_assign_request(request_id, *, actor, expected_revision, mode, reason=''):
    expected_revision = _expected_revision(expected_revision)
    reason = _reason(reason)
    record = _locked_request(request_id)
    actor = _fresh_actor(actor, lock=True)
    if actor.effective_role != 'technician':
        raise PermissionDenied('Cette action personnelle est réservée aux techniciens actifs.')
    if record.assignment_revision != expected_revision:
        raise AssignmentConflict()
    if record.status == 'closed':
        raise AssignmentConflict('Un dossier clôturé ne peut pas être pris en charge. Un responsable peut gérer sa suite selon les règles SAV.')
    previous_id = record.assigned_technician_id
    previous_name = _display(record.assigned_technician)
    if mode == 'claim':
        if previous_id is not None:
            raise AssignmentConflict('Ce dossier est déjà affecté. Rechargez sa fiche avant de reprendre le relais.')
    elif mode == 'takeover':
        if not reason:
            raise ValidationError({'reason': 'Expliquez pourquoi vous reprenez le relais sur ce dossier.'})
        if previous_id is None or previous_id == actor.pk:
            raise AssignmentConflict('La reprise concerne uniquement un dossier affecté à une autre personne.')
    else:
        raise ValidationError('Action de prise en charge inconnue.')
    record.assigned_technician = actor
    record._assignment_actor = actor
    record._assignment_reason = reason
    record._self_assignment_token = _SELF_ASSIGNMENT_TOKEN
    record._self_assignment_revision = expected_revision
    record._self_assignment_mode = mode
    with actor_context(actor):
        try:
            record.save(update_fields=['assigned_technician', 'updated_at'])
        finally:
            del record._self_assignment_token
            del record._self_assignment_revision
            del record._self_assignment_mode
        # Reuse the established acceptance service and its private token; a
        # failure rolls back the assignment, timestamps and all history.
        record = confirm_assignment(record.pk, actor=actor, expected_revision=record.assignment_revision, accept=True)
        append_event(
            equipment=record.equipment, service_request=record, actor=actor,
            kind='assignment_claimed' if mode == 'claim' else 'assignment_taken_over',
            status_before=record.status, status_after=record.status,
            summary=f'Demande prise en charge personnellement par {_display(actor)}.' if mode == 'claim'
                    else f'Relais repris par {_display(actor)} après {previous_name}. Les fiches et auteurs antérieurs sont conservés.',
            is_internal=True,
        )
    return record


def claim_request(request_id, *, actor, expected_revision):
    return _self_assign_request(request_id, actor=actor, expected_revision=expected_revision, mode='claim')


def takeover_request(request_id, *, actor, expected_revision, reason):
    return _self_assign_request(request_id, actor=actor, expected_revision=expected_revision, mode='takeover', reason=reason)
