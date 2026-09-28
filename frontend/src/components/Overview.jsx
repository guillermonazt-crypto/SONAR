import { useEffect, useState } from "react";
import { api } from "../api/client";

const labels = { up: "activos", down: "inactivos", unknown: "sin lectura" };

function formatUptime(value) {
  if (!Number.isFinite(Number(value))) return "Sin lectura";
  const days = Math.floor(Number(value) / 86400);
  const hours = Math.floor((Number(value) % 86400) / 3600);
  return `${days}d ${hours}h`;
}

function MetricHistory({ points }) {
  const valid = points.filter((point) => Number.isFinite(Number(point.cpu)) || Number.isFinite(Number(point.memoria)));
  if (!valid.length) return <small className="metric-history-empty">Sin histórico todavía</small>;
  const values = valid.flatMap((point) => [Number(point.cpu), Number(point.memoria)]).filter(Number.isFinite);
  const max = Math.max(100, ...values);
  const line = (key) => valid.map((point, index) => {
    const value = Number(point[key]);
    return `${(index / Math.max(1, valid.length - 1)) * 100},${value === value ? 32 - (value / max) * 28 : 32}`;
  }).join(" ");
  return <svg className="metric-history" viewBox="0 0 100 34" role="img" aria-label="Histórico de CPU y memoria">
    <polyline points={line("cpu")} fill="none" stroke="#00d4ff" strokeWidth="1.5" />
    <polyline points={line("memoria")} fill="none" stroke="#9b7bff" strokeWidth="1.5" />
  </svg>;
}

