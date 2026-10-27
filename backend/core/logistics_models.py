"""Courier missions and observed handoffs, distinct from SAV and invoicing."""
from django.db import models


class PickupRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Enlèvement demandé'
        ASSIGNED = 'assigned', 'Affecté au livreur'
        COLLECTED = 'collected', 'Collecté chez le client'
        RECEIVED = 'received', 'Reçu à l’atelier'
        CANCELLED = 'cancelled', 'Annulé'
    client = models.ForeignKey('core.Client', on_delete=models.PROTECT, related_name='pickup_requests')
    equipment = models.ForeignKey('core.Equipment', null=True, blank=True, on_delete=models.PROTECT, related_name='pickup_requests')
    serial_number = models.CharField(max_length=120)
    brand = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=120, blank=True)
    pickup_scope = models.CharField(max_length=16, choices=[('direct', 'Chez le client'), ('end_customer', 'Chez son client final')], default='direct')
    end_customer_name = models.CharField(max_length=200, blank=True)
    assignment_revision = models.PositiveIntegerField(default=1)
    client_reference = models.CharField(max_length=120, blank=True)
    fault_description = models.TextField()
    pickup_address = models.TextField()
    contact_name = models.CharField(max_length=150)
    contact_phone = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    assigned_courier = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='assigned_pickups')
    requested_by = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='requested_pickups')
    requested_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='pickup_assignments')
    collected_at = models.DateTimeField(null=True, blank=True)
    collected_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='collected_pickups')
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='received_pickups')
    service_request = models.ForeignKey('core.ServiceRequest', null=True, blank=True, on_delete=models.PROTECT, related_name='pickup_requests')
    request_key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    cancellation_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-requested_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['requested_by', 'request_key'], name='pickup_actor_request_key_unique'),
            models.CheckConstraint(condition=models.Q(pickup_scope='direct') | (models.Q(pickup_scope='end_customer') & ~models.Q(end_customer_name='')), name='pickup_scope_consistent'),
            models.CheckConstraint(condition=~models.Q(status='received') | models.Q(received_at__isnull=False, received_by__isnull=False, service_request__isnull=False), name='pickup_received_consistent'),
            models.CheckConstraint(condition=~models.Q(status='collected') | models.Q(collected_at__isnull=False, collected_by__isnull=False, assigned_courier__isnull=False), name='pickup_collected_consistent'),
        ]


class CourierReceipt(models.Model):
    actor = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='courier_receipts')
    request_key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    service_request = models.ForeignKey('core.ServiceRequest', on_delete=models.PROTECT, related_name='courier_receipts')
    pickup = models.ForeignKey(PickupRequest, null=True, blank=True, on_delete=models.PROTECT, related_name='receipts')
    created_request = models.BooleanField(default=False)
    created_equipment = models.BooleanField(default=False)
    already_received = models.BooleanField(default=False)
    source = models.CharField(max_length=12, choices=[('manual', 'Saisie'), ('usb', 'Douchette USB'), ('camera', 'Caméra'), ('photo', 'Photo')], default='manual')
    recorded_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['actor', 'request_key'], name='courier_receipt_actor_key_unique')]


class OutboundJob(models.Model):
    class Kind(models.TextChoices):
        DELIVERY = 'delivery', 'Livraison'
        RETURN = 'return', 'Retour client'
    service_request = models.OneToOneField('core.ServiceRequest', on_delete=models.PROTECT, related_name='outbound_job')
    client = models.ForeignKey('core.Client', on_delete=models.PROTECT, related_name='outbound_jobs')
    delivery_equipment = models.ForeignKey('core.Equipment', on_delete=models.PROTECT, related_name='outbound_jobs')
    kind = models.CharField(max_length=12, choices=Kind.choices)
    assigned_courier = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='outbound_jobs')
    assigned_at = models.DateTimeField()
    assigned_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='outbound_assignments')
    assignment_mode = models.CharField(max_length=12, choices=[('manual', 'Manuelle'), ('automatic', 'Automatique')], default='manual')
    routing_source = models.CharField(max_length=24, choices=[('manual', 'Manuelle'), ('default_courier', 'Livreur client par défaut'), ('internal_courier', 'Référent TVM')], default='manual')
    assignment_revision = models.PositiveIntegerField(default=1)
    delivery_address = models.TextField(blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    recipient_name = models.CharField(max_length=150, blank=True)
    handed_over_at = models.DateTimeField(null=True, blank=True)
    handed_over_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='handed_over_jobs')
    handed_over_actor_name = models.CharField(max_length=301, blank=True)
    handed_over_actor_role = models.CharField(max_length=20, blank=True)
    handed_over_serial = models.CharField(max_length=120, blank=True)
    handed_over_model = models.CharField(max_length=120, blank=True)
    handed_over_brand = models.CharField(max_length=100, blank=True)
    active = models.BooleanField(default=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey('core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='cancelled_outbound_jobs')
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['delivery_equipment'], condition=models.Q(active=True), name='outbound_active_unit_unique'),
            models.CheckConstraint(condition=models.Q(handed_over_at__isnull=True, handed_over_by__isnull=True, recipient_name='') | (models.Q(handed_over_at__isnull=False, handed_over_by__isnull=False) & ~models.Q(recipient_name='')), name='outbound_handoff_consistent'),
            models.CheckConstraint(condition=models.Q(handed_over_at__isnull=True, cancelled_at__isnull=True) | models.Q(active=False), name='outbound_active_stage_consistent'),
        ]
