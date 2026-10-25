import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0003_catalogueimport_catalogueproduct_cataloguestate_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='warranty', name='scope',
            field=models.CharField(choices=[('electronics', 'Électronique'), ('batteries', 'Batteries'), ('electronics_and_batteries', 'Électronique et batteries'), ('unspecified', 'Portée non précisée')], default='unspecified', max_length=32),
        ),
        migrations.AddField(
            model_name='equipment', name='manufactured_on',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='equipment', name='catalogue_product',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='equipment', to='core.catalogueproduct'),
        ),
        migrations.AddField(
            model_name='servicerequest', name='intake_key',
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='servicerequest', name='intake_data',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
