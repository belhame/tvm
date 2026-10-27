import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.db import connection, transaction
from django.db.models import Count, F, Q
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework import serializers
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import AuditLog, Client, Contract, DeliveryNote, Equipment, Intervention, LoginAttempt, Part, ServiceRequest, StockMovement, Warranty
from .pdf import intervention_report
from .permissions import AdminAccountsPermission, BusinessPermission, InternalPermission, ManagerPermission
from .serial_numbers import analyze_serial_number
from .serializers import AuditSerializer, ClientSerializer, ContractSerializer, DeliveryNoteSerializer, EquipmentSerializer, InterventionSerializer, PartSerializer, ServiceRequestSerializer, StaffSerializer, StockMovementSerializer, UserSerializer, WarrantySerializer
from .workflow import CATEGORIES, overdue_filter
from .workflow_api import timeline_response
from .request_numbering import reference_query_value
from .preventive_visits import with_preventive_counts
from .exchange_workflow import exchange_related, workflow_permission_hints
from .disposition_workflow import disposition_related

User = get_user_model()


def user_payload(user):
    return {'id': user.pk, 'username': user.username, 'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email, 'role': user.effective_role, 'courier_kind': user.courier_kind, 'client': user.client_id, 'can_validate_billing': user.can_validate_billing}


@ensure_csrf_cookie
def session_view(request):
    if request.method != 'GET':
        return JsonResponse({'detail': 'Méthode non autorisée.'}, status=405)
    return JsonResponse({'user': user_payload(request.user) if request.user.is_authenticated else None, 'csrfToken': get_token(request), 'demo_mode': settings.TVM_DEMO_MODE})


@csrf_protect
def login_view(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Méthode non autorisée.'}, status=405)
    try:
        body = json.loads(request.body)
        username = body.get('username', '')
        password = body.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 150 or len(password) > 1024:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'detail': 'Corps JSON invalide.'}, status=400)
    now = timezone.now()
    keys = [(f'user:{username.strip().lower()}', 10), (f'ip:{request.META.get("REMOTE_ADDR", "unknown")}', 30)]
    with transaction.atomic():
        attempts = []
        for raw, limit in sorted(keys):
            key = hashlib.sha256(raw.encode()).hexdigest()
            LoginAttempt.objects.get_or_create(identifier=key)
            row = LoginAttempt.objects.select_for_update().get(identifier=key)
            if row.window_start < now - timedelta(minutes=15):
                row.window_start = now
                row.failures = 0
            if row.failures >= limit:
                response = JsonResponse({'detail': 'Trop de tentatives. Réessayez dans 15 minutes.'}, status=429)
                response['Retry-After'] = '900'
                return response
            attempts.append(row)
        user = authenticate(request, username=username, password=password)
        if user is None:
            for row in attempts:
                row.failures += 1
                row.save(update_fields=['window_start', 'failures'])
            return JsonResponse({'detail': 'Identifiant ou mot de passe incorrect.'}, status=400)
        # Le compteur de compte est remis à zéro, celui de l’adresse reste partagé.
        user_key = hashlib.sha256(f'user:{username.strip().lower()}'.encode()).hexdigest()
        LoginAttempt.objects.filter(identifier=user_key).update(failures=0, window_start=now)
        login(request, user)
        AuditLog.objects.create(actor=user, action='login', resource='session', resource_id=str(user.pk))
    return JsonResponse({'user': user_payload(user), 'csrfToken': get_token(request)})


