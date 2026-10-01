import { useEffect, useMemo, useRef, useState } from "react";
import { Chart, ArcElement, DoughnutController, Tooltip } from "chart.js";
import { cssVar, useTheme } from "../utils/theme";
import { neighborType } from "../utils/neighbor";
import "./reports.css";

Chart.register(ArcElement, DoughnutController, Tooltip);

// Lenguaje visual común de los reportes: rojo = problema, amarillo = advertencia,
// gris = información, verde = normal. Cada nivel tiene además su propia forma,
// para que no dependa sólo del color.
export const MARKS = {
  critical: { label: "Problema", shape: "circle" },
  warning: { label: "Advertencia", shape: "triangle" },
  info: { label: "Información", shape: "ring" },
  ok: { label: "Normal", shape: "circle" },
};

/** Marca de nivel (círculo, triángulo o anillo) con el motivo como tooltip. */
export function Mark({ level = "info", title }) {
  const mark = MARKS[level] || MARKS.info;
  return (
    <i
      className={`report-mark mark-${level} shape-${mark.shape}`}
      title={title || mark.label}
      role="img"
      aria-label={title || mark.label}
    />
  );
}

export function MarkLegend({ levels = ["critical", "warning", "info"], labels = {} }) {
  return (
    <div className="report-legend" aria-label="Leyenda de colores">
      {levels.map((level) => (
        <span key={level}>
          <Mark level={level} title={labels[level] || MARKS[level].label} />
          {labels[level] || MARKS[level].label}
        </span>
      ))}
    </div>
  );
}

/** Fila de indicadores: [etiqueta, valor, nivel opcional, nota opcional]. */
export function KpiTiles({ items }) {
  return (
    <div className="report-kpis">
      {items.map(([label, value, level, note]) => (
        <div key={label} className={`report-kpi${level ? ` tone-${level}` : ""}`} title={note || label}>
          <span>{level && <Mark level={level} title={note || MARKS[level].label} />}{label}</span>
          <strong>{value}</strong>
          {note && <small>{note}</small>}
        </div>
      ))}
    </div>
  );
}

/** Dona con los colores del tema: `slices` = [[etiqueta, valor, token de color]]. */
export function Donut({ slices, label, center }) {
  const canvas = useRef(null);
  const theme = useTheme();
  useEffect(() => {
    if (!canvas.current) return undefined;
    const chart = new Chart(canvas.current, {
      type: "doughnut",
      data: {
        labels: slices.map(([name]) => name),
        datasets: [{
          data: slices.map(([, value]) => value),
          backgroundColor: slices.map(([, , color]) => cssVar(color)),
          borderColor: cssVar("surface"),
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        cutout: "72%",
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => ` ${context.label}: ${context.raw}` } } },
      },
    });
    return () => chart.destroy();
  }, [slices, theme]);
  return (
    <figure className="report-donut">
      <div className="report-donut-canvas">
        <canvas ref={canvas} role="img" aria-label={label} />
        {center && <strong className="report-donut-center">{center}</strong>}
      </div>
      <figcaption>
        {slices.map(([name, value, color]) => (
          <span key={name}><i style={{ background: `var(--${color})` }} aria-hidden="true" />{name}<b>{value}</b></span>
        ))}
      </figcaption>
    </figure>
  );
}

/** Barras horizontales simples: `rows` = [{label, value, level, title}] sobre la escala [min, max]. */
export function BarList({ rows, min = 0, max = 100, format = (value) => value, scaleNote }) {
  return (
    <div className="report-bars">
      {rows.map((row) => {
        const width = Math.max(2, Math.min(100, ((row.value - min) * 100) / (max - min)));
        return (
          <div key={row.label} className="report-bar" title={row.title || `${row.label}: ${format(row.value)}`}>
            <span className="report-bar-label">{row.level && <Mark level={row.level} title={row.title} />}{row.label}</span>
            <span className="report-bar-track"><i className={`fill-${row.level || "info"}`} style={{ width: `${width}%` }} /></span>
            <b>{format(row.value)}</b>
          </div>
        );
      })}
      {scaleNote && <small className="report-scale-note">{scaleNote}</small>}
    </div>
  );
}

