import secrets

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils import timezone


class LegacyModel(models.Model):
    legacy_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    class Meta:
        abstract = True


class Client(LegacyModel):
    name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=80, default='France')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['name', 'id']
    def __str__(self):
        return self.name


class PowerCareUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Administrateur'
        MANAGER = 'manager', 'Responsable SAV'
        TECHNICIAN = 'technician', 'Technicien'
        CLIENT = 'client', 'Client'
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TECHNICIAN)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name='portal_users')
    legacy_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    objects = PowerCareUserManager()
    class Meta:
        constraints = [models.CheckConstraint(condition=(models.Q(role='client', client__isnull=False) | (~models.Q(role='client') & models.Q(client__isnull=True))), name='user_client_role_consistent')]
    @property
    def effective_role(self):
        return 'admin' if self.is_superuser else self.role


class Equipment(LegacyModel):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'En service'
        MAINTENANCE = 'maintenance', 'En maintenance'
        INACTIVE = 'inactive', 'Hors service'
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='equipment')
    serial_number = models.CharField(max_length=120)
    brand = models.CharField(max_length=100, default='Eaton')
    model = models.CharField(max_length=120)
    power_kva = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    location = models.CharField(max_length=250, blank=True)
    commissioned_on = models.DateField(null=True, blank=True)
    manufactured_on = models.DateField(null=True, blank=True)
    catalogue_product = models.ForeignKey('core.CatalogueProduct', on_delete=models.SET_NULL, null=True, blank=True, related_name='equipment')
    warranty_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-id']
        constraints = [models.UniqueConstraint(Lower('serial_number'), name='equipment_serial_case_unique'), models.CheckConstraint(condition=models.Q(power_kva__gte=0), name='equipment_power_nonnegative')]
    def __str__(self):
        return f'{self.model} · {self.serial_number}'


class ReferencedModel(LegacyModel):
    reference = models.CharField(max_length=40, unique=True, blank=True)
    reference_prefix = 'REF'
    class Meta:
        abstract = True
    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f'{self.reference_prefix}-{timezone.localdate():%Y}-{secrets.token_hex(4).upper()}'
        return super().save(*args, **kwargs)


class RequestNumberSequence(models.Model):
    year = models.PositiveSmallIntegerField(primary_key=True)
    last_value = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(last_value__lte=99999), name='request_number_sequence_maximum')]


class ServiceRequest(ReferencedModel):
    class ServiceLocation(models.TextChoices):
        UNKNOWN = '', 'Non renseigné'
        WORKSHOP = 'workshop', 'Atelier'
        DEPOT = 'depot', 'Dépôt'
        ONSITE = 'onsite', 'Sur site'
    class DeliveredBy(models.TextChoices):
        UNKNOWN = '', 'Non renseigné'
        COURIER = 'courier', 'Transporteur'
        CLIENT = 'client', 'Client'
    class WarrantyStatus(models.TextChoices):
        UNSPECIFIED = 'unspecified', 'À vérifier'
        WARRANTY = 'warranty', 'Garantie'
        QUOTATION = 'quotation', 'Devis'
        CONTRACT = 'contract', 'Contrat'
        BILLABLE = 'billable', 'Hors garantie / facturable'
    class Priority(models.TextChoices):
        LOW = 'low', 'Basse'
        NORMAL = 'normal', 'Normale'
        HIGH = 'high', 'Haute'
        URGENT = 'urgent', 'Urgente'
    class Status(models.TextChoices):
        NEW = 'new', 'Non affecté'
        SCHEDULED = 'scheduled', 'Planifiée'
        IN_PROGRESS = 'in_progress', 'En cours'
        MAINTENANCE = 'maintenance', 'En entretien'
        TESTING = 'testing', 'En test'
        RESOLVED = 'resolved', 'Traité'
        QUOTATION = 'quotation', 'Devis'
        PENDING = 'pending', 'En attente'
        APPROVED = 'approved', 'Validé'
        REJECTED = 'rejected', 'Refusé'
        EXCHANGE = 'exchange', 'Échange'
        CLOSED = 'closed', 'Clôturée'
    reference_prefix = 'SAV'
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name='service_requests')
    subject = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    assigned_technician = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='assigned_requests')
    due_on = models.DateField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    client_reference = models.CharField(max_length=120, blank=True)
    end_customer = models.CharField(max_length=200, blank=True)
    return_flag = models.BooleanField(default=False)
    packaging = models.CharField(max_length=250, blank=True)
    service_location = models.CharField(max_length=20, choices=ServiceLocation.choices, default='', blank=True)
    delivered_by = models.CharField(max_length=20, choices=DeliveredBy.choices, default='', blank=True)
    courier_name = models.CharField(max_length=150, blank=True)
    accessories = models.TextField(blank=True)
    warranty_status = models.CharField(max_length=20, choices=WarrantyStatus.choices, default=WarrantyStatus.UNSPECIFIED)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    contact_email = models.EmailField(blank=True)
    intake_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    intake_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.CheckConstraint(condition=models.Q(closed_at__isnull=True) | models.Q(status='closed'), name='request_closure_status_consistent'),
            models.CheckConstraint(condition=models.Q(closed_at__isnull=True) | models.Q(arrived_at__isnull=True) | models.Q(closed_at__gte=models.F('arrived_at')), name='request_arrival_before_closure'),
        ]
    def __str__(self):
        return self.reference
    @transaction.atomic
    def save(self, *args, **kwargs):
        # The pre-save lifecycle handler must persist its closure timestamp even
        # when a status-only workflow update supplies update_fields.
        if kwargs.get('update_fields'):
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'closed_at'}
        allocated = not self.reference
        if allocated:
            from .request_numbering import next_request_number
            self.reference = next_request_number()
        try:
            return super().save(*args, **kwargs)
        except Exception:
            if allocated:
                self.reference = ''
            raise


