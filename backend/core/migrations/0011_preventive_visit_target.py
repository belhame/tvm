import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0010_client_directory')]

    operations = [
        migrations.AddField(
            model_name='servicerequest',
            name='planned_visit_count',
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(1000)]),
        ),
        migrations.AddConstraint(
            model_name='servicerequest',
            constraint=models.CheckConstraint(condition=models.Q(planned_visit_count__isnull=True) | models.Q(planned_visit_count__gte=1, planned_visit_count__lte=1000), name='request_planned_visits_range'),
        ),
    ]
