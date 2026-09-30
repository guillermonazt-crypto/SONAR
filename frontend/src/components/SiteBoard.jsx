import { StatusBadge } from "./Status";

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

function SiteTile({ site, usage, selected, onSelect }) {
  const { niveles: levels, puertos: ports } = site;
  return (
    <button
      type="button"
      className={`site-tile site-${site.estado}${selected ? " selected" : ""}`}
      aria-pressed={selected}
      aria-label={`${site.nombre}: ${plural(site.equipos, "equipo")}`}
      onClick={() => onSelect(selected ? null : site.id)}
    >
      <span className="site-tile-head">
        <span>
          <strong>{site.nombre}</strong>
          <small>{site.division}</small>
        </span>
        <StatusBadge level={site.estado} />
      </span>
      <span className="site-tile-levels">
        {plural(site.equipos, "equipo")}
        {levels.critical > 0 && <span className="status-critical-text"> · {levels.critical} en riesgo</span>}
        {levels.warning > 0 && <span className="status-warning-text"> · {levels.warning} en atención</span>}
        {site.inactivos > 0 && <span> · {site.inactivos} desactivado{site.inactivos === 1 ? "" : "s"}</span>}
      </span>
      {site.equipos > 0 && (
        <span className="site-tile-kpis">
          <span><small>Responden</small><b>{site.disponibilidad}%</b></span>
          <span><small>Puertos activos</small><b>{ports.up}/{ports.total}</b></span>
          <span className={site.alertas_sin_reconocer ? "status-critical-text" : ""}>
            <small>Alertas abiertas</small><b>{site.alertas_abiertas}</b>
          </span>
          <span className={usage?.cpu >= 80 ? "status-warning-text" : ""}>
            <small>CPU</small><b>{usage?.cpu != null ? `${usage.cpu}%` : "—"}</b>
          </span>
          <span className={usage?.mem >= 85 ? "status-warning-text" : ""}>
            <small>Memoria</small><b>{usage?.mem != null ? `${usage.mem}%` : "—"}</b>
          </span>
        </span>
      )}
      {site.mantenimiento && <span className="status-badge status-maintenance">En mantenimiento</span>}
    </button>
  );
}

/** Tablero por plantel: el peor estado de sus equipos, alertas y KPIs; al elegir uno se filtra el análisis. */
export default function SiteBoard({ sites, usage = new Map(), selected, onSelect }) {
  if (!sites.length) return null;
  const withIssues = sites.filter((site) => site.estado === "critical" || site.estado === "warning").length;
  return (
    <section className="card site-board">
      <div className="section-title">
        <div>
          <h2>Estado por plantel</h2>
        </div>
        <small>{withIssues ? `${withIssues} de ${sites.length} con incidencias` : `${sites.length} planteles sin incidencias`}</small>
      </div>
      <div className="site-board-grid">
        {sites.map((site) => (
          <SiteTile key={site.id} site={site} usage={usage.get(site.id)} selected={selected === site.id} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}
