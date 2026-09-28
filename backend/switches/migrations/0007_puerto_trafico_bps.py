from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('switches', '0006_puerto_octetos')]
    operations = [
        migrations.AddField(
            model_name='puerto', name='trafico_entrada_bps',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='puerto', name='trafico_salida_bps',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
