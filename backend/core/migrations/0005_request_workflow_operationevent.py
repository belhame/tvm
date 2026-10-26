import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def baseline(apps, schema_editor):
    Event = apps.get_model('core', 'OperationEvent')
    Equipment = apps.get_model('core', 'Equipment')
    Request = apps.get_model('core', 'ServiceRequest')
    Intervention = apps.get_model('core', 'Intervention')
    database = schema_editor.connection.alias
    for equipment in Equipment.objects.using(database).iterator():
        Event.objects.using(database).create(
            equipment_id=equipment.pk, kind='baseline', source='baseline', actor_label='Reprise de situation',
            status_after=equipment.status, recorded_created_at=equipment.created_at,
            summary='Onduleur déjà enregistré : situation constatée lors de l’activation de l’historique. Aucune opération antérieure reconstituée.',
        )
    for request in Request.objects.using(database).iterator():
        Event.objects.using(database).create(
            equipment_id=request.equipment_id, service_request_id=request.pk, kind='baseline', source='baseline',
            actor_label='Reprise de situation', status_after=request.status, recorded_created_at=request.created_at,
            summary='Demande existante : état repris lors de l’activation de l’historique. Sa date de création connue ne date pas une transition.',
        )
    for intervention in Intervention.objects.using(database).select_related('service_request').iterator():
        Event.objects.using(database).create(
            equipment_id=intervention.service_request.equipment_id, service_request_id=intervention.service_request_id,
            intervention_id=intervention.pk, kind='baseline', source='baseline', actor_label='Reprise de situation',
            status_after=intervention.status, recorded_created_at=intervention.created_at,
            summary='Intervention existante : état repris lors de l’activation de l’historique. Les étapes passées ne sont pas reconstituées.',
        )


def add_immutable_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''
            CREATE FUNCTION core_operationevent_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Historical operation events are immutable'; END; $$;
            CREATE TRIGGER core_operationevent_immutable_trigger
              BEFORE UPDATE OR DELETE ON core_operationevent
              FOR EACH ROW EXECUTE FUNCTION core_operationevent_immutable();
        ''')


def remove_immutable_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('DROP TRIGGER IF EXISTS core_operationevent_immutable_trigger ON core_operationevent; DROP FUNCTION IF EXISTS core_operationevent_immutable();')


class Migration(migrations.Migration):
    dependencies = [('core', '0004_equipment_catalogue_product_and_request_intake'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='servicerequest', name='assigned_technician', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='assigned_requests', to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='servicerequest', name='due_on', field=models.DateField(blank=True, null=True)),
        migrations.AlterField(model_name='servicerequest', name='status', field=models.CharField(choices=[('new', 'Non affecté'), ('scheduled', 'Planifiée'), ('in_progress', 'En cours'), ('maintenance', 'En entretien'), ('testing', 'En test'), ('resolved', 'Traité'), ('quotation', 'Devis'), ('pending', 'En attente'), ('approved', 'Validé'), ('rejected', 'Refusé'), ('exchange', 'Échange'), ('closed', 'Clôturée')], default='new', max_length=20)),
        migrations.CreateModel(name='OperationEvent', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('actor_label', models.CharField(blank=True, max_length=301)),
            ('kind', models.CharField(max_length=40)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('status_before', models.CharField(blank=True, max_length=20)),
            ('status_after', models.CharField(blank=True, max_length=20)),
            ('observation', models.TextField(blank=True)),
            ('summary', models.TextField(blank=True)),
            ('is_internal', models.BooleanField(default=False)),
            ('source', models.CharField(default='application', max_length=20)),
            ('recorded_created_at', models.DateTimeField(blank=True, null=True)),
            ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='operation_events', to=settings.AUTH_USER_MODEL)),
            ('equipment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='operation_events', to='core.equipment')),
            ('related_equipment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='related_operation_events', to='core.equipment')),
            ('intervention', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='operation_events', to='core.intervention')),
            ('service_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='operation_events', to='core.servicerequest')),
        ], options={'ordering': ['created_at', 'id'], 'indexes': [models.Index(fields=['equipment', 'created_at'], name='core_operat_equipme_a7d65b_idx'), models.Index(fields=['service_request', 'created_at'], name='core_operat_service_c795da_idx')]}),
        migrations.RunPython(baseline, migrations.RunPython.noop),
        migrations.RunPython(add_immutable_trigger, remove_immutable_trigger),
    ]
