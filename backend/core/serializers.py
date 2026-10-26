from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from .models import AuditLog, Client, Contract, DeliveryLine, DeliveryNote, Equipment, Intervention, Part, ServiceRequest, StockMovement, Warranty
from .workflow import is_due_overdue, request_category, technician_can_write
from .request_timing import request_timing
from .request_followup import FOLLOWUP_FIELD_NAMES, validate_followup

User = get_user_model()


class LegacySerializer(serializers.ModelSerializer):
    def validate_legacy_id(self, value):
        return value or None


class ClientSerializer(LegacySerializer):
    class Meta:
        model = Client
        fields = ['id', 'name', 'contact_name', 'email', 'phone', 'address', 'city', 'postal_code', 'country', 'legacy_id']


class EquipmentSerializer(LegacySerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    class Meta:
        model = Equipment
        fields = ['id', 'client', 'client_name', 'serial_number', 'brand', 'model', 'power_kva', 'location', 'commissioned_on', 'manufactured_on', 'catalogue_product', 'warranty_until', 'status', 'legacy_id']
        read_only_fields = ['manufactured_on', 'catalogue_product']
    def get_fields(self):
        fields = super().get_fields()
        user = getattr(self.context.get('request'), 'user', None)
        if user and user.is_authenticated and user.effective_role == 'client':
            fields.pop('catalogue_product', None)
        return fields
    def validate_serial_number(self, value):
        value = value.strip()
        qs = Equipment.objects.filter(serial_number__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ce numéro de série est déjà enregistré.')
        return value
    def validate(self, attrs):
        if self.instance and 'client' in attrs and attrs['client'].pk != self.instance.client_id and (self.instance.service_requests.exists() or self.instance.contracts.exists() or self.instance.warranties.exists() or self.instance.replacement_interventions.exists() or self.instance.operation_events.exists() or self.instance.related_operation_events.exists()):
            raise serializers.ValidationError({'client': 'Un équipement lié à des dossiers ne peut pas changer de client. Archivez-le et validez une procédure de transfert.'})
        start = attrs.get('commissioned_on', getattr(self.instance, 'commissioned_on', None))
        end = attrs.get('warranty_until', getattr(self.instance, 'warranty_until', None))
        if start and end and end < start:
            raise serializers.ValidationError({'warranty_until': 'La garantie ne peut pas finir avant la mise en service.'})
        return attrs


class ServiceRequestSerializer(LegacySerializer):
    call_number = serializers.CharField(source='reference', read_only=True)
    equipment_serial = serializers.CharField(source='equipment.serial_number', read_only=True)
    client_name = serializers.CharField(source='equipment.client.name', read_only=True)
    assigned_technician = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True).exclude(role='client'), required=False, allow_null=True)
    assigned_technician_name = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    is_due_overdue = serializers.SerializerMethodField()
    timing = serializers.SerializerMethodField()
    accessories = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    class Meta:
        model = ServiceRequest
        fields = ['id', 'reference', 'call_number', 'equipment', 'equipment_serial', 'client_name', 'subject', 'description', 'priority', 'status', 'assigned_technician', 'assigned_technician_name', 'due_on', 'category', 'is_overdue', 'is_due_overdue', 'timing', 'closed_at', 'created_at', 'updated_at', 'legacy_id', 'intake_key', 'intake_data', *FOLLOWUP_FIELD_NAMES]
        read_only_fields = ['reference', 'created_at', 'intake_key', 'intake_data']
    def get_fields(self):
        fields = super().get_fields()
        user = getattr(self.context.get('request'), 'user', None)
        if user and user.is_authenticated and user.effective_role == 'client':
            fields.pop('intake_key', None)
            fields.pop('intake_data', None)
        return fields
    def validate(self, attrs):
        if self.instance and 'equipment' in attrs and attrs['equipment'].pk != self.instance.equipment_id and (self.instance.interventions.exists() or self.instance.operation_events.exists()):
            raise serializers.ValidationError({'equipment': 'Un dossier ayant des interventions ne peut pas changer d’équipement.'})
        user = getattr(self.context.get('request'), 'user', None)
        if user and user.effective_role == 'technician' and any(field in attrs for field in ('assigned_technician', 'due_on')):
            raise serializers.ValidationError('Le responsable gère les affectations et les échéances.')
        assigned = attrs.get('assigned_technician', getattr(self.instance, 'assigned_technician', None))
        state = attrs.get('status', getattr(self.instance, 'status', 'new'))
        if assigned is not None and state == 'new':
            raise serializers.ValidationError({'status': 'Un dossier affecté doit quitter l’état Non affecté. Choisissez par exemple En attente.'})
        return validate_followup(attrs, instance=self.instance, user=user, initial_data=self.initial_data)
    def get_assigned_technician_name(self, obj):
        return (obj.assigned_technician.get_full_name() or obj.assigned_technician.username) if obj.assigned_technician else 'Non affecté'
    def get_category(self, obj):
        return request_category(obj)
    def get_is_overdue(self, obj):
        timing = self.get_timing(obj)
        return timing['timer_state'] == 'running' and timing['is_overdue_48h']
    def get_is_due_overdue(self, obj):
        return is_due_overdue(obj)
    def get_timing(self, obj):
        cache = self.context.setdefault('_request_timing', {})
        now = self.context.setdefault('_request_timing_now', timezone.now())
        key = (obj.pk, obj.arrived_at, obj.closed_at, obj.status)
        if key not in cache:
            cache[key] = request_timing(obj.arrived_at, obj.closed_at, obj.status, now=now)
        return cache[key]
    @transaction.atomic
    def update(self, instance, validated_data):
        instance = ServiceRequest.objects.select_for_update().get(pk=instance.pk)
        self.instance = instance
        validated_data = self.validate(validated_data)
        return super().update(instance, validated_data)