class Intervention(ReferencedModel):
    class Kind(models.TextChoices):
        MAINTENANCE = 'maintenance', 'Maintenance'
        EXCHANGE = 'exchange', 'Échange'
        COMMISSIONING = 'commissioning', 'Mise en service'
        PREVENTIVE = 'preventive', 'Maintenance préventive'
    class Conclusion(models.TextChoices):
        UNSPECIFIED = '', 'Non renseignée'
        FOLLOW_UP = 'follow_up', 'À suivre'
        COMPLETED = 'completed', 'Terminée'
        NOT_APPLICABLE_BILLABLE = 'not_applicable_billable', 'Garantie non applicable / à facturer'
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Planifiée'
        IN_PROGRESS = 'in_progress', 'En maintenance'
        TESTING = 'testing', 'En test'
        COMPLETED = 'completed', 'Terminée'
        CANCELLED = 'cancelled', 'Annulée'
    reference_prefix = 'INT'
    service_request = models.ForeignKey(ServiceRequest, on_delete=models.PROTECT, related_name='interventions')
    technician = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='interventions')
    scheduled_at = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=120, validators=[MinValueValidator(1)])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.MAINTENANCE)
    performed_on = models.DateField(null=True, blank=True)
    replacement_equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, null=True, blank=True, related_name='replacement_interventions')
    contract = models.ForeignKey('Contract', on_delete=models.PROTECT, null=True, blank=True, related_name='reported_interventions')
    extension_warranty = models.ForeignKey('Warranty', on_delete=models.PROTECT, null=True, blank=True, related_name='reported_interventions')
    cabinet_serial = models.CharField(max_length=120, blank=True)
    battery_count = models.PositiveIntegerField(null=True, blank=True)
    site = models.CharField(max_length=250, blank=True)
    end_customer = models.CharField(max_length=200, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    summary = models.TextField(blank=True)
    conclusion = models.CharField(max_length=32, choices=Conclusion.choices, default='', blank=True)
    conclusion_notes = models.TextField(blank=True)
    structured_data = models.JSONField(default=dict, blank=True)
    diagnosis = models.TextField(blank=True)
    work_done = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [models.CheckConstraint(condition=models.Q(duration_minutes__gte=1), name='intervention_duration_positive')]
    def __str__(self):
        return self.reference


class Part(LegacyModel):
    class Category(models.TextChoices):
        BATTERY = 'battery', 'Batteries'
        BOARD = 'board', 'Cartes'
        VENTILATION = 'ventilation', 'Ventilation'
        OTHER = 'other', 'Divers'
    sku = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    stock_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    min_stock = models.PositiveIntegerField(default=5)
    class Meta:
        ordering = ['sku']
        constraints = [models.CheckConstraint(condition=models.Q(stock_quantity__gte=0), name='part_stock_nonnegative'), models.CheckConstraint(condition=models.Q(unit_price__gte=0), name='part_price_nonnegative')]
    def __str__(self):
        return f'{self.sku} — {self.name}'


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        IN = 'in', 'Entrée'
        OUT = 'out', 'Sortie'
        ADJUSTMENT = 'adjustment', 'Ajustement'
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name='movements')
    quantity = models.IntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    reference = models.CharField(max_length=200, blank=True)
    intervention = models.ForeignKey(Intervention, on_delete=models.PROTECT, null=True, blank=True, related_name='parts_used')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [models.CheckConstraint(condition=~models.Q(quantity=0), name='stock_movement_nonzero')]


