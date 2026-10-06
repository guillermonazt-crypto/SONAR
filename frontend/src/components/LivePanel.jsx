import { useEffect, useState } from "react";
import { api } from "../api/client";
import { formatRate, timeAgo } from "../utils/format";
import { useAutoRefresh } from "../utils/refresh";

// Severidades de Zabbix, de la más grave a la más leve.
export const SEVERITIES = [
  [5, "Desastre"],
  [4, "Alta"],
  [3, "Media"],
  [2, "Advertencia"],
  [1, "Información"],
  [0, "Sin clasificar"],
];

/** 75 s → "1 min", 4000 s → "1 h 6 min", 3 días → "3 d 2 h". */
export function age(seconds) {
  const minutes = Math.floor((seconds || 0) / 60);
  if (minutes < 1) return "menos de 1 min";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

const number = (value, unit, digits = 1) => (value === null || value === undefined ? "—" : `${Number(value).toFixed(digits).replace(/\.0$/, "")}${unit}`);
const yesNo = (value, yes = "Sí", no = "No") => (value === null || value === undefined ? "—" : value ? yes : no);

/** Un problema activo de Zabbix con reconocimiento y comentario desde SONAR (editores). */
export function ProblemItem({ problem, canAck, onDone, showSite = true }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function send(ack) {
    setBusy(true);
    setError("");
    try {
      await api.liveAcknowledge(problem.eventid, { mensaje: note.trim(), reconocer: ack });
      setNote("");
      onDone();
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className={`live-problem sev-${problem.severidad}${problem.reconocido ? " acknowledged" : ""}`}>
      <div className="live-problem-main">
        <span className={`sev-badge sev-${problem.severidad}`}>{problem.severidad_nombre}</span>
        <strong>{problem.nombre}</strong>
        {problem.datos && <span className="live-problem-data">{problem.datos}</span>}
        <small>
          {problem.switch?.nombre}
          {showSite && problem.plantel && ` · ${problem.plantel.nombre}`} · desde hace {age(problem.antiguedad_s)}
          {" · "}
          <span className={problem.reconocido ? "ack-yes" : "ack-no"}>{problem.reconocido ? "Reconocido" : "Sin reconocer"}</span>
        </small>
        {error && <small role="alert" className="status-critical-text">{error}</small>}
      </div>
      {canAck && (
        <div className="live-problem-actions">
          <input aria-label={`Comentario para ${problem.nombre} en ${problem.switch?.nombre}`} placeholder="Comentario (opcional)" value={note} onChange={(event) => setNote(event.target.value)} />
          {problem.reconocido ? (
            <button type="button" disabled={busy || !note.trim()} onClick={() => send(false)}>Comentar</button>
          ) : (
            <button type="button" className="primary" disabled={busy} onClick={() => send(true)}>Reconocer</button>
          )}
        </div>
      )}
    </li>
  );
}

function SourceChips({ data }) {
  return (
    <div className="source-chips" aria-label="Fuentes de datos">
      <span className={`source-chip${data?.configurado && !data?.detalle ? " source-on" : " source-off"}`}>
        Zabbix {data?.configurado ? (data?.detalle ? "sin respuesta" : "en vivo") : "no configurado"}
      </span>
      <span className="source-chip source-on">SNMP · worker SONAR</span>
      <span className="source-chip">Historial · InfluxDB{data?.configurado ? " / Zabbix" : ""}</span>
    </div>
  );
}

/** Panel "En vivo (Zabbix)": problemas activos, disponibilidad y equipos con falla. */
export default function LivePanel({ plantel = "", title = "En vivo (Zabbix)", limit = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loadedAt, setLoadedAt] = useState(null);
  const [showAll, setShowAll] = useState(false);
  async function load() {
    try {
      setData(await api.live(plantel));
      setLoadedAt(new Date().toISOString());
      setError("");
    } catch (exception) {
      setError(exception.message);
    }
  }
  useEffect(() => {
    load();
  }, [plantel]);
  useAutoRefresh(load);

  if (data && !data.configurado) {
    return (
      <section className="card live-panel live-off" aria-label={title}>
        <h2>{title}</h2>
        <p className="muted">Zabbix no está configurado: SONAR usa sólo SNMP e InfluxDB. Define ZABBIX_URL y ZABBIX_TOKEN para ver problemas y valores en tiempo real.</p>
      </section>
    );
  }
  const problems = data?.problemas || [];
  const counts = data?.resumen?.por_severidad || {};
  const rows = data?.switches || [];
  const linked = rows.filter((row) => row.hostid);
  const down = linked.filter((row) => row.disponible === false || row.ultimos?.ping === false);
  const latencies = linked.map((row) => row.ultimos?.latencia_ms).filter((value) => value !== null && value !== undefined);
  const meanLatency = latencies.length ? latencies.reduce((sum, value) => sum + value, 0) / latencies.length : null;
  const visible = limit && !showAll ? problems.slice(0, limit) : problems;

  return (
    <section className="card live-panel" aria-label={title}>
      <div className="section-title">
        <div>
          <h2>{title}</h2>
          <small>
            {data ? `${linked.length}/${rows.length} switches en Zabbix · leído ${timeAgo(loadedAt)}` : "Consultando Zabbix…"}
          </small>
        </div>
        <SourceChips data={data} />
      </div>
      {(error || data?.detalle) && <p role="alert" className="live-error">{error || data.detalle}</p>}
      {data && (
        <div className="live-kpis">
          <div className={`live-kpi${data.resumen?.sin_reconocer ? " tone-critical" : ""}`}>
            <span>Problemas</span>
            <strong>{data.resumen?.problemas ?? 0}</strong>
            <small>{data.resumen?.sin_reconocer ?? 0} sin reconocer</small>
          </div>
          <div className={`live-kpi${down.length ? " tone-critical" : ""}`}>
            <span>Disponibles</span>
            <strong>{linked.length - down.length}/{linked.length}</strong>
            <small>{down.length ? `${down.length} sin ping o SNMP` : "todos responden"}</small>
          </div>
          <div className="live-kpi">
            <span>Latencia ICMP</span>
            <strong>{number(meanLatency, " ms")}</strong>
            <small>promedio de {latencies.length} equipos</small>
          </div>
          <div className="live-kpi live-severities">
            <span>Por severidad</span>
            <div>
              {SEVERITIES.slice(0, 5).map(([level, name]) => (
                <span key={level} className={`sev-count sev-${level}${counts[name] ? "" : " zero"}`} title={name}>
                  <i aria-hidden="true" />
                  {name} {counts[name] || 0}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
      {down.length > 0 && (
        <div className="live-down">
          <h3>Sin respuesta en Zabbix</h3>
          <ul>
            {down.map((row) => (
              <li key={row.id}>
                <strong>{row.nombre}</strong>
                <small>
                  {row.plantel_nombre} · {row.ip} · ping {yesNo(row.ultimos?.ping, "responde", "sin respuesta")} · pérdida {number(row.ultimos?.perdida_pct, " %")} · SNMP {yesNo(row.ultimos?.snmp, "disponible", "sin respuesta")}
                </small>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data && !problems.length && !data.detalle && <p className="empty">Sin problemas activos en Zabbix.</p>}
      {problems.length > 0 && (
        <ul className="live-problems">
          {visible.map((problem) => (
            <ProblemItem key={problem.eventid} problem={problem} canAck={data.puede_reconocer} onDone={load} showSite={!plantel} />
          ))}
        </ul>
      )}
      {limit > 0 && problems.length > limit && (
        <button type="button" className="text-button" onClick={() => setShowAll((value) => !value)}>
          {showAll ? "Mostrar menos" : `Ver los ${problems.length} problemas`}
        </button>
      )}
    </section>
  );
}

/** Últimos valores de Zabbix en el detalle del switch: ping, CPU, memoria y uplinks. */
export function SwitchLive({ device }) {
  const [data, setData] = useState(null);
  async function load() {
    if (!device?.id) return;
    try {
      setData(await api.liveSwitch(device.id));
    } catch {
      setData(null);
    }
  }
  useEffect(() => {
    load();
  }, [device?.id]);
  useAutoRefresh(load, Boolean(device?.id));

  if (!data || !data.configurado) return null;
  const row = data.switch;
  const latest = row?.ultimos;
  return (
    <section className="switch-live" aria-label="Últimos valores de Zabbix">
      <div className="switch-live-head">
        <strong>En vivo (Zabbix)</strong>
        <small>
          {data.detalle
            ? data.detalle
            : !row?.hostid
              ? "Este switch no está dado de alta en Zabbix."
              : `${row.host} · lectura ${timeAgo(latest?.momento)} · fuente Zabbix`}
        </small>
      </div>
      {latest && (
        <dl className="switch-live-values">
          <div><dt>Disponible</dt><dd className={row.disponible === false ? "status-critical-text" : ""}>{yesNo(row.disponible)}</dd></div>
          <div><dt>Ping</dt><dd className={latest.ping === false ? "status-critical-text" : ""}>{yesNo(latest.ping, "Responde", "Sin respuesta")}</dd></div>
          <div><dt>Pérdida</dt><dd>{number(latest.perdida_pct, " %")}</dd></div>
          <div><dt>Latencia</dt><dd>{number(latest.latencia_ms, " ms")}</dd></div>
          <div><dt>CPU</dt><dd>{number(latest.cpu, " %")}</dd></div>
          <div><dt>Memoria</dt><dd>{number(latest.memoria, " %")}</dd></div>
          <div><dt>SNMP</dt><dd>{yesNo(latest.snmp, "Disponible", "Sin respuesta")}</dd></div>
        </dl>
      )}
      {latest?.interfaces?.length > 0 && (
        <div className="table-scroll">
          <table className="switch-live-ports">
            <caption>Interfaces con más tráfico (uplinks)</caption>
            <thead>
              <tr><th>Interfaz</th><th>Entrada</th><th>Salida</th><th>Errores entrada / salida</th></tr>
            </thead>
            <tbody>
              {latest.interfaces.map((port) => (
                <tr key={port.nombre}>
                  <td>{port.nombre}</td>
                  <td>{formatRate(port.entrada_bps, { digits: 1, empty: "—" })}</td>
                  <td>{formatRate(port.salida_bps, { digits: 1, empty: "—" })}</td>
                  <td>{port.errores_entrada ?? "—"} / {port.errores_salida ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.problemas?.length > 0 && (
        <ul className="live-problems">
          {data.problemas.map((problem) => (
            <ProblemItem key={problem.eventid} problem={problem} canAck={data.puede_reconocer} onDone={load} showSite={false} />
          ))}
        </ul>
      )}
    </section>
  );
}