export default function Overview({ dashboard }) {
  const [devices, setDevices] = useState([]);
  const [portStats, setPortStats] = useState({});
  const [error, setError] = useState("");
  const [zabbix, setZabbix] = useState(null);
  const [histories, setHistories] = useState({});
  async function refresh() {
    setError("");
    try {
      const switches = await api.list("switches");
      setDevices(switches);
      const historyEntries = await Promise.all(
        switches.map(async (device) => {
          try { return [device.id, (await api.switchHistory(device.id)).points || []]; }
          catch { return [device.id, []]; }
        }),
      );
      setHistories(Object.fromEntries(historyEntries));
      const entries = await Promise.all(
        switches.map(async (device) => [device.id, await api.ports(device.id)]),
      );
      setPortStats(Object.fromEntries(entries));
    } catch (exception) {
      setError(exception.message);
    }
    try {
      setZabbix(await api.zabbix());
    } catch (exception) {
      // Zabbix es opcional: no debe impedir mostrar el inventario SONAR.
      setZabbix({ configured: false, hosts: [], detail: "Zabbix no disponible." });
    }
  }
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => clearInterval(timer);
  }, []);
  const allPorts = Object.values(portStats).flat();
  const totalErrors = allPorts.reduce(
    (sum, port) =>
      sum +
      [port.errores_entrada, port.errores_salida, port.errores_crc]
        .filter(Number.isFinite)
        .reduce((a, b) => a + b, 0),
    0,
  );
  const active = allPorts.filter(
    (port) => port.estado_operativo === "up",
  ).length;
  const unknown = allPorts.filter(
    (port) => !["up", "down"].includes(port.estado_operativo),
  ).length;
  const damaged = allPorts.filter(
    (port) => port.estado === "rojo" || [port.errores_entrada, port.errores_salida, port.errores_crc]
      .some((value) => Number.isFinite(value) && value > 0),
  ).length;
  const voice = allPorts.filter((port) => Number(port.voice_vlan) > 0 && Number(port.voice_vlan) !== 4096).length;
  const trunks = allPorts.filter((port) => port.es_trunk).length;
  return (
    <>
      {error && <p role="alert">{error}</p>}
      <div className="stats overview-stats">
        <article>
          <span>SALUD DE LA RED</span>
          <strong>
            {devices.filter((device) => device.lectura_correcta).length}/
            {devices.length}
          </strong>
          <small>switches con lectura válida</small>
        </article>
        <article>
          <span>PUERTOS ACTIVOS</span>
          <strong>{active}</strong>
          <small>de {allPorts.length} observados</small>
        </article>
        <article>
          <span>ERRORES ACUMULADOS</span>
          <strong>{totalErrors.toLocaleString()}</strong>
          <small>entrada, salida y CRC</small>
        </article>
        <article>
          <span>PUERTOS DAÑADOS</span>
          <strong className="metric-damaged">{damaged}</strong>
          <small>errores o estado dañado</small>
        </article>
        <article>
          <span>VOZ / TRONCALES</span>
          <strong>{voice} / {trunks}</strong>
          <small>Voice VLAN / trunk</small>
        </article>
      </div>
      <section className="card overview-list">
        <div className="section-title">
          <div>
            <span className="eyebrow">AHORA</span>
            <h2>Qué necesita atención</h2>
          </div>
          <button type="button" onClick={refresh}>
            Actualizar
          </button>
        </div>
        {devices.map((device) => {
          const ports = portStats[device.id] || [];
          const down = ports.filter(
            (port) => port.estado_operativo === "down",
          ).length;
          const unknownPorts = ports.filter(
            (port) => !["up", "down"].includes(port.estado_operativo),
          ).length;
          const errors = ports.reduce(
            (sum, port) =>
              sum +
              [port.errores_entrada, port.errores_salida, port.errores_crc]
                .filter(Number.isFinite)
                .reduce((a, b) => a + b, 0),
            0,
          );
          return (
            <article className="health-row" key={device.id}>
              <div>
                <strong>{device.nombre}</strong>
                <small>
                  {device.hostname} · {device.plantel_nombre}
                </small>
              </div>
              <div className="health-facts">
                <span
                  className={
                    device.lectura_correcta ? "health-ok" : "health-bad"
                  }
                >
                  {device.lectura_correcta ? "Lectura válida" : "Sin respuesta"}
                </span>
                <span>
                  {down} {labels.down}
                </span>
                <span>
                  {unknownPorts} {labels.unknown}
                </span>
                <span>{errors} errores</span>
              </div>
              <div className="device-metrics">
                <span>CPU <strong>{device.cpu_5m ?? "—"}%</strong></span>
                <span>RAM <strong>{device.memoria_usada_pct ?? "—"}%</strong></span>
                <span>Uptime <strong>{formatUptime(device.uptime_segundos)}</strong></span>
                <MetricHistory points={histories[device.id] || []} />
              </div>
            </article>
          );
        })}
        {!devices.length && (
          <p className="empty">No hay switches en el inventario.</p>
        )}
      </section>
      <section className="card historical native-monitor">
        <div className="section-title">
          <div>
            <span className="eyebrow">SONAR</span>
            <h2>Diagnóstico operativo</h2>
          </div>
        </div>
        <p>
          Esta vista resume el estado actual directamente desde Django y SNMP,
          sin depender de un dashboard externo.
        </p>
        <div className="native-metrics">
          <span><i className="legend-dot dot-damaged" /> {damaged} puertos con daño</span>
          <span><i className="legend-dot dot-voice" /> {voice} con Voice VLAN</span>
          <span><i className="legend-dot dot-trunk" /> {trunks} enlaces trunk</span>
          <span><i className="legend-dot dot-up" /> {active} activos</span>
          <span><i className="legend-dot dot-unknown" /> {unknown} sin lectura</span>
        </div>
      </section>
      <section className="card integration-card">
        <div className="section-title">
          <div>
            <span className="eyebrow">INTEGRACIÓN</span>
            <h2>Zabbix</h2>
          </div>
          <span className={zabbix?.configured && !zabbix.detail ? "health-ok" : "health-bad"}>
            {zabbix?.configured && !zabbix.detail ? "Conectado" : "No configurado"}
          </span>
        </div>
        <p>{zabbix?.detail || "SONAR puede consultar aquí los hosts y disponibilidad publicados por Zabbix."}</p>
        {zabbix?.hosts?.length > 0 && <small>{zabbix.hosts.length} hosts publicados por Zabbix.</small>}
      </section>
    </>
  );
}