const average = (values) => (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null);

/** Inventario: indicadores de la red y reparto de switches por estado. */
export function InventorySummary({ rows }) {
  const summary = useMemo(() => {
    const active = rows.filter((row) => row.activo !== "No");
    const count = (level) => active.filter((row) => row.estado === level).length;
    const uptimes = active.map((row) => row.uptime_dias).filter(Number.isFinite).sort((a, b) => a - b);
    const ports = active.reduce((sum, row) => sum + (row.puertos || 0), 0);
    const up = active.reduce((sum, row) => sum + (row.activos || 0), 0);
    return {
      active: active.length,
      critical: count("critical"),
      warning: count("warning"),
      ok: count("ok"),
      uptime: uptimes.length ? uptimes[Math.floor(uptimes.length / 2)] : null,
      ports,
      up,
    };
  }, [rows]);
  const slices = useMemo(() => [
    ["Normal", summary.ok, "ok"],
    ["Atención", summary.warning, "warning"],
    ["En riesgo", summary.critical, "critical"],
  ], [summary]);
  return (
    <div className="report-summary">
      <KpiTiles items={[
        ["Switches activos", summary.active],
        ["En riesgo", summary.critical, summary.critical ? "critical" : null, "Switches con un problema activo"],
        ["Con atención", summary.warning, summary.warning ? "warning" : null, "Switches con una advertencia"],
        ["Puertos con enlace", `${summary.up} / ${summary.ports}`, null, summary.ports ? `${Math.round((summary.up * 100) / summary.ports)} % en uso` : null],
        ["Uptime mediano", summary.uptime === null ? "—" : `${summary.uptime} d`, null, "Días desde el último reinicio"],
      ]} />
      {summary.active > 0 && <Donut slices={slices} label="Switches por estado" center={summary.active} />}
    </div>
  );
}

const availabilityLevel = (value) => (value < 99 ? "critical" : value < 99.9 ? "warning" : "ok");
const pct = (value) => `${value.toFixed(value >= 99.9 || value < 10 ? 2 : 1)} %`;

/** Disponibilidad: indicadores y una barra por plantel (promedio de sus switches). */
export function AvailabilitySummary({ rows }) {
  const sites = useMemo(() => {
    const groups = new Map();
    rows.forEach((row) => {
      const site = groups.get(row.plantel) || { label: row.plantel || "Sin plantel", values: [], minutes: 0 };
      site.values.push(row.disponibilidad);
      site.minutes += row.minutos_caido || 0;
      groups.set(row.plantel, site);
    });
    return [...groups.values()]
      .map((site) => {
        const value = average(site.values);
        return {
          label: site.label,
          value,
          level: availabilityLevel(value),
          title: `${site.label}: ${pct(value)} · ${site.values.length} switch${site.values.length === 1 ? "" : "es"} · ${site.minutes} min sin respuesta`,
        };
      })
      .sort((a, b) => a.value - b.value || a.label.localeCompare(b.label));
  }, [rows]);
  if (!rows.length) return null;
  const overall = average(rows.map((row) => row.disponibilidad));
  const minutes = rows.reduce((sum, row) => sum + (row.minutos_caido || 0), 0);
  const affected = rows.filter((row) => row.minutos_caido > 0).length;
  // Las disponibilidades suelen estar por encima de 99 %: la escala arranca abajo del peor valor.
  const floor = Math.max(0, Math.min(99, Math.floor(Math.min(...sites.map((site) => site.value)) - 1)));
  return (
    <div className="report-summary vertical">
      <KpiTiles items={[
        ["Disponibilidad", pct(overall), availabilityLevel(overall), "Promedio de todos los switches"],
        ["Switches activos", rows.length],
        ["Con caídas", affected, affected ? "warning" : null, "Switches con minutos sin respuesta"],
        ["Minutos sin respuesta", minutes.toLocaleString("es-MX"), minutes ? "info" : null, "Suma de todos los switches"],
      ]} />
      {sites.length > 1 && (
        <figure className="report-figure">
          <figcaption>Disponibilidad por plantel</figcaption>
          <BarList rows={sites} min={floor} max={100} format={pct} scaleNote={`Escala de ${floor} % a 100 %`} />
          <MarkLegend levels={["ok", "warning", "critical"]} labels={{ ok: "99.9 % o más", warning: "99 % a 99.9 %", critical: "Menos de 99 %" }} />
        </figure>
      )}
    </div>
  );
}

