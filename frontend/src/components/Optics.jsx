import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { timeAgo } from "../utils/format";
import { useAutoRefresh } from "../utils/refresh";
import Sparkline from "./Sparkline";
import "./optics.css";

// El nivel lo calcula el backend (switches/optics.py) con los umbrales del módulo o del admin.
const LEVELS = {
  ok: { rank: 0, label: "Normal", icon: "●" },
  warning: { rank: 1, label: "Atención", icon: "▲" },
  critical: { rank: 2, label: "En riesgo", icon: "✕" },
};
const FILTERS = [
  ["all", "Todos"],
  ["critical", "En riesgo"],
  ["warning", "Atención"],
  ["ok", "Normales"],
];
// [métrica de niveles/umbrales, campo de la lectura, etiqueta, unidad, decimales]
const METRICS = [
  ["rx", "rx_dbm", "RX", "dBm", 1],
  ["tx", "tx_dbm", "TX", "dBm", 1],
  ["temp", "temperatura", "Temperatura", "°C", 1],
  ["voltaje", "voltaje_v", "Voltaje", "V", 2],
  ["bias", "bias_ma", "Bias láser", "mA", 1],
];
const POWER = [["rx_dbm", "RX", "spark-rx"], ["tx_dbm", "TX", "spark-tx"]];

const number = (value, unit, digits = 1) =>
  value === null || value === undefined ? "—" : `${Number(value).toFixed(digits)} ${unit}`;
const signed = (value, unit, digits = 1) =>
  value === null || value === undefined ? "—" : `${value > 0 ? "+" : ""}${Number(value).toFixed(digits)} ${unit}`;
const dbm = (value) => `${Number(value).toFixed(1)} dBm`;

// Umbrales efectivos (del módulo o globales) en una línea corta bajo el valor.
export function limitText(limits, unit) {
  if (!limits) return "";
  const parts = [];
  if (limits.baja_alarma != null) parts.push(`alarma ≤ ${limits.baja_alarma}`);
  if (limits.baja_aviso != null) parts.push(`aviso ≤ ${limits.baja_aviso}`);
  if (limits.alta_aviso != null) parts.push(`aviso ≥ ${limits.alta_aviso}`);
  if (limits.alta_alarma != null) parts.push(`alarma ≥ ${limits.alta_alarma}`);
  const origin = limits.origen === "switch" ? "módulo" : "global";
  return parts.length ? `${parts.join(" · ")} ${unit} (${origin})` : "";
}

/** Valor coloreado según el nivel de esa métrica, con sus umbrales debajo. */
function Metric({ item, metric, field, label, unit, digits }) {
  const level = item.niveles?.[metric] || "ok";
  const limits = limitText(item.umbrales?.[metric], unit);
  return (
    <div className={`optic-metric optic-metric-${level}`}>
      <span className="optic-metric-label">{label}</span>
      <strong className={level === "ok" ? "" : `status-${level}-text`}>{number(item[field], unit, digits)}</strong>
      <small>{limits || "sin umbrales publicados"}</small>
    </div>
  );
}

