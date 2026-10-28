from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies = [('core', '0022_simple_sav_intake'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.AddField(model_name='outboundjob', name='accepted_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='outboundjob', name='accepted_by', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='accepted_outbound_jobs', to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='outboundjob', name='accepted_revision', field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddConstraint(model_name='outboundjob', constraint=models.CheckConstraint(condition=models.Q(accepted_at__isnull=True, accepted_by__isnull=True, accepted_revision__isnull=True) | models.Q(accepted_at__isnull=False, accepted_by__isnull=False, accepted_revision__isnull=False, accepted_revision=models.F('assignment_revision'), accepted_by=models.F('assigned_courier')), name='outbound_acceptance_consistent')),
    ]
