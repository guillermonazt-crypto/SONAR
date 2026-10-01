from django.db import migrations, models


def seed_failures(apps, schema_editor):
    """Los switches que ya estaban sin responder conservan su estado (ya confirmado)."""
    apps.get_model('switches', 'Switch').objects.filter(lectura_correcta=False).update(
        fallos_consecutivos=2, metodos_fallidos=['snmp'])


class Migration(migrations.Migration):

    dependencies = [
        ('switches', '0018_estado_conexion'),
    ]

    operations = [
        migrations.AddField(
            model_name='switch',
            name='fallos_consecutivos',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='switch',
            name='metodos_fallidos',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='switch',
            name='verificacion',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.RunPython(seed_failures, migrations.RunPython.noop),
    ]
