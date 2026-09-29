import { useEffect, useMemo, useState } from "react";
import { flushSync } from "react-dom";
import { api } from "../api/client";
import { formatRate } from "../utils/format";
import SonarDataTable from "./DataTable";

// [tipo, etiqueta, parámetro opcional {clave, etiqueta, valor}]
const REPORTS = [
  ["inventario", "Inventario"],
  ["disponibilidad", "Disponibilidad", { key: "dias", label: "Días", value: 30 }],
  ["puertos-sin-uso", "Puertos sin uso", { key: "dias", label: "Días sin enlace", value: 30 }],
  ["puertos-inestables", "Puertos inestables", { key: "horas", label: "Horas", value: 24 }],
  ["puertos-saturados", "Puertos saturados"],
  ["puertos-errores", "Puertos con errores", { key: "dias", label: "Días", value: 7 }],
  ["poe", "PoE"],
  ["hardware", "Hardware"],
  ["opticas", "Ópticas"],
  ["topologia", "Topología"],
];
const LEVEL_TEXT = { ok: "Normal", warning: "Atención", critical: "En riesgo" };

function cell(key, value) {
  if (value === null || value === undefined || value === "") return "—";
  if (key === "estado" || key === "nivel") {
    return LEVEL_TEXT[value] ? <span className={`status-badge status-${value}`}>{LEVEL_TEXT[value]}</span> : value;
  }
  if (key.endsWith("_bps")) return formatRate(value);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return new Date(value).toLocaleString();
  return String(value);
}

/** Mapa simple de enlaces CDP: nodos en círculo y una línea por enlace. */
function TopologyMap({ rows }) {
  const { nodes, links } = useMemo(() => {
    const names = new Map();
    const label = (row, side) => (side === "local" ? row.switch : row.vecino.split(".")[0]);
    rows.forEach((row) => {
      names.set(row.switch, { name: row.switch, known: true });
      const neighbor = label(row, "neighbor");
      if (!names.has(neighbor)) names.set(neighbor, { name: neighbor, known: row.en_inventario === "Sí" });
    });
    const list = [...names.values()];
    const radius = Math.max(120, list.length * 14);
    const size = radius * 2 + 180;
    list.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / list.length - Math.PI / 2;
      node.x = size / 2 + radius * Math.cos(angle);
      node.y = size / 2 + radius * Math.sin(angle);
    });
    const byName = new Map(list.map((node) => [node.name, node]));
    const seen = new Set();
    const edges = [];
    rows.forEach((row) => {
      const a = row.switch;
      const b = label(row, "neighbor");
      const key = [a, b].sort().join("|");
      if (seen.has(key)) return;
      seen.add(key);
      edges.push({ from: byName.get(a), to: byName.get(b), key });
    });
    return { nodes: { list, size }, links: edges };
  }, [rows]);
  if (!nodes.list.length) return null;
  return (
    <svg className="topology-map" viewBox={`0 0 ${nodes.size} ${nodes.size}`} role="img" aria-label="Mapa de enlaces CDP">
      {links.map((link) => (
        <line key={link.key} x1={link.from.x} y1={link.from.y} x2={link.to.x} y2={link.to.y} className="topology-link" />
      ))}
      {nodes.list.map((node) => (
        <g key={node.name} transform={`translate(${node.x} ${node.y})`}>
          <circle r="9" className={node.known ? "topology-node" : "topology-node external"} />
          <text y="-14" textAnchor="middle" className="topology-label">{node.name}</text>
        </g>
      ))}
    </svg>
  );
}

/** Reportes para operación y para la dirección: en pantalla, CSV o impresos. */
export default function Reports({ onOpenPort = () => {} }) {
  const [kind, setKind] = useState("inventario");
  const [params, setParams] = useState({});
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  // Al imprimir se muestran todas las filas, no sólo la página visible de la tabla.
  const [printing, setPrinting] = useState(false);
  const current = REPORTS.find(([id]) => id === kind);
  const param = current[2];
  const paramValue = param ? params[kind] ?? param.value : null;
  const query = param ? `?${param.key}=${encodeURIComponent(paramValue)}` : "";

  useEffect(() => {
    let active = true;
    setData(null);
    api.report(kind, query)
      .then((report) => active && (setData(report), setError("")))
      .catch((exception) => active && setError(exception.message));
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

  const rows = useMemo(() => (data?.filas || []).map((row, index) => ({ ...row, _key: index })), [data]);
  const columns = (data?.columnas || []).map((column) => ({
    name: column.titulo,
    sortable: true,
    wrap: true,
    selector: (row) => row[column.clave] ?? "",
    cell: (row) => cell(column.clave, row[column.clave]),
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

  return (
    <>
      <div className="section-title page-heading no-print">
        <div>
          <span className="eyebrow">INFORMES</span>
          <h2>Reportes</h2>
          <p>Consulta en pantalla, descarga en CSV (Excel) o imprime / guarda como PDF.</p>
        </div>
      </div>
      <div className="filter-row report-picker no-print">
        {REPORTS.map(([id, label]) => (
          <button key={id} type="button" className={kind === id ? "active" : ""} onClick={() => setKind(id)}>{label}</button>
        ))}
      </div>
      <section className="card report-card">
        <div className="section-title">
          <div>
            <h2>{data?.titulo || current[1]}</h2>
            {data?.descripcion && <small>{data.descripcion}</small>}
          </div>
          <div className="report-actions no-print">
            {param && (
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
            <a className="button" href={`/api/reportes/${kind}/${query ? `${query}&` : "?"}formato=csv`}>Descargar CSV</a>
            <button type="button" onClick={() => window.print()}>Imprimir / PDF</button>
          </div>
        </div>
        {error && <p role="alert">{error}</p>}
        {!data && !error ? (
          <p role="status">Generando reporte…</p>
        ) : data ? (
          <>
            {kind === "topologia" && <TopologyMap rows={data.filas} />}
            <p className="report-count">{data.filas.length} fila{data.filas.length === 1 ? "" : "s"} · generado {new Date().toLocaleString()}</p>
            <div className="table-scroll sonar-table">
              <SonarDataTable
                columns={columns}
                data={rows}
                keyField="_key"
                pagination={!printing}
                noDataComponent="Sin datos para este reporte."
              />
            </div>
          </>
        ) : null}
      </section>
    </>
  );
}