@csrf_protect
def logout_view(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Méthode non autorisée.'}, status=405)
    logout(request)
    return JsonResponse({'detail': 'Déconnecté.'})


def health_view(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return JsonResponse({'status': 'ok', 'database': 'ok'})
    except Exception:
        return JsonResponse({'status': 'unavailable'}, status=503)


def scope_queryset(qs, user, owner_path):
    if user.effective_role == 'client':
        if not user.client_id:
            return qs.none()
        return qs.filter(**{owner_path: user.client_id})
    return qs


class BusinessViewSet(viewsets.ModelViewSet):
    permission_classes = [BusinessPermission]
    owner_path = None
    def get_queryset(self):
        return scope_queryset(super().get_queryset(), self.request.user, self.owner_path)
    def audit(self, instance, action_name):
        AuditLog.objects.create(actor=self.request.user, action=action_name, resource=instance._meta.model_name, resource_id=str(instance.pk))
    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        self.audit(instance, 'create')
    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        self.audit(instance, 'update')
    @transaction.atomic
    def perform_destroy(self, instance):
        self.audit(instance, 'delete')
        instance.delete()


class ClientViewSet(BusinessViewSet):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer
    owner_path = 'id'
    def get_queryset(self):
        qs = super().get_queryset().select_related('default_courier', 'internal_courier').annotate(
            equipment_count=Count('equipment', distinct=True),
            open_requests_count=Count('equipment__service_requests', filter=~Q(equipment__service_requests__status='closed'), distinct=True),
            portal_users_count=Count('portal_users', filter=Q(portal_users__is_active=True, portal_users__role='client'), distinct=True),
        )
        query = reference_query_value(self.request.query_params, 'q')
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(contact_name__icontains=query) | Q(tax_id__icontains=query) | Q(email__icontains=query) | Q(phone__icontains=query) | Q(city__icontains=query))
        return qs


class EquipmentViewSet(BusinessViewSet):
    queryset = Equipment.objects.select_related('client').all()
    serializer_class = EquipmentSerializer
    owner_path = 'client_id'
    def get_queryset(self):
        qs = super().get_queryset()
        serial = self.request.query_params.get('serial')
        client = self.request.query_params.get('client')
        if serial:
            qs = qs.filter(serial_number__iexact=serial.strip())
        if client:
            try:
                qs = qs.filter(client_id=int(client))
            except ValueError:
                raise ValidationError({'client': 'Identifiant invalide.'})
        return qs
    @action(detail=True, methods=['get', 'post'], permission_classes=[IsAuthenticated])
    def timeline(self, request, pk=None):
        return timeline_response(request, equipment=self.get_object())


class ServiceRequestViewSet(BusinessViewSet):
    queryset = disposition_related(exchange_related(with_preventive_counts(ServiceRequest.objects.select_related('equipment__client', 'assigned_technician').all())))
    serializer_class = ServiceRequestSerializer
    owner_path = 'equipment__client_id'
    def get_queryset(self):
        qs = workflow_permission_hints(super().get_queryset(), self.request.user)
        params = self.request.query_params
        for field, lookup in [('equipment', 'equipment_id'), ('client', 'equipment__client_id'), ('assigned_technician', 'assigned_technician_id')]:
            value = params.get(field)
            if value:
                if not value.isascii() or not value.isdecimal() or len(value) > 19:
                    raise ValidationError({field: 'Identifiant invalide.'})
                qs = qs.filter(**{lookup: int(value)})
        query = reference_query_value(params, 'q')
        if query:
            qs = qs.filter(Q(reference__icontains=query) | Q(client_reference__icontains=query) | Q(subject__icontains=query) | Q(equipment__serial_number__icontains=query) | Q(equipment__client__name__icontains=query))
        for key, lookup in [('call_number', 'reference__icontains'), ('client_reference', 'client_reference__icontains')]:
            value = reference_query_value(params, key)
            if value:
                qs = qs.filter(**{lookup: value})
        state = params.get('status')
        if state:
            if state not in ServiceRequest.Status.values:
                raise ValidationError({'status': 'État inconnu.'})
            qs = qs.filter(status=state)
        category = params.get('category', 'all')
        if category not in {item[0] for item in CATEGORIES}:
            raise ValidationError({'category': 'Sous-catégorie inconnue.'})
        if getattr(self, 'action', '') != 'categories':
            if category == 'overdue':
                qs = qs.filter(overdue_filter(qs))
            elif category != 'all':
                states = next(item[2] for item in CATEGORIES if item[0] == category)
                qs = qs.filter(status__in=states)
        return qs
    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save(requested_by=self.request.user)
        self.audit(instance, 'create')
    @action(detail=False, methods=['get'])
    def categories(self, request):
        qs = self.get_queryset()
        counts = dict(qs.values('status').annotate(total=Count('id', distinct=True)).values_list('status', 'total'))
        total = sum(counts.values())
        items = []
        for key, label, states in CATEGORIES:
            count = total if key == 'all' else (qs.filter(overdue_filter(qs)).count() if key == 'overdue' else sum(counts.get(state, 0) for state in states))
            items.append({'key': key, 'label': label, 'count': count})
        return Response({'categories': items, 'total': total, 'as_of': timezone.localdate().isoformat()})
    @action(detail=True, methods=['get', 'post'], permission_classes=[IsAuthenticated])
    def timeline(self, request, pk=None):
        return timeline_response(request, service_request=self.get_object())
    @action(detail=True, methods=['get'])
    def report(self, request, pk=None):
        from .pdf import service_request_report
        instance = self.get_object()
        response = HttpResponse(service_request_report(instance, for_client=request.user.effective_role == 'client'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Rapport-suivi-{instance.reference}.pdf"'
        response['Cache-Control'] = 'private, no-store'
        self.audit(instance, 'download_report')
        return response


class InterventionViewSet(BusinessViewSet):
    queryset = with_preventive_counts(Intervention.objects.select_related('service_request__equipment__client', 'technician').all(), 'service_request__interventions')
    serializer_class = InterventionSerializer
    owner_path = 'service_request__equipment__client_id'
    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        query = reference_query_value(params, 'q')
        if query:
            qs = qs.filter(Q(reference__icontains=query) | Q(service_request__reference__icontains=query) | Q(service_request__client_reference__icontains=query) | Q(service_request__subject__icontains=query) | Q(service_request__equipment__serial_number__icontains=query) | Q(service_request__equipment__client__name__icontains=query))
        for key, lookup in [('call_number', 'service_request__reference__icontains'), ('client_reference', 'service_request__client_reference__icontains')]:
            value = reference_query_value(params, key)
            if value:
                qs = qs.filter(**{lookup: value})
        kind = self.request.query_params.get('kind')
        if kind:
            if kind not in Intervention.Kind.values:
                raise ValidationError({'kind': 'Type d’intervention inconnu.'})
            qs = qs.filter(kind=kind)
        return qs
    @action(detail=True, methods=['get'])
    def report(self, request, pk=None):
        instance = self.get_object()
        response = HttpResponse(intervention_report(instance, for_client=request.user.effective_role == 'client'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Rapport-{instance.reference}.pdf"'
        response['Cache-Control'] = 'private, no-store'
        self.audit(instance, 'download_report')
        return response
    @action(detail=True, methods=['post'], url_path='use-part')
    def use_part(self, request, pk=None):
        instance = self.get_object()
        if request.user.effective_role == 'client':
            raise PermissionDenied()
        quantity = serializers.IntegerField(min_value=1, max_value=1000000).run_validation(request.data.get('quantity'))
        serializer = StockMovementSerializer(data={'part': request.data.get('part'), 'quantity': -quantity, 'kind': 'out', 'reference': instance.reference, 'intervention': instance.pk}, context={'request': request})
        serializer.is_valid(raise_exception=True)
        movement = serializer.save()
        self.audit(movement, 'create')
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UserViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminAccountsPermission]
    queryset = User.objects.all().order_by('first_name', 'id')
    def get_serializer_class(self):
        return UserSerializer if self.request.user.effective_role == 'admin' else StaffSerializer
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.effective_role != 'admin':
            qs = qs.filter(is_active=True).exclude(role='client')
        return qs
    def perform_create(self, serializer):
        instance = serializer.save()
        AuditLog.objects.create(actor=self.request.user, action='create', resource='user', resource_id=str(instance.pk))
    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.pk == self.request.user.pk and 'password' in serializer.validated_data:
            update_session_auth_hash(self.request, instance)
        AuditLog.objects.create(actor=self.request.user, action='update', resource='user', resource_id=str(instance.pk))
    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise ValidationError('Vous ne pouvez pas supprimer votre propre compte.')
        if instance.effective_role == 'admin' and not User.objects.filter(is_active=True).filter(Q(role='admin') | Q(is_superuser=True)).exclude(pk=instance.pk).exists():
            raise ValidationError('Le dernier administrateur actif doit être conservé.')
        pk = instance.pk
        instance.delete()
        AuditLog.objects.create(actor=self.request.user, action='delete', resource='user', resource_id=str(pk))


class PartViewSet(BusinessViewSet):
    permission_classes = [InternalPermission, BusinessPermission]
    queryset = Part.objects.all()
    serializer_class = PartSerializer


class StockPermission(InternalPermission):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.method in ('GET', 'HEAD', 'OPTIONS', 'POST')


class StockMovementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = [StockPermission]
    queryset = StockMovement.objects.select_related('part', 'intervention').all()
    serializer_class = StockMovementSerializer
    def perform_create(self, serializer):
        instance = serializer.save()
        AuditLog.objects.create(actor=self.request.user, action='create', resource='stockmovement', resource_id=str(instance.pk))


class ContractViewSet(BusinessViewSet):
    queryset = Contract.objects.select_related('client', 'equipment').all()
    serializer_class = ContractSerializer
    owner_path = 'client_id'


class WarrantyViewSet(BusinessViewSet):
    queryset = Warranty.objects.select_related('equipment__client').all()
    serializer_class = WarrantySerializer
    owner_path = 'equipment__client_id'


class DeliveryNoteViewSet(BusinessViewSet):
    queryset = DeliveryNote.objects.select_related('client', 'intervention__service_request__equipment').prefetch_related('lines').all()
    serializer_class = DeliveryNoteSerializer
    owner_path = 'client_id'


class AuditViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related('actor').all()
    serializer_class = AuditSerializer
    permission_classes = [ManagerPermission]
    def list(self, request, *args, **kwargs):
        return Response(self.get_serializer(self.get_queryset()[:500], many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_view(request):
    user = request.user
    interventions = scope_queryset(Intervention.objects.select_related('service_request__equipment__client', 'technician'), user, 'service_request__equipment__client_id')
    requests = scope_queryset(ServiceRequest.objects.all(), user, 'equipment__client_id')
    equipment = scope_queryset(Equipment.objects.all(), user, 'client_id')
    clients = scope_queryset(Client.objects.all(), user, 'id')
    critical = Part.objects.filter(stock_quantity__lte=F('min_stock')).count() if user.effective_role != 'client' else None
    metrics = {
        'active_interventions': interventions.exclude(status__in=['completed', 'cancelled']).count(),
        'open_requests': requests.exclude(status__in=['resolved', 'rejected', 'closed']).count(),
        'critical_stock': critical,
        'equipment_count': equipment.count(), 'client_count': clients.count(),
        'completed_interventions': interventions.filter(status='completed').count(),
    }
    today = timezone.localdate()
    first_day = today - timedelta(days=29)
    intervention_counts = {row['created_at__date']: row['count'] for row in interventions.filter(created_at__date__gte=first_day).values('created_at__date').annotate(count=Count('id')).order_by()}
    request_counts = {row['created_at__date']: row['count'] for row in requests.filter(created_at__date__gte=first_day).values('created_at__date').annotate(count=Count('id')).order_by()}
    activity = []
    for offset in range(29, -1, -1):
        day = today - timedelta(days=offset)
        activity.append({'label': day.strftime('%d/%m'), 'interventions': intervention_counts.get(day, 0), 'requests': request_counts.get(day, 0)})
    distribution = [{'name': row['status'], 'value': row['count']} for row in interventions.values('status').annotate(count=Count('id')).order_by('status')]
    serializer_context = {'request': request}
    upcoming = interventions.filter(status__in=['scheduled', 'in_progress', 'testing'], scheduled_at__isnull=False).order_by('scheduled_at')[:8]
    return Response({'metrics': metrics, 'recent_interventions': InterventionSerializer(interventions.order_by('-created_at')[:8], many=True, context=serializer_context).data, 'activity': activity, 'status_distribution': distribution, 'upcoming': InterventionSerializer(upcoming, many=True, context=serializer_context).data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_view(request):
    q = reference_query_value(request.query_params, 'q')
    if not q:
        return Response({'equipment': [], 'clients': [], 'requests': [], 'interventions': []})
    user = request.user
    if len(q) == 1:
        requests = scope_queryset(ServiceRequest.objects.select_related('equipment__client'), user, 'equipment__client_id').filter(Q(reference__iexact=q) | Q(client_reference__iexact=q))[:20]
        interventions = scope_queryset(Intervention.objects.select_related('service_request__equipment__client', 'technician'), user, 'service_request__equipment__client_id').filter(Q(reference__iexact=q) | Q(service_request__reference__iexact=q) | Q(service_request__client_reference__iexact=q))[:20]
        ctx = {'request': request}
        return Response({'equipment': [], 'clients': [], 'requests': ServiceRequestSerializer(requests, many=True, context=ctx).data, 'interventions': InterventionSerializer(interventions, many=True, context=ctx).data})
    equipment = scope_queryset(Equipment.objects.select_related('client'), user, 'client_id').filter(Q(serial_number__icontains=q) | Q(model__icontains=q) | Q(client__name__icontains=q))[:20]
    clients = scope_queryset(Client.objects.all(), user, 'id').filter(Q(name__icontains=q) | Q(contact_name__icontains=q) | Q(tax_id__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q) | Q(city__icontains=q))[:20]
    requests = scope_queryset(ServiceRequest.objects.select_related('equipment__client'), user, 'equipment__client_id').filter(Q(reference__icontains=q) | Q(client_reference__icontains=q) | Q(subject__icontains=q) | Q(equipment__serial_number__icontains=q) | Q(equipment__client__name__icontains=q))[:20]
    interventions = scope_queryset(Intervention.objects.select_related('service_request__equipment__client', 'technician'), user, 'service_request__equipment__client_id').filter(Q(reference__icontains=q) | Q(service_request__reference__icontains=q) | Q(service_request__client_reference__icontains=q) | Q(service_request__subject__icontains=q) | Q(service_request__equipment__serial_number__icontains=q) | Q(service_request__equipment__client__name__icontains=q))[:20]
    ctx = {'request': request}
    return Response({'equipment': EquipmentSerializer(equipment, many=True, context=ctx).data, 'clients': ClientSerializer(clients, many=True, context=ctx).data, 'requests': ServiceRequestSerializer(requests, many=True, context=ctx).data, 'interventions': InterventionSerializer(interventions, many=True, context=ctx).data})


@api_view(['GET'])
@permission_classes([InternalPermission])
def integrations_view(request):
    from .outbox_service import channel_status
    whatsapp = channel_status('whatsapp')
    email = channel_status('email')
    return Response({
        'whatsapp': {**whatsapp, 'message': 'Les messages de collecte et de livraison visent le responsable du centre client, selon sa préférence. Configurez et activez WhatsApp Business pour permettre les envois ; leur acceptation réelle se consulte dans le journal. Le rappel personnel de 08:00 reste dans TVM.', 'requirements': ['Compte Meta WhatsApp Business et numéro validé', 'Jeton API et identifiant du numéro dans la configuration privée', 'Modèle approuvé et notifications activées pour le client']},
        'email': {**email, 'message': 'Notifications au responsable du centre via le serveur SMTP configuré et la préférence du client. Le journal distingue les messages en attente, bloqués ou acceptés par le serveur.'},
        'ai': {'configured': False, 'operational': False, 'status': 'requires_credentials', 'message': 'Assistant non connecté. Aucune réponse de diagnostic n’est simulée et aucun dossier n’est transmis à un fournisseur.', 'requirements': ['Fournisseur et modèle IA approuvés', 'Clé API fournie par canal sécurisé', 'Politique de conservation, localisation et traitement des données', 'Recherche filtrée selon les droits de l’utilisateur et audit des accès']},
        'scanner': {'operational': True, 'requires_https': True, 'message': 'Recherche par numéro de série opérationnelle. Le scan caméra nécessite HTTPS et une caméra autorisée ; prise en charge selon navigateur, saisie manuelle disponible.'},
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def serial_analysis_view(request):
    """Analyse consultative ; aucune recherche dans le parc ni écriture métier."""
    value = request.data.get('serial_number') if isinstance(request.data, dict) else None
    if not isinstance(value, str):
        raise ValidationError({'serial_number': 'Une chaîne de caractères est obligatoire.'})
    if not value.strip():
        raise ValidationError({'serial_number': 'Indiquez un numéro de série.'})
    if len(value) > 120:
        raise ValidationError({'serial_number': '120 caractères maximum.'})
    return Response(analyze_serial_number(value))


def api_not_found(request, *args, **kwargs):
    return JsonResponse({'detail': 'Route API introuvable.'}, status=404)


def csrf_failure(request, reason=''):
    return JsonResponse({'detail': 'Validation CSRF impossible. Rechargez la page puis réessayez.'}, status=403)


def spa_view(request, path=''):
    if request.method not in ('GET', 'HEAD'):
        return JsonResponse({'detail': 'Méthode non autorisée.'}, status=405)
    index = settings.FRONTEND_DIST / 'index.html'
    if not index.is_file():
        return HttpResponse('Interface non compilée. Dans frontend : npm ci puis npm run build. API disponible sous /api/.', status=503, content_type='text/plain; charset=utf-8')
    response = HttpResponse(index.read_bytes(), content_type='text/html; charset=utf-8')
    response['Cache-Control'] = 'no-cache'
    return response