class InterventionSerializer(LegacySerializer):
    call_number = serializers.CharField(source='service_request.reference', read_only=True)
    client_reference = serializers.CharField(source='service_request.client_reference', read_only=True)
    request_reference = serializers.CharField(source='service_request.reference', read_only=True)
    equipment_serial = serializers.CharField(source='service_request.equipment.serial_number', read_only=True)
    equipment_model = serializers.CharField(source='service_request.equipment.model', read_only=True)
    client_name = serializers.CharField(source='service_request.equipment.client.name', read_only=True)
    technician_name = serializers.SerializerMethodField()
    technician = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True).exclude(role='client'), required=False, allow_null=True)
    replacement_equipment_serial = serializers.CharField(source='replacement_equipment.serial_number', read_only=True, default=None)
    contract_number = serializers.CharField(source='contract.number', read_only=True, default=None)
    contract_starts_on = serializers.DateField(source='contract.starts_on', read_only=True, default=None)
    contract_ends_on = serializers.DateField(source='contract.ends_on', read_only=True, default=None)
    extension_starts_on = serializers.DateField(source='extension_warranty.starts_on', read_only=True, default=None)
    extension_ends_on = serializers.DateField(source='extension_warranty.ends_on', read_only=True, default=None)
    extension_scope = serializers.CharField(source='extension_warranty.scope', read_only=True, default=None)
    class Meta:
        model = Intervention
        fields = ['id', 'reference', 'call_number', 'client_reference', 'service_request', 'request_reference', 'equipment_serial', 'equipment_model', 'client_name', 'technician', 'technician_name', 'scheduled_at', 'duration_minutes', 'status', 'kind', 'performed_on', 'replacement_equipment', 'replacement_equipment_serial', 'contract', 'contract_number', 'contract_starts_on', 'contract_ends_on', 'extension_warranty', 'extension_starts_on', 'extension_ends_on', 'extension_scope', 'cabinet_serial', 'battery_count', 'site', 'end_customer', 'contact_name', 'contact_phone', 'summary', 'conclusion', 'conclusion_notes', 'structured_data', 'diagnosis', 'work_done', 'recommendations', 'internal_notes', 'completed_at', 'created_at', 'legacy_id']
        read_only_fields = ['reference', 'completed_at', 'created_at']
    def get_technician_name(self, obj):
        return (obj.technician.get_full_name() or obj.technician.username) if obj.technician else 'Non affecté'
    def get_fields(self):
        fields = super().get_fields()
        user = getattr(self.context.get('request'), 'user', None)
        if user and user.is_authenticated and user.effective_role == 'client':
            fields.pop('internal_notes', None)
            fields.pop('legacy_id', None)
        return fields
    def validate(self, attrs):
        if self.instance and 'service_request' in attrs and attrs['service_request'].pk != self.instance.service_request_id:
            raise serializers.ValidationError({'service_request': 'Le dossier d’une intervention existante ne peut pas être remplacé.'})
        state = attrs.get('status', getattr(self.instance, 'status', 'scheduled'))
        done = attrs.get('work_done', getattr(self.instance, 'work_done', ''))
        if state == 'completed' and not done.strip():
            raise serializers.ValidationError({'work_done': 'Renseignez les travaux réalisés avant de terminer l’intervention.'})
        if attrs.get('duration_minutes', 120) > 2880:
            raise serializers.ValidationError({'duration_minutes': 'Durée maximale : 48 heures.'})
        user = getattr(self.context.get('request'), 'user', None)
        if user and user.effective_role == 'technician':
            request = attrs.get('service_request', getattr(self.instance, 'service_request', None))
            if self.instance is None and request and not technician_can_write(user, request):
                raise serializers.ValidationError({'service_request': 'Le responsable doit vous affecter au dossier avant de créer une intervention.'})
            assigned = attrs.get('technician', self.instance.technician if self.instance else user)
            if assigned != user:
                raise serializers.ValidationError({'technician': 'Un technicien ne peut affecter qu’à lui-même. Le responsable gère les affectations.'})
            attrs.setdefault('technician', user)
        from .intervention_workflow import validate_intervention_workflow
        return validate_intervention_workflow(self, attrs)
    def _save_state(self, instance, service_request, *, sync_status=True):
        # Verrou partagé par toutes les interventions d'un dossier : un rapport
        # terminé ne doit pas masquer une seconde intervention encore en cours.
        if instance.status == 'completed':
            instance.completed_at = instance.completed_at or timezone.now()
        else:
            instance.completed_at = None
        instance.save(update_fields=['completed_at'])
        if sync_status and service_request.status in ('new', 'scheduled', 'in_progress', 'resolved', 'maintenance', 'testing'):
            canonical = service_request.status in ('maintenance', 'testing')
            states = set(service_request.interventions.values_list('status', flat=True))
            if canonical and 'testing' in states:
                service_request.status = 'testing'
            elif states & {'in_progress', 'testing'}:
                service_request.status = 'maintenance' if canonical else 'in_progress'
            elif 'scheduled' in states:
                service_request.status = 'scheduled'
            elif 'completed' in states:
                service_request.status = 'resolved'
            else:
                service_request.status = 'new'
            service_request.save(update_fields=['status', 'updated_at'])
        return instance
    @transaction.atomic
    def create(self, validated_data):
        service_request = ServiceRequest.objects.select_for_update().get(pk=validated_data['service_request'].pk)
        return self._save_state(super().create(validated_data), service_request)
    @transaction.atomic
    def update(self, instance, validated_data):
        service_request = ServiceRequest.objects.select_for_update().get(pk=instance.service_request_id)
        sync_status = 'status' in validated_data and validated_data['status'] != instance.status
        return self._save_state(super().update(instance, validated_data), service_request, sync_status=sync_status)


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=10, trim_whitespace=False)
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'role', 'client', 'is_active', 'password']
    def to_representation(self, instance):
        result = super().to_representation(instance)
        result['role'] = instance.effective_role
        return result
    def validate(self, attrs):
        role = attrs.get('role', getattr(self.instance, 'role', 'technician'))
        if self.instance and self.instance.is_superuser and 'role' in attrs and role != 'admin':
            raise serializers.ValidationError({'role': 'Les droits de superutilisateur se gèrent via la console serveur ; ce compte reste administrateur.'})
        client = attrs.get('client', getattr(self.instance, 'client', None))
        if (role == 'client') != (client is not None):
            raise serializers.ValidationError({'client': 'Un compte client doit être lié à un client ; un compte interne ne doit pas l’être.'})
        if not self.instance and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'Mot de passe obligatoire à la création.'})
        if attrs.get('password'):
            candidate = self.instance or User(username=attrs.get('username', ''), first_name=attrs.get('first_name', ''), last_name=attrs.get('last_name', ''), email=attrs.get('email', ''))
            try:
                password_validation.validate_password(attrs['password'], candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'password': list(exc.messages)})
        if self.instance and self.instance.effective_role == 'admin':
            losing_admin = role != 'admin' or attrs.get('is_active') is False
            if losing_admin and not User.objects.filter(is_active=True).filter(Q(role='admin') | Q(is_superuser=True)).exclude(pk=self.instance.pk).exists():
                raise serializers.ValidationError('Le dernier administrateur actif doit être conservé.')
        return attrs
    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class StaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'role']


