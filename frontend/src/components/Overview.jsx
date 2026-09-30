import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { formatRate, formatUptime, timeAgo } from "../utils/format";
import { useAutoRefresh } from "../utils/refresh";
import LineChart from "./LineChart";
import SiteBoard from "./SiteBoard";
import { LEVELS, REASON_TYPES, StatusBadge, hasReason } from "./Status";
import { useViewState } from "../utils/viewState";

const FILTERS = [
  ["all", "Todos"],
  ["critical", "En riesgo"],
  ["warning", "Atención"],
  ["ok", "Normales"],
];
const USAGE_SERIES = [["cpu", "CPU %", "accent"], ["memoria", "Memoria %", "violet"]];
const TRAFFIC_SERIES = [["entrada_bps", "Entrada", "accent"], ["salida_bps", "Salida", "violet"]];

const ZABBIX_MIN_MS = 30000;

const rate = (value) => formatRate(value, { digits: 1, empty: "—" });
const formatPercent = (value) => `${Math.round(value)}%`;
function DeviceCharts({ points }) {
  const usage = points.filter((point) => Number.isFinite(point.cpu) || Number.isFinite(point.memoria));
  const traffic = points.filter((point) => Number.isFinite(point.entrada_bps) || Number.isFinite(point.salida_bps));
  return (
    <div className="device-charts">
      <figure>
        <figcaption>CPU y memoria · 24 h</figcaption>
        {usage.length ? (
          <LineChart points={usage} series={USAGE_SERIES} format={formatPercent} max={100} label="CPU y memoria de las últimas 24 horas" />
        ) : <small className="metric-history-empty">Sin histórico todavía</small>}
      </figure>
      <figure>
        <figcaption>Tráfico total · 24 h</figcaption>
        {traffic.length ? (
          <LineChart points={traffic} series={TRAFFIC_SERIES} format={rate} label="Tráfico de entrada y salida de las últimas 24 horas" />
        ) : <small className="metric-history-empty">Sin histórico todavía</small>}
      </figure>
    </div>
  );
}

function metricLevel(value, warning, critical) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "ok";
  if (Number(value) >= critical) return "critical";
  if (Number(value) >= warning) return "warning";
  return "ok";
}

