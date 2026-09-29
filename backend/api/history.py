"""Consultas históricas a InfluxDB para las gráficas de SONAR."""
import os

from influxdb_client import InfluxDBClient


def flux_string(value):
    """Escapa un valor para usarlo dentro de una cadena Flux entre comillas."""
    return str(value).replace('\\', '\\\\').replace('"', '\\"')


def influx_settings():
    # Django sólo lee: usa un token de lectura si existe (INFLUX_READ_TOKEN).
    token = os.getenv('INFLUX_READ_TOKEN') or os.getenv('INFLUX_TOKEN', '')
    return (os.getenv('INFLUX_URL', 'http://localhost:8086'), token,
            os.getenv('INFLUX_ORG', 'universidad'), os.getenv('INFLUX_BUCKET', 'red_universitaria'))


def _device_filter(names):
    items = ', '.join(f'"{flux_string(name)}"' for name in names)
    return f'contains(value: r.device, set: [{items}])'


def switch_histories(names, hours=24, every='15m'):
    """CPU, memoria y tráfico total por switch en dos consultas para todos.

    Devuelve {nombre: [ {time, cpu, memoria, uptime, entrada_bps, salida_bps} ]}.
    """
    names = list(dict.fromkeys(names))
    if not names:
        return {}
    url, token, org, bucket = influx_settings()
    base = f'''from(bucket: "{flux_string(bucket)}")
  |> range(start: -{int(hours)}h)
  |> filter(fn: (r) => {_device_filter(names)})'''
    usage_flux = f'''{base}
  |> filter(fn: (r) => (r._measurement == "cpu" and r._field == "cpu_5m") or
                       (r._measurement == "sistema" and (r._field == "memoria_usada_pct" or r._field == "uptime_segundos")))
  |> group(columns: ["device", "_measurement", "_field"])
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: {every}, fn: last, createEmpty: false)'''
    # Tasa por interfaz (contadores HC) promediada por ventana y sumada en Python.
    traffic_flux = f'''{base}
  |> filter(fn: (r) => r._measurement == "interfaces")
  |> filter(fn: (r) => r._field == "octetos_entrada" or r._field == "octetos_salida")
  |> group(columns: ["device", "interface", "_field"])
  |> sort(columns: ["_time"])
  |> derivative(unit: 1s, nonNegative: true)
  |> aggregateWindow(every: {every}, fn: mean, createEmpty: false)'''
    field_keys = {'cpu_5m': 'cpu', 'memoria_usada_pct': 'memoria', 'uptime_segundos': 'uptime',
                  'octetos_entrada': 'entrada_bps', 'octetos_salida': 'salida_bps'}
    series = {name: {} for name in names}

    def point(device, time):
        return series.setdefault(device, {}).setdefault(time, dict(
            cpu=None, memoria=None, uptime=None, entrada_bps=None, salida_bps=None))

    with InfluxDBClient(url=url, token=token, org=org) as client:
        query_api = client.query_api()
        for table in query_api.query(usage_flux, org=org):
            for record in table.records:
                key = field_keys.get(record.get_field())
                if key:
                    point(record.values.get('device'), record.get_time().isoformat())[key] = record.get_value()
        try:
            traffic_tables = query_api.query(traffic_flux, org=org)
        except Exception:
            traffic_tables = []
        for table in traffic_tables:
            for record in table.records:
                slot = point(record.values.get('device'), record.get_time().isoformat())
                key = field_keys[record.get_field()]
                slot[key] = (slot[key] or 0) + (record.get_value() or 0) * 8
    return {device: [dict(time=time, **values) for time, values in sorted(points.items())]
            for device, points in series.items()}


def port_history(switch_name, port_name, hours=24):
    url, token, org, bucket = influx_settings()
    flux = f'''from(bucket: "{flux_string(bucket)}")
  |> range(start: -{int(hours)}h)
  |> filter(fn: (r) => r._measurement == "interfaces")
  |> filter(fn: (r) => r.device == "{flux_string(switch_name)}" and r.interface == "{flux_string(port_name)}")
  |> filter(fn: (r) => r._field == "octetos_entrada" or r._field == "octetos_salida")
  |> group(columns: ["_field"])
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: 3m, fn: last, createEmpty: false)
  |> group()
  |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")'''
    with InfluxDBClient(url=url, token=token, org=org) as client:
        rows = client.query_api().query(flux, org=org)
    points = [dict(time=record.get_time().isoformat(), entrada=record.values.get('octetos_entrada'),
                 salida=record.values.get('octetos_salida'))
              for table in rows for record in table.records]
    return sorted(points, key=lambda point: point['time'])
