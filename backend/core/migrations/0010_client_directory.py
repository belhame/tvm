from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0009_requestnumbersequence')]
    operations = [
        migrations.AddField(model_name='client', name='tax_id', field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name='client', name='notes', field=models.TextField(blank=True)),
        migrations.AlterField(model_name='client', name='country', field=models.CharField(blank=True, default='France', max_length=80)),
    ]
