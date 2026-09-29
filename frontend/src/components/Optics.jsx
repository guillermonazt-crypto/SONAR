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
    { name: "RX", sortable: true, right: true, selector: (item) => item.rx_dbm ?? -99, cell: (item) => number(item.rx_dbm, "dBm") },
    { name: "TX", sortable: true, right: true, selector: (item) => item.tx_dbm ?? -99, cell: (item) => number(item.tx_dbm, "dBm") },
    { name: "Temp.", sortable: true, right: true, selector: (item) => item.temperatura ?? -99, cell: (item) => number(item.temperatura, "°C", 0) },
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
          <small>con lectura DOM en 24 h</small>
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
              noDataComponent="No hay lecturas ópticas. Muchos equipos no publican DOM por SNMP."
            />
          </div>
        )}
        {limits && (
          <p className="thresholds">
            Umbrales (editables en el admin, Umbrales ópticos): RX atención ≤ {limits.rx_atencion} dBm · riesgo ≤ {limits.rx_riesgo} dBm ·
            saturación ≥ {limits.rx_saturacion} dBm · TX mínimo {limits.tx_minimo} dBm · temperatura {limits.temp_atencion}/{limits.temp_riesgo} °C ·
            degradación: caída de RX ≥ {limits.caida_rx} dB en 24 h.
          </p>
        )}
      </section>
    </>
  );
}
