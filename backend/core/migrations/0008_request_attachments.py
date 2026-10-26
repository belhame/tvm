import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0007_request_arrival_followup'),
    ]

    operations = [
        migrations.CreateModel(
            name='RequestAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stored_name', models.CharField(editable=False, max_length=255)),
                ('original_name', models.CharField(max_length=200)),
                ('label', models.CharField(max_length=200)),
                ('mime_type', models.CharField(max_length=100)),
                ('size_bytes', models.PositiveBigIntegerField()),
                ('sha256', models.CharField(max_length=64)),
                ('client_visible', models.BooleanField(default=False)),
                ('uploaded_by_label', models.CharField(max_length=301)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('storage_deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('service_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='core.servicerequest')),
                ('uploaded_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='uploaded_request_documents', to=settings.AUTH_USER_MODEL)),
                ('deleted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deleted_request_documents', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [models.Index(fields=['service_request', 'deleted_at'], name='attachment_request_active')],
            },
        ),
    ]
