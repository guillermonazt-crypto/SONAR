import { useEffect, useMemo, useState } from "react";
import { flushSync } from "react-dom";
import { api } from "../api/client";
import { formatRate } from "../utils/format";
import NeighborTypeLabel from "./NeighborType";
import SonarDataTable from "./DataTable";
import LineChart from "./LineChart";
import TopologyMap from "./TopologyMap";
import { useViewState } from "../utils/viewState";

// [tipo, etiqueta, parámetro opcional {clave, etiqueta, valor, opciones}]
const REPORTS = [
  ["inventario", "Inventario"],
  ["tendencias", "Tendencias", { key: "dias", label: "Periodo", value: 7, options: [[7, "7 días"], [30, "30 días"]] }],
  ["disponibilidad", "Disponibilidad", { key: "dias", label: "Días", value: 30 }],
  ["puertos-sin-uso", "Puertos sin uso", { key: "dias", label: "Días sin enlace", value: 30 }],
  ["puertos-inestables", "Puertos inestables", { key: "horas", label: "Horas", value: 24 }],
  ["puertos-saturados", "Puertos saturados"],
  ["puertos-errores", "Puertos con errores", { key: "dias", label: "Días", value: 7 }],
  ["poe", "PoE"],
  ["hardware", "Hardware"],
  ["opticas", "Ópticas"],
  ["topologia", "Topología"],
  ["aps-telefonos", "APs y teléfonos", { key: "equipo", label: "Equipo", value: "", options: [["", "Todos"], ["ap", "Access points"], ["telefono", "Teléfonos"]] }],
];
// Agrupación del menú de reportes (lo que no aparezca aquí va en "Otros").
const GROUPS = [
  ["Equipos", ["inventario", "disponibilidad", "hardware"]],
  ["Puertos", ["puertos-sin-uso", "puertos-inestables", "puertos-saturados", "puertos-errores"]],
  ["Energía y fibra", ["poe", "opticas"]],
  ["Históricos", ["tendencias"]],
];
const LEVEL_TEXT = { ok: "Normal", warning: "Atención", critical: "En riesgo" };

function cell(key, value) {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "estado" || key === "nivel") {
    return LEVEL_TEXT[value] ? <span className={`status-badge status-${value}`}>{LEVEL_TEXT[value]}</span> : value;
  }
  if (key.endsWith("_bps")) return formatRate(value);
  if (key.endsWith("_prom") || key.endsWith("_max")) return `${value}%`;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return new Date(value).toLocaleString();
  return String(value);
}

const percent = (value) => `${Math.round(value)}%`;
const rate = (value) => formatRate(value, { digits: 1, empty: "—" });
const dayLabel = (day) => new Date(`${day}T12:00:00`).toLocaleDateString("es-MX", { day: "2-digit", month: "short" });
const USAGE = [["cpu", "CPU prom. %", "accent"], ["memoria", "Memoria prom. %", "violet"]];
const TRAFFIC = [["entrada_bps", "Entrada", "accent"], ["salida_bps", "Salida", "violet"]];

/** Serie diaria de toda la red: uso, tráfico y alertas nuevas por día. */
function TrendCharts({ serie }) {
  const alerts = serie.reduce((sum, day) => sum + day.alertas, 0);
  const worst = serie.reduce((best, day) => (day.alertas > (best?.alertas ?? 0) ? day : best), null);
  const hasUsage = serie.some((day) => Number.isFinite(day.cpu) || Number.isFinite(day.memoria));
  const hasTraffic = serie.some((day) => Number.isFinite(day.entrada_bps) || Number.isFinite(day.salida_bps));
  return (
    <div className="trend-charts">
      <figure>
        <figcaption>CPU y memoria · promedio diario de la red</figcaption>
        {hasUsage ? (
          <LineChart points={serie} series={USAGE} format={percent} max={100} xKey="dia" xLabel={dayLabel} label="CPU y memoria promedio por día" />
        ) : <small className="metric-history-empty">Sin lecturas históricas</small>}
      </figure>
      <figure>
        <figcaption>Tráfico total · promedio diario</figcaption>
        {hasTraffic ? (
          <LineChart points={serie} series={TRAFFIC} format={rate} xKey="dia" xLabel={dayLabel} label="Tráfico total promedio por día" />
        ) : <small className="metric-history-empty">Sin lecturas históricas</small>}
      </figure>
      <figure>
        <figcaption>Alertas nuevas</figcaption>
        <strong className="trend-total">{alerts}</strong>
        <small>{worst ? `Día con más alertas: ${dayLabel(worst.dia)} (${worst.alertas})` : "Sin alertas en el periodo"}</small>
      </figure>
    </div>
  );
}

/** Reportes para operación y para la dirección: en pantalla, CSV o impresos. */
// Reportes que viven en la sección Red (topología y equipos conectados).
export const NETWORK_REPORTS = ["topologia", "aps-telefonos"];