class Contract(LegacyModel):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Actif'
        EXPIRED = 'expired', 'Expiré'
        DRAFT = 'draft', 'Brouillon'
    number = models.CharField(max_length=80, unique=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='contracts')
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, null=True, blank=True, related_name='contracts')
    starts_on = models.DateField()
    ends_on = models.DateField()
    coverage = models.TextField(blank=True)
    visits_per_year = models.PositiveIntegerField(default=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    class Meta:
        ordering = ['-ends_on', '-id']
        constraints = [models.CheckConstraint(condition=models.Q(ends_on__gte=models.F('starts_on')), name='contract_date_order')]


class Warranty(LegacyModel):
    class Scope(models.TextChoices):
        ELECTRONICS = 'electronics', 'Électronique'
        BATTERIES = 'batteries', 'Batteries'
        COMBINED = 'electronics_and_batteries', 'Électronique et batteries'
        UNSPECIFIED = 'unspecified', 'Portée non précisée'
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name='warranties')
    scope = models.CharField(max_length=32, choices=Scope.choices, default=Scope.UNSPECIFIED)
    provider = models.CharField(max_length=150, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    terms = models.TextField(blank=True)
    class Meta:
        ordering = ['-ends_on', '-id']
        constraints = [models.CheckConstraint(condition=models.Q(ends_on__gte=models.F('starts_on')), name='warranty_date_order')]


class DeliveryNote(ReferencedModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Brouillon'
        READY = 'ready', 'Prêt à livrer'
        DELIVERED = 'delivered', 'Livré'
    reference_prefix = 'BL'
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='delivery_notes')
    intervention = models.ForeignKey(Intervention, on_delete=models.PROTECT, null=True, blank=True, related_name='delivery_notes')
    delivered_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-id']


class DeliveryLine(models.Model):
    delivery_note = models.ForeignKey(DeliveryNote, on_delete=models.CASCADE, related_name='lines')
    part = models.ForeignKey(Part, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=250)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    class Meta:
        ordering = ['id']
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=1), name='delivery_quantity_positive')]


class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=40)
    resource = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-id']


class LegacyRecord(models.Model):
    batch_id = models.CharField(max_length=128)
    table_name = models.CharField(max_length=80)
    source_id = models.CharField(max_length=128)
    payload = models.JSONField()
    imported_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['batch_id', 'table_name', 'source_id'], name='legacy_batch_table_source_unique')]


class LoginAttempt(models.Model):
    identifier = models.CharField(max_length=64, unique=True)
    window_start = models.DateTimeField(default=timezone.now)
    failures = models.PositiveIntegerField(default=0)


class DemoInitialization(models.Model):
    name = models.CharField(max_length=80, primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)


# Keep catalogue models separately while registering them with the core app.
from .catalogue_models import CatalogueImport, CatalogueProduct, CatalogueState, CatalogueWarranty  # noqa: E402,F401
from .workflow_models import OperationEvent  # noqa: E402,F401
from .attachment_models import RequestAttachment  # noqa: E402,F401
