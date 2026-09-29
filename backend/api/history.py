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


def switch_histories(names, hours=24, every='15m', bucket=None):
    """CPU, memoria y tráfico total por switch en dos consultas para todos.

    Devuelve {nombre: [ {time, cpu, memoria, uptime, entrada_bps, salida_bps} ]}.
    `bucket` permite leer el bucket de largo plazo (promedios de 15 min).
    """
    names = list(dict.fromkeys(names))
    if not names:
        return {}
    url, token, org, default_bucket = influx_settings()
    bucket = bucket or default_bucket
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


def optics_snapshot(hours=24):
    """Última lectura de cada transceptor y su RX máxima del periodo.

    Devuelve [{device, interfaz, time, rx_dbm, tx_dbm, temperatura, atenuacion, estado, rx_max_24h}].
    """
    url, token, org, bucket = influx_settings()
    base = f'''from(bucket: "{flux_string(bucket)}")
  |> range(start: -{int(hours)}h)
  |> filter(fn: (r) => r._measurement == "optica")'''
    latest_flux = f'''{base}
  |> group(columns: ["device", "interface", "_field"])
  |> last()'''
    peak_flux = f'''{base}
  |> filter(fn: (r) => r._field == "rx_dbm")
  |> group(columns: ["device", "interface"])
  |> max()'''
    readings = {}

    def slot(record):
        key = (record.values.get('device'), record.values.get('interface'))
        return readings.setdefault(key, dict(
            device=key[0], interfaz=key[1], time=None, rx_dbm=None, tx_dbm=None,
            temperatura=None, atenuacion=None, estado=None, rx_max_24h=None))

    with InfluxDBClient(url=url, token=token, org=org) as client:
        query_api = client.query_api()
        for table in query_api.query(latest_flux, org=org):
            for record in table.records:
                item = slot(record)
                field = record.get_field()
                if field in item:
                    item[field] = record.get_value()
                time = record.get_time().isoformat()
                item['time'] = max(item['time'] or time, time)
        for table in query_api.query(peak_flux, org=org):
            for record in table.records:
                slot(record)['rx_max_24h'] = record.get_value()
    return list(readings.values())


def trend_buckets():
    """Buckets a intentar para tendencias de días: el de largo plazo primero.

    scripts/setup_influx_downsampling.py crea <INFLUX_BUCKET>_15m con retención
    larga; INFLUX_TREND_BUCKET permite nombrar otro. Si no existe o está vacío se
    usa el bucket crudo.
    """
    bucket = influx_settings()[3]
    return list(dict.fromkeys(filter(None, [os.getenv('INFLUX_TREND_BUCKET'), f'{bucket}_15m', bucket])))


def switch_trends(names, days):
    """Series de `days` días por switch (ventanas de 1 h hasta 7 días, de 6 h después).

    Devuelve (series, bucket usado). Lanza la última excepción si ningún bucket responde.
    """
    every = '1h' if days <= 7 else '6h'
    error = None
    for bucket in trend_buckets():
        try:
            series = switch_histories(names, hours=days * 24, every=every, bucket=bucket)
        except Exception as exception:
            error = exception
            continue
        if any(series.values()):
            return series, bucket
    if error is not None:
        raise error
    return {name: [] for name in names}, None
