from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('core', '0015_logistics_workflow')]

    operations = [
        migrations.CreateModel(name='DailyReminderPreferences', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('enabled', models.BooleanField(default=False)),
            ('timezone', models.CharField(blank=True, max_length=64)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='daily_reminder_preferences', to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name='InAppNotification', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('kind', models.CharField(choices=[('daily_logistics', 'Rappel logistique quotidien'), ('equipment_received', 'Matériel reçu'), ('equipment_delivered', 'Remise enregistrée')], max_length=32)),
            ('dedup_key', models.CharField(max_length=160)),
            ('local_date', models.DateField()),
            ('payload', models.JSONField(default=dict)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('read_at', models.DateTimeField(blank=True, null=True)),
            ('recipient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='in_app_notifications', to=settings.AUTH_USER_MODEL)),
            ('service_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='in_app_notifications', to='core.servicerequest')),
        ], options={'ordering': ['-created_at', '-id'], 'constraints': [
            models.UniqueConstraint(fields=('recipient', 'dedup_key'), name='notification_recipient_dedup_unique'),
            models.UniqueConstraint(condition=models.Q(kind='daily_logistics'), fields=('recipient', 'kind', 'local_date'), name='notification_daily_recipient_unique'),
        ]}),
    ]
