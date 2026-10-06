"""Carga en Zabbix el histórico que ya guardó SONAR (init_zabbix.py --backfill).

Sin esto, las anomalías (trendstl, baselinedev) y los pronósticos (timeleft/forecast)
esperan días a que Zabbix junte historia propia. Se copian, para los mismos ítems que
usan los disparadores de "SONAR Cisco avanzado":

- sonar.cpu.util            <- InfluxDB cpu.cpu_1m del switch
- sonar.uplink.in/out[idx]  <- InfluxDB interfaces.octetos_entrada/salida (bps, ventanas de 5 min)
- sonar.optical.rx[idx]     <- MuestraOptica.rx_dbm de SONAR

history.push de Zabbix 7 sólo acepta ítems trapper; por eso se escribe con COPY en las
tablas history y trends de PostgreSQL. Es seguro porque sólo se insertan valores
ANTERIORES al primero que ya tiene cada ítem (nunca se pisa ni se duplica nada; repetirlo
no agrega filas) y al final se reinicia zabbix-server para que su caché de valores los vea.
"""
import re
import sys
from datetime import datetime, timezone

HOUR = 3600
WINDOW = '5m'
DAYS = 30


def short_port(name):
    """GigabitEthernet1/0/25 y Gi1/0/25 → 'gi1/0/25' (igual que backend/api/zabbix.short_port)."""
    text = (name or '').strip().lower()
    match = re.match(r'([a-z\-]+)\s*(.*)', text)
    if not match:
        return text
    prefix, rest = match.groups()
    for long, short in (('gigabitethernet', 'gi'), ('tengigabitethernet', 'te'), ('fastethernet', 'fa'),
                        ('twentyfivegige', 'twe'), ('fortygigabitethernet', 'fo'), ('hundredgige', 'hu'),
                        ('twogigabitethernet', 'tw'), ('fivegigabitethernet', 'fi')):
        if prefix == long or (prefix.startswith(short) and long.startswith(prefix)):
            return short + rest
    return prefix + rest


