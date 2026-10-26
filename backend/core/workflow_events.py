from contextvars import ContextVar


_request_context = ContextVar('workflow_request', default=None)


class WorkflowActorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request_context.set(request)
        try:
            return self.get_response(request)
        finally:
            _request_context.reset(token)


def current_actor():
    request = _request_context.get()
    actor = getattr(request, 'user', None)
    return actor if actor and actor.is_authenticated else None


def append_event(*, equipment, service_request=None, intervention=None, actor=None, **fields):
    from .models import OperationEvent
    actor = actor or current_actor()
    return OperationEvent.objects.create(
        equipment=equipment, service_request=service_request, intervention=intervention,
        actor=actor, actor_label=((actor.get_full_name() or actor.username) if actor else 'Système'),
        **fields,
    )
