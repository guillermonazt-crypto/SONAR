from django.db import migrations, models
from django.db.models import F


def seed_last_success(apps, schema_editor):
    """La última consulta correcta conocida cuenta como última lectura exitosa."""
    apps.get_model('switches', 'Switch').objects.filter(
        lectura_correcta=True, ultima_consulta__isnull=False).update(ultima_lectura_exitosa=F('ultima_consulta'))


class Migration(migrations.Migration):

    dependencies = [
        ('switches', '0017_dom_opticas'),
    ]

    operations = [
        migrations.AddField(
            model_name='switch',
            name='ultima_lectura_exitosa',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='EstadoMonitoreo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('iniciado', models.DateTimeField(blank=True, null=True)),
                ('latido', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Estado del monitoreo',
                'verbose_name_plural': 'Estado del monitoreo',
            },
        ),
        migrations.RunPython(seed_last_success, migrations.RunPython.noop),
    ]
