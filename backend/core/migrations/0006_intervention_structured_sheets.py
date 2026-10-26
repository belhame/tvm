import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0005_request_workflow_operationevent'),
    ]

    operations = [
        migrations.AddField(model_name='intervention', name='kind', field=models.CharField(choices=[('maintenance', 'Maintenance'), ('exchange', 'Échange'), ('commissioning', 'Mise en service'), ('preventive', 'Maintenance préventive')], default='maintenance', max_length=20)),
        migrations.AddField(model_name='intervention', name='performed_on', field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name='intervention', name='replacement_equipment', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='replacement_interventions', to='core.equipment')),
        migrations.AddField(model_name='intervention', name='contract', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reported_interventions', to='core.contract')),
        migrations.AddField(model_name='intervention', name='extension_warranty', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reported_interventions', to='core.warranty')),
        migrations.AddField(model_name='intervention', name='cabinet_serial', field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name='intervention', name='battery_count', field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='intervention', name='site', field=models.CharField(blank=True, max_length=250)),
        migrations.AddField(model_name='intervention', name='end_customer', field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name='intervention', name='contact_name', field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name='intervention', name='contact_phone', field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name='intervention', name='summary', field=models.TextField(blank=True)),
        migrations.AddField(model_name='intervention', name='conclusion', field=models.CharField(blank=True, choices=[('', 'Non renseignée'), ('follow_up', 'À suivre'), ('completed', 'Terminée'), ('not_applicable_billable', 'Garantie non applicable / à facturer')], default='', max_length=32)),
        migrations.AddField(model_name='intervention', name='conclusion_notes', field=models.TextField(blank=True)),
        migrations.AddField(model_name='intervention', name='structured_data', field=models.JSONField(blank=True, default=dict)),
    ]
