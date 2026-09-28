from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('switches', '0007_puerto_trafico_bps')]
    operations = [
        migrations.RemoveField(model_name='puerto', name='trafico_entrada_bps'),
        migrations.RemoveField(model_name='puerto', name='trafico_salida_bps'),
    ]