// Rango del medidor de RX y umbral de fibra dañada.
const RX_MIN = -30;
const RX_MAX = 0;
export const RX_DAMAGED = -24;
const dbm = (value) => (Number.isFinite(value) ? `${value.toFixed(1)} dBm` : "—");

function opticLevel(row) {
  if (Number.isFinite(row.rx_dbm) && row.rx_dbm < RX_DAMAGED) return "critical";
  if (row.nivel === "critical") return "critical";
  if (row.nivel === "warning") return "warning";
  return "ok";
}

/** Ópticas: un medidor de RX por transceptor, agrupado por switch; rojo si RX < -24 dBm. */
export function OpticsBars({ rows }) {
  const groups = useMemo(() => {
    const bySwitch = new Map();
    rows.forEach((row) => bySwitch.set(row.switch, [...(bySwitch.get(row.switch) || []), row]));
    return [...bySwitch.entries()];
  }, [rows]);
  if (!rows.length) return null;
  const damaged = rows.filter((row) => Number.isFinite(row.rx_dbm) && row.rx_dbm < RX_DAMAGED).length;
  const warning = rows.filter((row) => opticLevel(row) === "warning").length;
  const rxValues = rows.map((row) => row.rx_dbm).filter(Number.isFinite);
  return (
    <div className="report-summary vertical">
      <KpiTiles items={[
        ["Transceptores", rows.length],
        ["RX bajo -24 dBm", damaged, damaged ? "critical" : null, "Posible fibra dañada o sucia"],
        ["Con advertencia", warning, warning ? "warning" : null, "Fuera del rango esperado"],
        ["RX más bajo", rxValues.length ? dbm(Math.min(...rxValues)) : "—"],
      ]} />
      <div className="optic-groups">
        {groups.map(([name, items]) => (
          <section key={name} className="optic-group">
            <h3>{name}</h3>
            {items.map((row) => {
              const level = opticLevel(row);
              const width = Number.isFinite(row.rx_dbm)
                ? Math.max(2, Math.min(100, ((row.rx_dbm - RX_MIN) * 100) / (RX_MAX - RX_MIN)))
                : 0;
              const reason = row.motivos || (level === "critical" ? "RX bajo el umbral de -24 dBm" : MARKS[level].label);
              return (
                <div key={row.puerto} className="optic-row" title={`${row.puerto} · RX ${dbm(row.rx_dbm)} · TX ${dbm(row.tx_dbm)} · ${reason}`}>
                  <span className="optic-port"><Mark level={level} title={reason} />{row.puerto}</span>
                  <span className="report-bar-track optic-track">
                    <i className={`fill-${level}`} style={{ width: `${width}%` }} />
                    <em className="optic-threshold" style={{ left: `${((RX_DAMAGED - RX_MIN) * 100) / (RX_MAX - RX_MIN)}%` }} aria-hidden="true" />
                  </span>
                  <span className="optic-values"><b>RX {dbm(row.rx_dbm)}</b><small>TX {dbm(row.tx_dbm)}</small></span>
                </div>
              );
            })}
          </section>
        ))}
      </div>
      <MarkLegend
        levels={["ok", "warning", "critical"]}
        labels={{ ok: "Señal normal", warning: "Advertencia", critical: "RX menor a -24 dBm (fibra dañada)" }}
      />
      <small className="report-scale-note">Medidor de RX de {RX_MIN} a {RX_MAX} dBm; la línea vertical marca {RX_DAMAGED} dBm.</small>
    </div>
  );
}

/** Tipo de equipo vecino con una marca de color en lugar de ícono. */
export function TypeLabel({ kind, label }) {
  const type = neighborType(kind);
  if (!type) return label || "—";
  return (
    <span className={`neighbor-type neighbor-${kind}`}>
      <i className="neighbor-dot" aria-hidden="true" /> {label || type.label}
    </span>
  );
}

const LINK = { up: ["ok", "Con enlace"], down: ["critical", "Sin enlace"] };
const PAGE = 48;

