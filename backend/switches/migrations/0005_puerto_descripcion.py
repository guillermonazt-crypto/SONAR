from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('switches', '0004_switch_firmware_switch_modelo'),
    ]

    operations = [
        migrations.AddField(
            model_name='puerto',
            name='descripcion',
            field=models.TextField(blank=True, null=True),
        ),
    ]
