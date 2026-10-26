from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0012_exchange_workflow')]
    operations = [
        migrations.AddField(
            model_name='user',
            name='can_validate_billing',
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=~models.Q(role='client') | models.Q(can_validate_billing=False),
                name='user_client_cannot_validate_billing',
            ),
        ),
    ]