function Metric({ label, value, level = "ok" }) {
  return (
    <div className={`device-metric metric-level-${level}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DeviceCard({ device, limits, onOpenPorts }) {
  const points = device.historial || [];
  const stats = device.puertos || {};
  const traffic = [...points].reverse().find((point) => Number.isFinite(point.entrada_bps));
  return (
    <article className={`device-card device-${device.estado}`}>
      <header className="device-card-head">
        <div>
          <strong>{device.nombre}</strong>
          <small>{device.hostname} · {device.plantel_nombre} · {device.rol}</small>
        </div>
        <StatusBadge level={device.estado} />
      </header>
      <div className="device-metric-row">
        <Metric label="CPU 5 min" value={device.cpu_5m != null ? `${device.cpu_5m}%` : "—"}
          level={metricLevel(device.cpu_5m, limits.cpu_atencion, limits.cpu_riesgo)} />
        <Metric label="Memoria" value={device.memoria_usada_pct != null ? `${Math.round(device.memoria_usada_pct)}%` : "—"}
          level={metricLevel(device.memoria_usada_pct, limits.memoria_atencion, limits.memoria_riesgo)} />
        <Metric label="Tráfico" value={traffic ? `↓${rate(traffic.entrada_bps)} ↑${rate(traffic.salida_bps)}` : "—"} />
        <Metric label="Puertos activos" value={`${stats.up ?? 0}/${stats.total ?? 0}`} />
        <Metric label="Uptime" value={formatUptime(device.uptime_segundos)} />
      </div>
      {device.motivos?.length > 0 && (
        <ul className="device-reasons">
          {device.motivos.map((reason) => <li key={reason.text} className={`reason-${reason.level}`}>{reason.text}</li>)}
        </ul>
      )}
      <DeviceCharts points={points} />
      {onOpenPorts && (
        <div className="device-card-actions">
          <button type="button" onClick={() => onOpenPorts(device)}>Ver puertos</button>
        </div>
      )}
    </article>
  );
}

function groupBySite(items) {
  const groups = new Map();
  items.forEach((item) => {
    const key = item.plantel_nombre || "Sin plantel asignado";
    if (!groups.has(key)) groups.set(key, { division: item.division_nombre, items: [] });
    groups.get(key).items.push(item);
  });
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export default function Overview({ plantel = "", onPlantelChange = () => {}, onOpenPorts }) {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [zabbix, setZabbix] = useState(null);
  // Nivel y tipo de problema se recuerdan con el resto de la vista; el plantel es el global.
  const [filters, setFilters] = useViewState("overview-filters", { level: "all", type: "all" });
  const setFilter = (key, value) => setFilters((current) => ({ ...current, [key]: value }));
  const zabbixAt = useRef(0);
  async function refresh(force = false, auto = false) {
    try {
      setSummary(await api.summary(force, plantel));
      setError("");
    } catch (exception) {
      setError(exception.message);
    }
    // Zabbix no está cacheado en el backend: en automático se consulta como mucho cada 30 s.
    if (auto && Date.now() - zabbixAt.current < ZABBIX_MIN_MS) return;
    zabbixAt.current = Date.now();
    try {
      setZabbix(await api.zabbix());
    } catch {
      // Zabbix es opcional: no debe impedir mostrar el inventario SONAR.
      setZabbix({ configured: false, hosts: [], detail: "Zabbix no disponible." });
    }
  }
  useEffect(() => {
    refresh();
  }, []);
  useAutoRefresh(() => refresh(false, true));

  const devices = (summary?.switches || [])
    .slice()
    .sort((a, b) => LEVELS[b.estado].rank - LEVELS[a.estado].rank || a.nombre.localeCompare(b.nombre));
  const thresholds = summary?.umbrales || {};
  const countLevel = (level) => devices.filter((device) => device.estado === level).length;
  const atRisk = devices.filter((device) => device.estado !== "ok");
  const siteBoard = summary?.planteles || [];
  const inSite = devices;
  const typeCount = (type) => inSite.filter((device) => hasReason(device.motivos, type)).length;
  const byType = filters.type === "all" ? inSite : inSite.filter((device) => hasReason(device.motivos, filters.type));
  const visible = filters.level === "all" ? byType : byType.filter((device) => device.estado === filters.level);
  const filtered = filters.type !== "all" || filters.level !== "all";
  const sites = groupBySite(visible);
  const totals = devices.reduce((sum, device) => {
    const stats = device.puertos || {};
    Object.keys(sum).forEach((key) => { sum[key] += stats[key] || 0; });
    return sum;
  }, { total: 0, up: 0, down: 0, con_errores: 0, danados: 0, troncales: 0, voz: 0 });
  const core = thresholds.core || thresholds.access;

  return (
    <>
      {error && <p role="alert">{error}</p>}
      {summary?.worker_atrasado && (
        <p role="alert" className="worker-alert">
          El worker SNMP no ha escrito lecturas {timeAgo(summary.ultima_lectura)}. Los estados pueden estar desactualizados.
        </p>
      )}
      <div className="stats overview-stats">
        <article>
          <span>SALUD DE LA RED</span>
          <strong>{devices.filter((device) => device.lectura_correcta).length}/{devices.length}</strong>
          <small>switches con lectura válida</small>
        </article>
        <article>
          <span>EQUIPOS EN RIESGO</span>
          <strong className={countLevel("critical") ? "metric-critical" : ""}>{countLevel("critical")}</strong>
          <small>{countLevel("warning")} más requieren atención</small>
        </article>
        <article>
          <span>PUERTOS ACTIVOS</span>
          <strong>{totals.up}</strong>
          <small>de {totals.total} físicos observados</small>
        </article>
        <article>
          <span>PUERTOS CON ERRORES</span>
          <strong className="metric-damaged">{totals.con_errores}</strong>
          <small>errores nuevos en 24 h · {totals.danados} marcados dañados</small>
        </article>
        <article>
          <span>ÚLTIMA LECTURA</span>
          <strong className="stat-time">{summary ? timeAgo(summary.ultima_lectura) : "—"}</strong>
          <small>resumen generado {summary ? timeAgo(summary.generado) : "—"}</small>
        </article>
      </div>

      <SiteBoard sites={siteBoard} selected={plantel ? Number(plantel) : null} onSelect={(id) => onPlantelChange(id ? String(id) : "")} />

      <section className="card risk-panel">
        <div className="section-title">
          <div>
            <span className="eyebrow">AHORA</span>
            <h2>Equipos en riesgo</h2>
          </div>
          <button type="button" onClick={() => refresh(true)}>Actualizar</button>
        </div>
        {atRisk.length ? (
          <ul className="risk-list">
            {atRisk.map((device) => (
              <li key={device.id}>
                <StatusBadge level={device.estado} />
                <div>
                  <strong>{device.nombre}</strong>
                  <small>{device.plantel_nombre}</small>
                </div>
                <span>{device.motivos.map((reason) => reason.text).join(" · ")}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">{summary ? (devices.length ? "Todos los equipos operan dentro de los umbrales." : (plantel ? "No hay switches en este plantel." : "No hay switches en el inventario.")) : "Cargando…"}</p>
        )}
        {core && (
          <small className="thresholds">
            Umbrales (editables por rol en el administrador): CPU ≥ {core.cpu_atencion}% atención y ≥ {core.cpu_riesgo}% riesgo ·
            memoria ≥ {core.memoria_atencion}% / ≥ {core.memoria_riesgo}% · sin respuesta SNMP = riesgo · lectura de hace más de 5 min,
            reinicio en las últimas 24 h o errores nuevos en puertos = atención.{core.puertos_riesgo ? ` ${core.puertos_riesgo} o más puertos con errores o inestables a la vez = riesgo.` : ""}
          </small>
        )}
        {summary?.historial_detalle && <small className="thresholds">{summary.historial_detalle}</small>}
      </section>

      <section className="card device-analysis">
        <div className="section-title">
          <div>
            <span className="eyebrow">ANÁLISIS</span>
            <h2>Estado por equipo</h2>
          </div>
          <div className="filter-bar">
            <label className="inline-field">
              Problema
              <select value={filters.type} onChange={(event) => setFilter("type", event.target.value)}>
                <option value="all">Cualquiera</option>
                {REASON_TYPES.map(([id, label]) => <option key={id} value={id}>{label} ({typeCount(id)})</option>)}
              </select>
            </label>
            {filtered && (
              <button type="button" className="chip" onClick={() => setFilters({ level: "all", type: "all" })}>
                Limpiar filtros
              </button>
            )}
          </div>
          <div className="filter-row" role="group" aria-label="Filtrar equipos por estado">
            {FILTERS.map(([id, label]) => (
              <button key={id} type="button" className={filters.level === id ? "active" : ""} aria-pressed={filters.level === id} onClick={() => setFilter("level", id)}>
                {label} ({id === "all" ? byType.length : byType.filter((device) => device.estado === id).length})
              </button>
            ))}
          </div>
        </div>
        {sites.map(([site, group]) => {
          const red = group.items.filter((device) => device.estado === "critical").length;
          const yellow = group.items.filter((device) => device.estado === "warning").length;
          return (
            <div className="site-group" key={site}>
              {sites.length > 1 || site !== "Sin plantel asignado" ? (
                <h3 className="site-heading">
                  {site}
                  {group.division && <small>{group.division}</small>}
                  <span className="site-counts">
                    {group.items.length} equipo{group.items.length === 1 ? "" : "s"}
                    {red > 0 && <span className="status-critical-text"> · {red} en riesgo</span>}
                    {yellow > 0 && <span className="status-warning-text"> · {yellow} en atención</span>}
                  </span>
                </h3>
              ) : null}
              <div className="device-grid">
                {group.items.map((device) => (
                  <DeviceCard key={device.id} device={device} limits={thresholds[device.rol] || core || {}} onOpenPorts={onOpenPorts} />
                ))}
              </div>
            </div>
          );
        })}
        {summary && !visible.length && <p className="empty">{filtered ? "Ningún equipo coincide con los filtros." : "No hay equipos en este estado."}</p>}
      </section>

      <section className="card historical native-monitor">
        <div className="section-title">
          <div>
            <span className="eyebrow">SONAR</span>
            <h2>Diagnóstico operativo</h2>
          </div>
        </div>
        <p>Esta vista resume el estado actual directamente desde Django y SNMP, sin depender de un dashboard externo.</p>
        <div className="native-metrics">
          <span><i className="legend-dot dot-damaged" /> {totals.con_errores} puertos con errores nuevos</span>
          <span><i className="legend-dot dot-voice" /> {totals.voz} con Voice VLAN</span>
          <span><i className="legend-dot dot-trunk" /> {totals.troncales} enlaces trunk</span>
          <span><i className="legend-dot dot-up" /> {totals.up} activos</span>
          <span><i className="legend-dot dot-unknown" /> {totals.total - totals.up - totals.down} sin lectura</span>
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
