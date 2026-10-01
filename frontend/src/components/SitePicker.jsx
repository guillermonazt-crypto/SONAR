const DIVISIONS = ["Institutos", "Escuelas Superiores", "Preparatorias"];

/** Elegir un plantel, agrupados por división (Institutos, Escuelas Superiores, Preparatorias). */
export default function SitePicker({ sites, onSelect, hint }) {
  const groups = new Map();
  [...sites]
    .sort((a, b) => a.nombre.localeCompare(b.nombre, "es", { numeric: true }))
    .forEach((site) => {
      const division = site.division_nombre || site.division || "Otros";
      const key = typeof division === "string" ? division : "Otros";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(site);
    });
  const ordered = [...groups.entries()].sort(([a], [b]) => {
    const ia = DIVISIONS.indexOf(a), ib = DIVISIONS.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  if (!sites.length) return <p className="empty">Cargando planteles…</p>;
  return (
    <div className="site-picker-grid">
      {hint && <p className="page-subtitle site-picker-hint">{hint}</p>}
      {ordered.map(([division, items]) => (
        <section key={division} className="panel site-picker-group" aria-label={division}>
          <h2 className="panel-title">{division}<small>{items.length}</small></h2>
          <ul>
            {items.map((site) => (
              <li key={site.id}>
                <button type="button" className="site-picker-item" onClick={() => onSelect(String(site.id))}>
                  <span>{site.nombre}</span>
                  <span aria-hidden="true" className="chevron">›</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