def hourly_trends(points):
    """[(clock, valor)] → [(hora, num, min, avg, max)] como la tabla trends de Zabbix."""
    hours = {}
    for clock, value in points:
        hours.setdefault(clock // HOUR * HOUR, []).append(value)
    return [(hour, len(v), min(v), sum(v) / len(v), max(v)) for hour, v in sorted(hours.items())]


def rows_before(points, first_history, first_trend):
    """Sólo lo anterior a lo que Zabbix ya tiene: history < primer valor y trends < su primera hora."""
    history = [(clock, value) for clock, value in points if first_history is None or clock < first_history]
    limit = first_trend if first_trend is not None else (first_history // HOUR * HOUR if first_history else None)
    trends = [row for row in hourly_trends(history) if limit is None or row[0] < limit]
    return history, trends


def copy_sql(rows_by_item):
    """Script psql con COPY (una transacción) para {itemid: (history, trends)}."""
    lines = ['BEGIN;', 'COPY history (itemid, clock, value, ns) FROM STDIN;']
    for itemid, (history, _trends) in rows_by_item.items():
        lines += [f'{itemid}\t{clock}\t{value!r}\t0' for clock, value in history]
    lines += ['\\.', 'COPY trends (itemid, clock, num, value_min, value_avg, value_max) FROM STDIN;']
    for itemid, (_history, trends) in rows_by_item.items():
        lines += [f'{itemid}\t{hour}\t{num}\t{low!r}\t{avg!r}\t{high!r}' for hour, num, low, avg, high in trends]
    lines += ['\\.', 'COMMIT;']
    return '\n'.join(lines) + '\n'


# --- Fuentes ---------------------------------------------------------------------------

def influx_client(sonar_env):
    from influxdb_client import InfluxDBClient
    token = sonar_env.get('INFLUX_READ_TOKEN') or sonar_env.get('INFLUX_TOKEN', '')
    return InfluxDBClient(url=sonar_env.get('INFLUX_URL', 'http://localhost:8086'), token=token,
                          org=sonar_env.get('INFLUX_ORG', 'universidad'), timeout=120_000)


def flux_string(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"')


def influx_cpu(query, bucket, device, stop):
    flux = f'''from(bucket: "{flux_string(bucket)}")
  |> range(start: -{DAYS}d, stop: {stop})
  |> filter(fn: (r) => r._measurement == "cpu" and r._field == "cpu_1m" and r.device == "{flux_string(device)}")
  |> aggregateWindow(every: {WINDOW}, fn: mean, createEmpty: false)'''
    return [(int(r.get_time().timestamp()), float(r.get_value())) for t in query.query(flux) for r in t.records
            if r.get_value() is not None]


def influx_traffic(query, bucket, device, port, stop):
    """{'octetos_entrada': [(clock, bps)], 'octetos_salida': [...]}."""
    flux = f'''from(bucket: "{flux_string(bucket)}")
  |> range(start: -{DAYS}d, stop: {stop})
  |> filter(fn: (r) => r._measurement == "interfaces" and r.device == "{flux_string(device)}"
                       and r.interface == "{flux_string(port)}")
  |> filter(fn: (r) => r._field == "octetos_entrada" or r._field == "octetos_salida")
  |> sort(columns: ["_time"])
  |> derivative(unit: 1s, nonNegative: true)
  |> aggregateWindow(every: {WINDOW}, fn: mean, createEmpty: false)'''
    series = {}
    for table in query.query(flux):
        for r in table.records:
            if r.get_value() is not None:
                series.setdefault(r.get_field(), []).append((int(r.get_time().timestamp()), float(r.get_value()) * 8))
    return series


def sonar_data():
    """Puertos {(ip, ifIndex): nombre} y óptica {(ip, puerto corto): [(clock, rx)]} de la base de SONAR."""
    from switches.models import MuestraOptica, Puerto
    ports = {(ip, index): name for ip, index, name in
             Puerto.objects.values_list('switch__hostname', 'indice', 'nombre')}
    optics = {}
    for ip, name, at, rx in (MuestraOptica.objects.exclude(rx_dbm__isnull=True).order_by('momento')
                             .values_list('puerto__switch__hostname', 'puerto__nombre', 'momento', 'rx_dbm')):
        optics.setdefault((ip, short_port(name)), []).append((int(at.timestamp()), float(rx)))
    return ports, optics


# --- Zabbix --------------------------------------------------------------------------------

def first_clocks(psql, table, itemids):
    if not itemids:
        return {}
    out = psql('-tAc', f"SELECT itemid, min(clock) FROM {table} WHERE itemid IN ({','.join(map(str, itemids))}) "
                       'GROUP BY itemid')
    return {int(a): int(b) for a, b in (line.split('|') for line in out.splitlines() if '|' in line)}


def collect(api, hosts, sonar_env, ports, optics):
    """{itemid: [(clock, valor)]} de todo lo que se puede llenar desde SONAR."""
    items = api.call('item.get', {'output': ['itemid', 'hostid', 'key_', 'name'], 'hostids': [h['hostid'] for h in hosts],
                                  'search': {'key_': ['sonar.cpu.util', 'sonar.uplink.in[', 'sonar.uplink.out[',
                                                      'sonar.optical.rx[']},
                                  'searchByAny': True, 'startSearch': True, 'templated': False}) or []
    by_host = {h['hostid']: h for h in hosts}
    bucket = sonar_env.get('INFLUX_BUCKET', 'red_universitaria')
    stop = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    points, traffic_cache = {}, {}
    with influx_client(sonar_env) as client:
        query = client.query_api()
        for item in items:
            host = by_host[item['hostid']]
            device = host['name']
            ip = next((i['ip'] for i in host.get('interfaces', []) if i.get('ip')), None)
            key = item['key_']
            index = key[key.find('[') + 1:-1] if '[' in key else None
            if key == 'sonar.cpu.util':
                points[item['itemid']] = influx_cpu(query, bucket, device, stop)
            elif key.startswith(('sonar.uplink.in[', 'sonar.uplink.out[')):
                port = ports.get((ip, int(index))) if index and index.isdigit() else None
                if port is None:
                    continue
                if (device, port) not in traffic_cache:
                    traffic_cache[(device, port)] = influx_traffic(query, bucket, device, port, stop)
                field = 'octetos_entrada' if key.startswith('sonar.uplink.in[') else 'octetos_salida'
                points[item['itemid']] = traffic_cache[(device, port)].get(field, [])
            elif key.startswith('sonar.optical.rx['):
                sensor = item['name'].split(':')[0].split()[0]  # "Gi1/0/25 Receive Power Sensor: potencia RX"
                points[item['itemid']] = optics.get((ip, short_port(sensor)), [])
    return {itemid: values for itemid, values in points.items() if values}


def run(api, hosts, sonar_env, psql, restart):
    """Inserta lo anterior a cada ítem y reinicia el server. Devuelve (ítems, filas history, filas trends)."""
    ports, optics = sonar_data()
    points = collect(api, hosts, sonar_env, ports, optics)
    ids = [int(i) for i in points]
    first_history, first_trend = first_clocks(psql, 'history', ids), first_clocks(psql, 'trends', ids)
    rows = {}
    for itemid, values in points.items():
        history, trends = rows_before(sorted(values), first_history.get(int(itemid)), first_trend.get(int(itemid)))
        if history or trends:
            rows[itemid] = (history, trends)
    total_history = sum(len(h) for h, _ in rows.values())
    total_trends = sum(len(t) for _, t in rows.values())
    if rows:
        psql(stdin=copy_sql(rows))
        restart()
    print(f'· Backfill: {len(rows)} ítems, {total_history} valores de history y {total_trends} horas de trends '
          f'(de {len(points)} ítems con datos en SONAR).')
    return len(rows), total_history, total_trends


if __name__ == '__main__':
    sys.exit('Usa: python zabbix/init_zabbix.py --backfill')
