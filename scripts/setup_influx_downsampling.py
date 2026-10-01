"""Configura retención y downsampling de InfluxDB para SONAR.

Crea (si no existen):
- Bucket <INFLUX_BUCKET>_15m con retención larga (por defecto 400 días).
- Tarea "sonar-downsample-15m" que cada 15 min guarda promedios de cpu,
  sistema, interfaces y óptica en ese bucket.
- Opcional: token de sólo lectura para Django (--read-token).
- Opcional: reduce la retención del bucket crudo (--raw-retention-days).
  OJO: al reducirla InfluxDB borra los datos más antiguos que ese plazo.

Uso (desde la raíz, con .env cargado):
    python scripts/setup_influx_downsampling.py
    python scripts/setup_influx_downsampling.py --read-token --raw-retention-days 14
"""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from influxdb_client import BucketRetentionRules, InfluxDBClient, Permission, PermissionResource, TaskCreateRequest

load_dotenv(Path(__file__).resolve().parents[1] / '.env')

URL = os.getenv('INFLUX_URL', 'http://localhost:8086')
TOKEN = os.getenv('INFLUX_TOKEN', '')
ORG = os.getenv('INFLUX_ORG', 'universidad')
BUCKET = os.getenv('INFLUX_BUCKET', 'red_universitaria')
TASK_NAME = 'sonar-downsample-15m'


def task_flux(source, target):
    return f'''option task = {{name: "{TASK_NAME}", every: 15m}}

from(bucket: "{source}")
  |> range(start: -task.every)
  |> filter(fn: (r) => r._measurement == "cpu" or r._measurement == "sistema" or
                       r._measurement == "interfaces" or r._measurement == "optica")
  |> filter(fn: (r) => r._field != "estado")
  |> aggregateWindow(every: 15m, fn: mean, createEmpty: false)
  |> to(bucket: "{target}", org: "{ORG}")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--long-retention-days', type=int, default=400)
    parser.add_argument('--raw-retention-days', type=int, help='Reduce la retención del bucket crudo (borra datos antiguos)')
    parser.add_argument('--read-token', action='store_true', help='Crea un token de sólo lectura para Django')
    args = parser.parse_args()
    if not TOKEN:
        raise SystemExit('Define INFLUX_TOKEN en .env')

    target = f'{BUCKET}_15m'
    with InfluxDBClient(url=URL, token=TOKEN, org=ORG) as client:
        org = client.organizations_api().find_organizations(org=ORG)[0]
        buckets = client.buckets_api()
        raw = buckets.find_bucket_by_name(BUCKET)
        if raw is None:
            raise SystemExit(f'No existe el bucket {BUCKET}')
        long_bucket = buckets.find_bucket_by_name(target)
        if long_bucket is None:
            rules = BucketRetentionRules(type='expire', every_seconds=args.long_retention_days * 86400)
            long_bucket = buckets.create_bucket(bucket_name=target, retention_rules=rules, org_id=org.id)
            print(f'Bucket {target} creado ({args.long_retention_days} días)')
        else:
            print(f'Bucket {target} ya existe')

        tasks = client.tasks_api()
        if any(task.name == TASK_NAME for task in tasks.find_tasks(org_id=org.id)):
            print(f'La tarea {TASK_NAME} ya existe')
        else:
            tasks.create_task(task_create_request=TaskCreateRequest(
                flux=task_flux(BUCKET, target), org_id=org.id, status='active', description='Downsampling SONAR'))
            print(f'Tarea {TASK_NAME} creada')

        if args.raw_retention_days:
            raw.retention_rules = [BucketRetentionRules(type='expire', every_seconds=args.raw_retention_days * 86400)]
            buckets.update_bucket(bucket=raw)
            print(f'Retención de {BUCKET} ajustada a {args.raw_retention_days} días')

        if args.read_token:
            permissions = [Permission(action='read', resource=PermissionResource(type='buckets', id=bucket.id, org_id=org.id))
                           for bucket in (raw, long_bucket)]
            auth = client.authorizations_api().create_authorization(
                org_id=org.id, permissions=permissions)
            print('Token de sólo lectura (guárdalo como INFLUX_READ_TOKEN en .env):')
            print(auth.token)


if __name__ == '__main__':
    main()