/** APs y teléfonos como tarjetas, con búsqueda por nombre/IP/modelo y filtro por VLAN. */
export function DeviceCards({ rows, onOpenPort, printing = false }) {
  const [search, setSearch] = useState("");
  const [vlan, setVlan] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const vlans = useMemo(
    () => [...new Set(rows.map((row) => row.vlan).filter((value) => value !== null && value !== undefined && value !== ""))]
      .sort((a, b) => Number(a) - Number(b)),
    [rows],
  );
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((row) => (!vlan || String(row.vlan) === vlan)
      && (!term || [row.vecino, row.vecino_ip, row.plataforma, row.switch, row.puerto, row.tipo_equipo]
        .some((value) => String(value ?? "").toLowerCase().includes(term))));
  }, [rows, search, vlan]);
  useEffect(() => setLimit(PAGE), [search, vlan, rows]);
  const visible = printing ? filtered : filtered.slice(0, limit);
  const down = rows.filter((row) => row.enlace === "down").length;
  return (
    <div className="device-report">
      <KpiTiles items={[
        ["Access points", rows.filter((row) => row.vecino_tipo === "ap").length],
        ["Teléfonos", rows.filter((row) => row.vecino_tipo === "telefono").length],
        ["Sin enlace", down, down ? "critical" : null, "Puerto del switch caído"],
        ["PoE total", `${rows.reduce((sum, row) => sum + (Number(row.poe_w) || 0), 0).toFixed(1)} W`],
      ]} />
      <div className="device-filters no-print">
        <input
          type="search"
          placeholder="Buscar por nombre, IP, modelo o switch"
          aria-label="Buscar equipo"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="inline-field">
          VLAN
          <select value={vlan} onChange={(event) => setVlan(event.target.value)}>
            <option value="">Todas</option>
            {vlans.map((value) => <option key={value} value={String(value)}>{value}</option>)}
          </select>
        </label>
        <MarkLegend levels={["ok", "critical", "info"]} labels={{ ok: "Con enlace", critical: "Sin enlace", info: "Sin lectura" }} />
      </div>
      {filtered.length === 0 ? (
        <p className="report-count">Ningún equipo coincide con la búsqueda.</p>
      ) : (
        <div className="device-cards">
          {visible.map((row) => {
            const [level, text] = LINK[row.enlace] || ["info", "Estado del puerto sin lectura"];
            return (
              <article key={row._key} className={`device-card kind-${row.vecino_tipo}`}>
                <header>
                  <Mark level={level} title={text} />
                  <div>
                    <strong title={row.vecino}>{row.vecino || "Sin nombre"}</strong>
                    <small>{neighborType(row.vecino_tipo)?.label || row.tipo_equipo}</small>
                  </div>
                </header>
                <dl>
                  <div><dt>IP</dt><dd>{row.vecino_ip || "—"}</dd></div>
                  <div><dt>Modelo</dt><dd title={row.plataforma}>{row.plataforma || "—"}</dd></div>
                  <div><dt>VLAN</dt><dd>{row.vlan ?? "—"}</dd></div>
                  <div><dt>PoE</dt><dd>{Number.isFinite(row.poe_w) ? `${row.poe_w} W` : "—"}</dd></div>
                </dl>
                <footer>
                  <small title={row.plantel}>{row.switch} · {row.puerto}</small>
                  {row.puerto_id && (
                    <button type="button" className="text-button no-print" onClick={() => onOpenPort({ id: row.switch_id, nombre: row.switch, hostname: "" }, row.puerto_id)}>
                      Ver puerto
                    </button>
                  )}
                </footer>
              </article>
            );
          })}
        </div>
      )}
      {!printing && filtered.length > limit && (
        <button type="button" className="secondary device-more no-print" onClick={() => setLimit(limit + PAGE)}>
          Mostrar más ({filtered.length - limit} restantes)
        </button>
      )}
    </div>
  );
}

const TOP = 10;
const portLabel = (row) => `${row.switch} · ${row.puerto}`;
const total = (rows, key) => rows.reduce((sum, row) => sum + (Number(row[key]) || 0), 0);