export default function Reports({ plantel = "", onOpenPort = () => {}, kinds = null, viewKey = "report", heading = true }) {
  const available = kinds ? REPORTS.filter(([id]) => kinds.includes(id)) : REPORTS.filter(([id]) => !NETWORK_REPORTS.includes(id));
  // El reporte abierto y sus parámetros se recuerdan como el resto de la vista.
  const [savedKind, setKind] = useViewState(viewKey, available[0][0]);
  const kind = available.some(([id]) => id === savedKind) ? savedKind : available[0][0];
  const [params, setParams] = useViewState("report-params", {});
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // Al imprimir se muestran todas las filas, no sólo la página visible de la tabla.
  const [printing, setPrinting] = useState(false);
  const current = available.find(([id]) => id === kind) || available[0];
  const param = current[2];
  const paramValue = param ? params[kind] ?? param.value : null;
  // El plantel global se suma a los parámetros del reporte (pantalla y CSV).
  const own = param ? `?${param.key}=${encodeURIComponent(paramValue)}` : "";
  const query = plantel ? `${own}${own ? "&" : "?"}plantel=${encodeURIComponent(plantel)}` : own;

  useEffect(() => {
    let active = true;
    // El reporte anterior queda en pantalla (atenuado) hasta que llegue el nuevo.
    setLoading(true);
    api.report(kind, query)
      .then((report) => active && (setData({ ...report, kind }), setError("")))
      .catch((exception) => active && setError(exception.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [kind, query]);

  useEffect(() => {
    const before = () => flushSync(() => setPrinting(true));
    const after = () => setPrinting(false);
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);

  // Al cambiar de reporte no se muestran columnas del anterior.
  const shown = data?.kind === kind ? data : null;
  const rows = useMemo(() => (data?.filas || []).map((row, index) => ({ ...row, _key: index })), [data]);
  const columns = (data?.columnas || []).map((column) => ({
    name: column.titulo,
    sortable: true,
    wrap: true,
    selector: (row) => row[column.clave] ?? "",
    cell: (row) => (column.clave === "tipo_equipo"
      ? <NeighborTypeLabel kind={row.vecino_tipo} label={row.tipo_equipo} />
      : cell(column.clave, row[column.clave])),
  }));
  if (data?.filas?.some((row) => row.puerto_id)) {
    columns.push({
      name: "",
      button: true,
      width: "120px",
      cell: (row) => row.puerto_id && (
        <button type="button" onClick={() => onOpenPort({ id: row.switch_id, nombre: row.switch, hostname: "" }, row.puerto_id)}>
          Ver puerto
        </button>
      ),
    });
  }

  const grouped = available.length > 1
    ? [
      ...GROUPS.map(([title, ids]) => [title, available.filter(([id]) => ids.includes(id))]),
      ["Otros", available.filter(([id]) => !GROUPS.some(([, ids]) => ids.includes(id)))],
    ].filter(([, items]) => items.length)
    : [];

  return (
    <>
      {heading && (
        <div className="section-title page-heading no-print">
          <div>
            <h2>Reportes</h2>
            <p>Consulta en pantalla, descarga en CSV o imprime como PDF.</p>
          </div>
        </div>
      )}
      <div className={grouped.length ? "reports-layout" : ""}>
      {grouped.length > 0 && (
        <nav className="report-nav no-print" aria-label="Reportes disponibles">
          {grouped.map(([title, items]) => (
            <div key={title} className="report-nav-group">
              <span className="report-nav-title">{title}</span>
              {items.map(([id, label]) => (
                <button key={id} type="button" className={kind === id ? "active" : ""} aria-current={kind === id ? "true" : undefined} onClick={() => setKind(id)}>{label}</button>
              ))}
            </div>
          ))}
        </nav>
      )}
      <section className="card report-card">
        <div className="section-title">
          <div>
            <h2>{shown?.titulo || current[1]}</h2>
            {shown?.descripcion && <small>{shown.descripcion}</small>}
          </div>
          <div className="report-actions no-print">
            {param?.options && (
              <label className="inline-field">
                {param.label}
                <select value={paramValue} onChange={(event) => setParams({ ...params, [kind]: event.target.value })}>
                  {param.options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
                </select>
              </label>
            )}
            {param && !param.options && (
              <label className="inline-field">
                {param.label}
                <input
                  type="number"
                  min="1"
                  max="365"
                  value={paramValue}
                  onChange={(event) => setParams({ ...params, [kind]: event.target.value })}
                />
              </label>
            )}
            <a className="button secondary" href={`/api/reportes/${kind}/${query ? `${query}&` : "?"}formato=csv`}>Descargar CSV</a>
            <button type="button" className="secondary" onClick={() => window.print()}>Imprimir / PDF</button>
          </div>
        </div>
        {error && <p role="alert">{error}</p>}
        {loading && (
          <p role="status" className="loading-line no-print">
            <i className="spinner" aria-hidden="true" />
            Generando reporte…
          </p>
        )}
        {!shown ? (
          loading && (
            <div className="skeleton-table" aria-hidden="true">
              {Array.from({ length: 6 }, (_, index) => <span key={index} className="skeleton" />)}
            </div>
          )
        ) : (
          <div className={loading ? "is-stale" : ""}>
            {kind === "topologia" && <TopologyMap rows={data.filas} onOpenPort={onOpenPort} />}
            {data.detalle && <p className="worker-alert" role="status">{data.detalle}</p>}
            {data.serie && <TrendCharts serie={data.serie} />}
            <p className="report-count">{data.filas.length} fila{data.filas.length === 1 ? "" : "s"}</p>
            <div className="table-scroll sonar-table">
              <SonarDataTable
                columns={columns}
                data={rows}
                keyField="_key"
                pagination={!printing}
                noDataComponent="Sin datos para este reporte."
              />
            </div>
          </div>
        )}
      </section>
      </div>
    </>
  );
}