function Fact({ label, value, detail, tone = "" }) {
  return (
    <div className="optic-fact">
      <span>{label}</span>
      <strong className={tone ? `status-${tone}-text` : ""}>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

function linkState(item) {
  if (item.admin === "down") return "Puerto deshabilitado";
  if (item.sin_senal) return "Sin luz en RX";
  return "";
}

function LevelBadge({ level }) {
  const info = LEVELS[level] || LEVELS.ok;
  return (
    <span className={`status-badge status-${level}`}>
      <span aria-hidden="true">{info.icon}</span> {info.label}
    </span>
  );
}

function moduleText(module) {
  if (!module) return "Módulo sin datos de inventario (ENTITY-MIB)";
  return [
    module.modelo || module.descripcion,
    module.longitud_onda_nm && `${module.longitud_onda_nm} nm`,
    module.serie && `S/N ${module.serie}`,
    module.revision && `rev. ${module.revision}`,
    module.fabricante,
  ].filter(Boolean).join(" · ");
}

function etaText(prediction) {
  if (!prediction) return { value: "—", detail: "se calcula con 12 h de muestras" };
  if (prediction.eta_dias === null || prediction.eta_dias === undefined) return { value: "Estable", detail: "RX sin tendencia a la baja" };
  if (prediction.eta_dias === 0) return { value: "Ya en el límite", detail: `RX ≤ ${prediction.objetivo_dbm} dBm`, tone: "critical" };
  return { value: `~${prediction.eta_dias} días`, detail: `hasta ${prediction.objetivo_dbm} dBm`, tone: prediction.nivel === "ok" ? "" : prediction.nivel };
}

/** Tarjeta con todo lo de un transceptor: DOM, umbrales, enlace, tendencia, errores y módulo. */
function OpticCard({ item, onOpenPort }) {
  const errors = item.errores || {};
  const prediction = item.prediccion;
  const eta = etaText(prediction);
  const remote = item.remoto;
  const margin = item.margen_rx_db;
  return (
    <article className={`optic-card optic-${item.nivel}`} aria-label={`${item.switch?.nombre || item.device} ${item.interfaz}`}>
      <header className="optic-card-head">
        <LevelBadge level={item.nivel} />
        <div className="optic-card-title">
          <strong>{item.switch?.nombre || item.device}</strong>
          <small>{item.interfaz}{item.switch ? ` · ${item.switch.plantel_nombre}` : " · fuera del inventario"}</small>
          <small className="optic-module">{moduleText(item.modulo)}</small>
        </div>
        {item.switch && (
          <button type="button" onClick={() => onOpenPort(item.switch, item.puerto_id)}>Ver puerto</button>
        )}
      </header>

      <div className="optic-metrics">
        {METRICS.map(([metric, field, label, unit, digits]) => (
          <Metric key={metric} item={item} metric={metric} field={field} label={label} unit={unit} digits={digits} />
        ))}
      </div>

      <div className="optic-facts">
        <Fact label={`Margen RX hasta ${item.objetivo_dbm ?? -24} dBm`} value={signed(margin, "dB")}
          tone={margin === null || margin === undefined ? "" : margin < 3 ? "critical" : margin < 6 ? "warning" : ""}
          detail={linkState(item) || (item.rx_base_dbm != null ? `base 7 d: ${number(item.rx_base_dbm, "dBm")}` : "")} />
        <Fact label="Pérdida del enlace" value={number(item.perdida_enlace_db, "dB")}
          detail={remote
            ? `TX remoto ${number(remote.tx_dbm, "dBm")} (${remote.switch} ${remote.puerto}) − RX local`
            : "el vecino no publica DOM o no está en el inventario"} />
        <Fact label="TX − RX local" value={number(item.atenuacion, "dB")} detail="diferencia en este módulo" />
      </div>

      <div className="optic-trend">
        <Fact label="Δ RX 24 h" value={signed(item.delta_rx_24h, "dB", 2)} tone={item.delta_rx_24h <= -1 ? "warning" : ""} />
        <Fact label="Δ RX 7 d" value={signed(item.delta_rx_7d, "dB", 2)} tone={item.delta_rx_7d <= -2 ? "warning" : ""} />
        <Fact label="Pendiente" value={prediction ? signed(prediction.pendiente_db_dia, "dB/día", 2) : "—"}
          detail={prediction ? `${prediction.muestras} muestras` : ""} />
        <Fact label="ETA de falla" value={eta.value} detail={eta.detail} tone={eta.tone} />
        <div className="optic-spark">
          <span>RX y TX · 7 días</span>
          <Sparkline points={item.serie || []} series={POWER} label="Potencia óptica de los últimos 7 días" format={dbm} />
        </div>
      </div>

      <div className="optic-errors">
        <Fact label="CRC / FCS" value={errors.errores_crc ?? "—"} tone={errors.errores_crc ? "warning" : ""} />
        <Fact label="Errores de entrada" value={errors.errores_entrada ?? "—"} tone={errors.errores_entrada ? "warning" : ""} />
        <Fact label="Errores de salida" value={errors.errores_salida ?? "—"} />
        <Fact label="Nuevos último ciclo" value={errors.errores_nuevos ?? "—"} tone={errors.errores_nuevos ? "critical" : ""}
          detail={errors.ultimo_error ? `último error ${timeAgo(errors.ultimo_error)}` : "sin errores recientes"} />
      </div>

      {item.motivos.length > 0 ? (
        <ul className="device-reasons optic-reasons">
          {item.motivos.map((reason, index) => (
            <li key={index} className={`reason-${reason.level}`}>{reason.text}</li>
          ))}
        </ul>
      ) : (
        <small className="optic-time">{item.time ? `Lectura ${timeAgo(item.time)}` : ""}</small>
      )}
    </article>
  );
}

/** Transceptores SFP: todas las métricas DOM con umbrales, enlace, tendencia y errores a la vista. */
export default function Optics({ plantel = "", onOpenPort = () => {} }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");

  async function refresh(force = false) {
    try {
      setData(await api.optics(force, plantel));
      setError("");
    } catch (exception) {
      setError(exception.message);
    }
  }
  useEffect(() => {
    refresh();
  }, []);
  useAutoRefresh(() => refresh());

  // Lo urgente primero; clave estable por transceptor para no volver a montar tarjetas al refrescar.
  const items = useMemo(
    () => (data?.transceptores || [])
      .map((item) => ({ ...item, clave: `${item.device}|${item.interfaz}` }))
      .sort((a, b) => (LEVELS[b.nivel]?.rank ?? 0) - (LEVELS[a.nivel]?.rank ?? 0)),
    [data],
  );
  const count = (level) => items.filter((item) => item.nivel === level).length;
  const visible = filter === "all" ? items : items.filter((item) => item.nivel === filter);
  const limits = data?.umbrales;

  return (
    <>
      <div className="section-title page-heading">
        <div>
          <h2>Ópticas SFP</h2>
          <p>Potencia, temperatura, voltaje y bias de cada transceptor, con su enlace, tendencia y errores del puerto.</p>
        </div>
        <button type="button" onClick={() => refresh(true)}>Actualizar</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {data?.detalle && <p role="alert" className="worker-alert">{data.detalle}</p>}
      <div className="stats">
        <article>
          <span>TRANSCEPTORES</span>
          <strong>{items.length}</strong>
          <small>con lectura DOM</small>
        </article>
        <article>
          <span>EN RIESGO</span>
          <strong className={count("critical") ? "metric-critical" : ""}>{count("critical")}</strong>
          <small>{count("warning")} más requieren atención</small>
        </article>
        <article>
          <span>NORMALES</span>
          <strong>{count("ok")}</strong>
          <small>dentro de rango</small>
        </article>
      </div>
      <section className="card">
        <div className="filter-row">
          {FILTERS.map(([id, label]) => (
            <button key={id} type="button" className={filter === id ? "active" : ""} onClick={() => setFilter(id)}>
              {label} ({id === "all" ? items.length : count(id)})
            </button>
          ))}
        </div>
        {!data && !error ? (
          <p role="status">Cargando ópticas…</p>
        ) : visible.length ? (
          <div className="optic-cards">
            {visible.map((item) => <OpticCard key={item.clave} item={item} onOpenPort={onOpenPort} />)}
          </div>
        ) : (
          <p className="muted">
            {items.length
              ? "Ningún transceptor en este filtro."
              : "No hay lecturas ópticas. Los puertos de cobre y los módulos sin DOM no publican potencia óptica por SNMP."}
          </p>
        )}
        {limits && (
          <p className="thresholds">
            Mandan los umbrales DOM que publica cada módulo (marcados «módulo»); voltaje y bias sólo usan los del módulo.
            Respaldo global para módulos sin umbrales (editable en el admin, Umbrales ópticos): RX atención ≤ {limits.rx_atencion} dBm ·
            riesgo ≤ {limits.rx_riesgo} dBm · saturación ≥ {limits.rx_saturacion} dBm · TX mínimo {limits.tx_minimo} dBm ·
            temperatura {limits.temp_atencion}/{limits.temp_riesgo} °C · degradación: caída de RX ≥ {limits.caida_rx} dB frente a su
            línea base de 7 días. La longitud de onda se deduce del tipo de módulo. Los puertos deshabilitados o sin enlace no
            generan alertas.
          </p>
        )}
      </section>
    </>
  );
}