class PartSerializer(LegacySerializer):
    class Meta:
        model = Part
        fields = ['id', 'sku', 'name', 'category', 'unit_price', 'stock_quantity', 'min_stock', 'legacy_id']
        read_only_fields = ['stock_quantity']


class StockMovementSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source='part.name', read_only=True)
    class Meta:
        model = StockMovement
        fields = ['id', 'part', 'part_name', 'quantity', 'kind', 'reference', 'intervention', 'created_at']
        read_only_fields = ['created_at']
    def validate(self, attrs):
        quantity = attrs.get('quantity', 0)
        kind = attrs.get('kind')
        if not quantity or abs(quantity) > 1000000:
            raise serializers.ValidationError({'quantity': 'Indiquez une quantité non nulle entre -1 000 000 et 1 000 000.'})
        if kind == 'in' and quantity < 0 or kind == 'out' and quantity > 0:
            raise serializers.ValidationError({'quantity': 'Entrée : quantité positive. Sortie : quantité négative.'})
        user = getattr(self.context.get('request'), 'user', None)
        intervention = attrs.get('intervention')
        if user and user.effective_role == 'technician':
            if kind != 'out' or not intervention or intervention.technician_id != user.pk:
                raise serializers.ValidationError('Les techniciens enregistrent uniquement les sorties pour leurs propres interventions.')
        return attrs
    @transaction.atomic
    def create(self, validated_data):
        part = Part.objects.select_for_update().get(pk=validated_data['part'].pk)
        resulting_stock = part.stock_quantity + validated_data['quantity']
        if resulting_stock < 0:
            raise serializers.ValidationError({'quantity': f'Stock insuffisant : {part.stock_quantity} disponible(s).'})
        part.stock_quantity = resulting_stock
        part.save(update_fields=['stock_quantity'])
        user = getattr(self.context.get('request'), 'user', None)
        validated_data['created_by'] = user if user and user.is_authenticated else None
        return super().create(validated_data)


