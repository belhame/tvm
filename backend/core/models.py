import secrets

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import MinValueValidator
from django.db import models
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


class ServiceRequest(ReferencedModel):
    class Priority(models.TextChoices):
        LOW = 'low', 'Basse'
        NORMAL = 'normal', 'Normale'
        HIGH = 'high', 'Haute'
        URGENT = 'urgent', 'Urgente'
    class Status(models.TextChoices):
        NEW = 'new', 'Nouvelle'
        SCHEDULED = 'scheduled', 'Planifiée'
        IN_PROGRESS = 'in_progress', 'En cours'
        RESOLVED = 'resolved', 'Résolue'
        CLOSED = 'closed', 'Clôturée'
    reference_prefix = 'SAV'
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name='service_requests')
    subject = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-created_at', '-id']
    def __str__(self):
        return self.reference


class Intervention(ReferencedModel):
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
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name='warranties')
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
