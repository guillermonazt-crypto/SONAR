from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('switches', '0005_puerto_descripcion')]
    operations = [
        migrations.AddField(
            model_name='puerto', name='octetos_entrada',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='puerto', name='octetos_salida',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