class DateRangeMixin:
    def validate(self, attrs):
        start = attrs.get('starts_on', getattr(self.instance, 'starts_on', None))
        end = attrs.get('ends_on', getattr(self.instance, 'ends_on', None))
        if start and end and end < start:
            raise serializers.ValidationError({'ends_on': 'La date de fin doit être postérieure ou égale à la date de début.'})
        return attrs


class ContractSerializer(DateRangeMixin, LegacySerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    class Meta:
        model = Contract
        fields = ['id', 'number', 'client', 'client_name', 'equipment', 'starts_on', 'ends_on', 'coverage', 'visits_per_year', 'status', 'legacy_id']
    def validate(self, attrs):
        attrs = super().validate(attrs)
        equipment = attrs.get('equipment', getattr(self.instance, 'equipment', None))
        client = attrs.get('client', getattr(self.instance, 'client', None))
        if self.instance and self.instance.reported_interventions.exists() and (client.pk != self.instance.client_id or getattr(equipment, 'pk', None) != self.instance.equipment_id):
            raise serializers.ValidationError('Un contrat cité dans une intervention ne peut pas changer de client ou d’équipement.')
        if equipment and client and equipment.client_id != client.pk:
            raise serializers.ValidationError({'equipment': 'Cet équipement appartient à un autre client.'})
        return attrs


class WarrantySerializer(DateRangeMixin, LegacySerializer):
    equipment_serial = serializers.CharField(source='equipment.serial_number', read_only=True)
    client_name = serializers.CharField(source='equipment.client.name', read_only=True)
    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance and self.instance.reported_interventions.exists() and 'equipment' in attrs and attrs['equipment'].pk != self.instance.equipment_id:
            raise serializers.ValidationError({'equipment': 'Une garantie citée dans une intervention ne peut pas changer d’équipement.'})
        return attrs
    class Meta:
        model = Warranty
        fields = ['id', 'equipment', 'equipment_serial', 'client_name', 'provider', 'scope', 'starts_on', 'ends_on', 'terms', 'legacy_id']


class DeliveryLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryLine
        fields = ['id', 'part', 'description', 'quantity']


class PortalDeliveryLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryLine
        fields = ['id', 'description', 'quantity']


class DeliveryNoteSerializer(LegacySerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    lines = DeliveryLineSerializer(many=True, required=False)
    class Meta:
        model = DeliveryNote
        fields = ['id', 'reference', 'client', 'client_name', 'intervention', 'delivered_at', 'status', 'notes', 'lines', 'legacy_id']
        read_only_fields = ['reference']
    def get_fields(self):
        fields = super().get_fields()
        user = getattr(self.context.get('request'), 'user', None)
        if user and user.is_authenticated and user.effective_role == 'client':
            fields['lines'] = PortalDeliveryLineSerializer(many=True, read_only=True)
        return fields
    def validate(self, attrs):
        intervention = attrs.get('intervention', getattr(self.instance, 'intervention', None))
        client = attrs.get('client', getattr(self.instance, 'client', None))
        if intervention and client and intervention.service_request.equipment.client_id != client.pk:
            raise serializers.ValidationError({'intervention': 'Cette intervention appartient à un autre client.'})
        return attrs
    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop('lines', [])
        instance = super().create(validated_data)
        for line in lines:
            line.pop('id', None)
            DeliveryLine.objects.create(delivery_note=instance, **line)
        return instance
    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop('lines', None)
        instance = super().update(instance, validated_data)
        if lines is not None:
            instance.lines.all().delete()
            for line in lines:
                line.pop('id', None)
                DeliveryLine.objects.create(delivery_note=instance, **line)
        return instance


class AuditSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    class Meta:
        model = AuditLog
        fields = ['id', 'actor_name', 'action', 'resource', 'resource_id', 'created_at']
    def get_actor_name(self, obj):
        return obj.actor.get_full_name() or obj.actor.username if obj.actor else 'Compte supprimé'
