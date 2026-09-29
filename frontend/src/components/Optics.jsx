import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { timeAgo } from "../utils/format";
import { useAutoRefresh } from "../utils/refresh";
import SonarDataTable from "./DataTable";

// El nivel lo calcula el backend (switches/optics.py) con los umbrales del admin.
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

const number = (value, unit, digits = 1) =>
  value === null || value === undefined ? "—" : `${Number(value).toFixed(digits)} ${unit}`;

// Umbrales efectivos (del módulo o globales) en una línea corta bajo el valor.
function limitText(limits, unit) {
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
function Metric({ item, metric, field, unit, digits = 1 }) {
  const level = item.niveles?.[metric] || "ok";
  const limits = limitText(item.umbrales?.[metric], unit);
  return (
    <div className="optic-metric" title={limits}>
      <span className={level === "ok" ? "" : `status-${level}-text`}>{number(item[field], unit, digits)}</span>
      {limits && <small>{limits}</small>}
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

/** Transceptores SFP: potencia RX/TX, temperatura y alertas fuera de rango. */
export default function Optics({ onOpenPort = () => {} }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");

  async function refresh(force = false) {
    try {
      setData(await api.optics(force));
      setError("");
    } catch (exception) {
      setError(exception.message);
    }
  }
  useEffect(() => {
    refresh();
  }, []);
  useAutoRefresh(() => refresh());

  // Clave estable por transceptor: la tabla no vuelve a montar filas al refrescar.
  const items = useMemo(
    () => (data?.transceptores || []).map((item) => ({ ...item, clave: `${item.device}|${item.interfaz}` })),
    [data],
  );
  const count = (level) => items.filter((item) => item.nivel === level).length;
  const visible = filter === "all" ? items : items.filter((item) => item.nivel === filter);
  const limits = data?.umbrales;

  const columns = [
    { name: "Estado", sortable: true, width: "130px", selector: (item) => LEVELS[item.nivel]?.rank ?? 0, cell: (item) => <LevelBadge level={item.nivel} /> },
    {
      name: "Switch / Interfaz",
      sortable: true,
      grow: 1.6,
      selector: (item) => `${item.switch?.nombre || item.device} ${item.interfaz}`,
      cell: (item) => (
        <div>
          <strong>{item.switch?.nombre || item.device}</strong>
          <small>{item.interfaz}{item.switch ? ` · ${item.switch.plantel_nombre}` : " · fuera del inventario"}</small>
        </div>
      ),
    },
    {
      name: "RX",
      sortable: true,
      right: true,
      grow: 1.3,
      selector: (item) => item.rx_dbm ?? -99,
      cell: (item) => (
        <div>
          <Metric item={item} metric="rx" field="rx_dbm" unit="dBm" />
          {item.rx_base_dbm != null && !item.sin_senal && <small>base 7 d: {number(item.rx_base_dbm, "dBm")}</small>}
          {linkState(item) && <small>{linkState(item)}</small>}
        </div>
      ),
    },
    { name: "TX", sortable: true, right: true, grow: 1.3, selector: (item) => item.tx_dbm ?? -99, cell: (item) => <Metric item={item} metric="tx" field="tx_dbm" unit="dBm" /> },
    { name: "Temp.", sortable: true, right: true, grow: 1.1, selector: (item) => item.temperatura ?? -99, cell: (item) => <Metric item={item} metric="temp" field="temperatura" unit="°C" digits={0} /> },
    {
      name: "Láser",
      right: true,
      cell: (item) => (
        <div>
          <span>{number(item.bias_ma, "mA")}</span>
          <small>{number(item.voltaje_v, "V", 2)}</small>
        </div>
      ),
    },
    { name: "Atenuación", sortable: true, right: true, selector: (item) => item.atenuacion ?? -1, cell: (item) => number(item.atenuacion, "dB") },
    {
      name: "Motivos",
      grow: 2,
      cell: (item) =>
        item.motivos.length ? (
          <ul className="device-reasons optic-reasons">
            {item.motivos.map((reason, index) => (
              <li key={index} className={`reason-${reason.level}`}>{reason.text}</li>
            ))}
          </ul>
        ) : (
          <small>{item.time ? `Lectura ${timeAgo(item.time)}` : ""}</small>
        ),
    },
    {
      name: "",
      button: true,
      width: "120px",
      cell: (item) =>
        item.switch && (
          <button type="button" onClick={() => onOpenPort(item.switch, item.puerto_id)}>
            Ver puerto
          </button>
        ),
    },
  ];

  return (
    <>
      <div className="section-title page-heading">
        <div>
          <span className="eyebrow">FIBRA</span>
          <h2>Ópticas SFP</h2>
          <p>Potencia de recepción y transmisión, temperatura y degradación de cada transceptor.</p>
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
        ) : (
          <div className="table-scroll sonar-table">
            <SonarDataTable
              columns={columns}
              data={visible}
              keyField="clave"
              defaultSortFieldId={1}
              defaultSortAsc={false}
              noDataComponent="No hay lecturas ópticas. Los puertos de cobre y los módulos sin DOM no publican potencia óptica por SNMP."
            />
          </div>
        )}
        {limits && (
          <p className="thresholds">
            Mandan los umbrales DOM que publica cada módulo (marcados «módulo»). Respaldo global para módulos sin umbrales
            (editable en el admin, Umbrales ópticos): RX atención ≤ {limits.rx_atencion} dBm · riesgo ≤ {limits.rx_riesgo} dBm ·
            saturación ≥ {limits.rx_saturacion} dBm · TX mínimo {limits.tx_minimo} dBm · temperatura {limits.temp_atencion}/{limits.temp_riesgo} °C ·
            degradación: caída de RX ≥ {limits.caida_rx} dB frente a su línea base de 7 días. Los puertos deshabilitados o sin
            enlace no generan alertas.
          </p>
        )}
      </section>
    </>
  );
}
