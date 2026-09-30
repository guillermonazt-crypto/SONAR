// Menú lateral colapsable; el estado (abierto/compacto) se recuerda.
export const SECTIONS = [
  ["home", "Inicio", "◉"],
  ["status", "Estado", "▦"],
  ["alerts", "Alertas", "◬"],
  ["network", "Red", "⌬"],
  ["reports", "Reportes", "≡"],
  ["settings", "Configuración", "⚙"],
];

export default function Sidebar({ current, onSelect, collapsed, onToggle, pendingAlerts = 0, user, onLogout }) {
  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`} aria-label="Navegación principal">
      <div className="sidebar-brand">
        <span className="brand-mark" aria-hidden="true">⬡</span>
        {!collapsed && <span className="brand-name">SONAR</span>}
        <button type="button" className="sidebar-toggle" onClick={onToggle} aria-label={collapsed ? "Expandir menú" : "Contraer menú"} aria-expanded={!collapsed}>
          {collapsed ? "›" : "‹"}
        </button>
      </div>
      <nav className="sidebar-nav">
        {SECTIONS.map(([id, label, icon]) => (
          <button
            key={id}
            type="button"
            className={current === id ? "active" : ""}
            aria-current={current === id ? "page" : undefined}
            aria-label={label}
            title={collapsed ? label : undefined}
            onClick={() => onSelect(id)}
          >
            <span className="nav-icon" aria-hidden="true">{icon}</span>
            {!collapsed && <span className="nav-label">{label}</span>}
            {id === "alerts" && pendingAlerts > 0 && (
              <span className="nav-count" aria-label={`${pendingAlerts} sin atender`}>{pendingAlerts}</span>
            )}
          </button>
        ))}
      </nav>
      {user && (
        <div className="sidebar-foot">
          {!collapsed && (
            <span className="sidebar-user">
              <strong>{user.username}</strong>
              <small>{user.rol}</small>
            </span>
          )}
          <button type="button" className="text-button" onClick={onLogout} title="Cerrar sesión">
            {collapsed ? "⎋" : "Salir"}
          </button>
        </div>
      )}
    </aside>
  );
}