/** Los `TOP` renglones con mayor valor como barras, escaladas contra el máximo (o `max`). */
function TopBars({ title, rows, label, value, level, format = (v) => String(v), max, note }) {
  const ranked = rows
    .filter((row) => Number.isFinite(value(row)))
    .sort((a, b) => value(b) - value(a))
    .slice(0, TOP);
  if (!ranked.length) return null;
  const top = max ?? Math.max(...ranked.map(value), 1);
  return (
    <figure className="report-figure">
      <figcaption>{title}</figcaption>
      <BarList
        rows={ranked.map((row) => ({ label: label(row), value: value(row), level: level?.(row) || "info" }))}
        min={0}
        max={top}
        format={format}
        scaleNote={note || (rows.length > TOP ? `Los ${TOP} más altos de ${rows.length}` : null)}
      />
    </figure>
  );
}

/** Cuenta renglones por una clave: [{name, amount}]. */
function countBy(rows, key) {
  const counts = new Map();
  rows.forEach((row) => counts.set(row[key] || "Sin dato", (counts.get(row[key] || "Sin dato") || 0) + 1));
  return [...counts.entries()].map(([name, amount]) => ({ name, amount }));
}

function UnusedPorts({ rows }) {
  const never = rows.filter((row) => !Number.isFinite(row.dias)).length;
  const old = rows.filter((row) => row.dias >= 90).length;
  return (
    <div className="report-summary vertical">
      <KpiTiles items={[
        ["Puertos sin uso", rows.length, null, "Candidatos a reasignar"],
        ["Más de 90 días", old, old ? "warning" : null],
        ["Sin registro", never, never ? "info" : null, "Nunca vistos activos"],
        ["Switches", new Set(rows.map((row) => row.switch)).size],
      ]} />
      <TopBars title="Puertos libres por switch" rows={countBy(rows, "switch")} label={(row) => row.name} value={(row) => row.amount} />
    </div>
  );
}

function FlappingPorts({ rows }) {
  const down = rows.filter((row) => row.estado === "down").length;
  return (
    <div className="report-summary vertical">
      <KpiTiles items={[
        ["Puertos inestables", rows.length, "warning"],
        ["Cambios up/down", total(rows, "cambios")],
        ["Caídos ahora", down, down ? "critical" : null, "Último estado sin enlace"],
      ]} />
      <TopBars
        title="Cambios de estado por puerto"
        rows={rows}
        label={portLabel}
        value={(row) => row.cambios}
        level={(row) => (row.estado === "down" ? "critical" : "warning")}
      />
      <MarkLegend levels={["critical", "warning"]} labels={{ critical: "Caído ahora", warning: "Con enlace" }} />
    </div>
  );
}

const usageLevel = (value) => (value >= 90 ? "critical" : value >= 70 ? "warning" : "ok");
const percentText = (value) => `${Math.round(value)} %`;

function SaturatedPorts({ rows }) {
  const critical = rows.filter((row) => row.uso_pct >= 90).length;
  return (
    <div className="report-summary vertical">
      <KpiTiles items={[
        ["Puertos con uso alto", rows.length, "warning", "70 % o más"],
        ["Saturados", critical, critical ? "critical" : null, "90 % o más"],
        ["Troncales", rows.filter((row) => row.troncal === "Sí").length],
      ]} />
      <TopBars
        title="Uso por puerto"
        rows={rows}
        label={portLabel}
        value={(row) => row.uso_pct}
        level={(row) => usageLevel(row.uso_pct)}
        format={percentText}
        max={100}
      />
      <MarkLegend levels={["warning", "critical"]} labels={{ warning: "70 % a 89 %", critical: "90 % o más" }} />
    </div>
  );
}

function ErrorPorts({ rows }) {
  const errors = (row) => (Number(row.entrada) || 0) + (Number(row.salida) || 0);
  const fresh = rows.filter((row) => row.nuevos > 0).length;
  const crc = total(rows, "crc");
  return (
    <div className="report-summary vertical">
      <KpiTiles items={[
        ["Puertos con errores", rows.length, "warning"],
        ["Errores CRC", crc.toLocaleString("es-MX"), crc ? "critical" : null, "Suelen indicar cable o conector"],
        ["Errores de entrada", total(rows, "entrada").toLocaleString("es-MX")],
        ["Con errores nuevos", fresh, fresh ? "critical" : null, "En el último ciclo del worker"],
      ]} />
      <TopBars
        title="Errores acumulados por puerto"
        rows={rows}
        label={portLabel}
        value={errors}
        level={(row) => (row.nuevos > 0 ? "critical" : "warning")}
        format={(value) => value.toLocaleString("es-MX")}
      />
      <MarkLegend levels={["critical", "warning"]} labels={{ critical: "Con errores nuevos", warning: "Errores anteriores" }} />
    </div>
  );
}

function PoeSummary({ rows }) {
  const budget = total(rows, "presupuesto_w");
  const used = total(rows, "consumo_w");
  const faults = total(rows, "puertos_falla");
  const ready = rows.filter((row) => row.preparacion === "Listo").length;
  const usage = budget ? (used * 100) / budget : null;
  return (
    <div className="report-summary vertical">
      <KpiTiles items={[
        ["Consumo total", `${used.toFixed(0)} W`, null, budget ? `de ${budget.toFixed(0)} W de presupuesto` : null],
        ["Uso del presupuesto", usage === null ? "—" : percentText(usage), usage === null ? null : usageLevel(usage)],
        ["Puertos en falla", faults, faults ? "critical" : null, "El switch no puede energizar"],
        ["Switches con margen", `${ready} / ${rows.length}`, null, "Listos para más equipos PoE"],
      ]} />
      <TopBars
        title="Uso del presupuesto PoE por switch"
        rows={rows}
        label={(row) => row.switch}
        value={(row) => row.uso_pct}
        level={(row) => (row.puertos_falla || row.uso_pct >= 90 ? "critical" : row.uso_pct >= 75 ? "warning" : "ok")}
        format={percentText}
        max={100}
      />
      <MarkLegend levels={["ok", "warning", "critical"]} labels={{ ok: "Menos de 75 %", warning: "75 % a 89 %", critical: "90 % o más, o puertos en falla" }} />
    </div>
  );
}

function HardwareSummary({ rows }) {
  const count = (level) => rows.filter((row) => row.estado === level).length;
  const slices = useMemo(() => [
    ["Normal", rows.filter((row) => row.estado === "ok").length, "ok"],
    ["Advertencia", rows.filter((row) => row.estado === "warning").length, "warning"],
    ["Problema", rows.filter((row) => row.estado === "critical").length, "critical"],
  ], [rows]);
  const temperatures = rows.filter((row) => row.valor !== null && row.valor !== "" && Number.isFinite(Number(row.valor)));
  return (
    <div className="report-summary">
      <div className="report-summary vertical">
        <KpiTiles items={[
          ["Componentes", rows.length],
          ["Con problema", count("critical"), count("critical") ? "critical" : null],
          ["Con advertencia", count("warning"), count("warning") ? "warning" : null],
        ]} />
        <TopBars
          title="Temperatura más alta"
          rows={temperatures}
          label={(row) => `${row.switch} · ${row.componente}`}
          value={(row) => Number(row.valor)}
          level={(row) => (MARKS[row.estado] ? row.estado : "info")}
          format={(value) => `${value} °C`}
        />
      </div>
      <Donut slices={slices} label="Componentes por estado" center={rows.length} />
    </div>
  );
}

const SUMMARIES = {
  inventario: InventorySummary,
  disponibilidad: AvailabilitySummary,
  opticas: OpticsBars,
  "puertos-sin-uso": UnusedPorts,
  "puertos-inestables": FlappingPorts,
  "puertos-saturados": SaturatedPorts,
  "puertos-errores": ErrorPorts,
  poe: PoeSummary,
  hardware: HardwareSummary,
};

/** Reportes con resumen gráfico arriba de la tabla de detalle. */
export const SUMMARY_KINDS = Object.keys(SUMMARIES);

/** Resumen gráfico del reporte (indicadores y barras); nada si no hay filas. */
export function ReportSummary({ kind, rows }) {
  const Summary = SUMMARIES[kind];
  if (!Summary || !rows.length) return null;
  return <Summary rows={rows} />;
}
