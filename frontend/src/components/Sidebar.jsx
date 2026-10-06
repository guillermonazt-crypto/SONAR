import { useState } from "react";

// Menú lateral colapsable; el estado (abierto/compacto) se recuerda.
// En el celular (≤ 768 px) es una barra inferior: las cuatro primeras secciones y "Más".
export const SECTIONS = [
  ["home", "Inicio", "◉"],
  ["status", "Estado", "▦"],
  ["alerts", "Alertas", "◬"],
  ["network", "Red", "⌬"],
  ["reports", "Reportes", "≡"],
  ["settings", "Configuración", "⚙"],
];
const PRIMARY = ["home", "status", "alerts", "network"];

/** Hoja "Más" del celular: el resto de las secciones, la cuenta y el tema. */
function MoreSheet({ current, onSelect, onClose, user, onLogout, theme, onTheme }) {
  const choose = (id) => {
    onClose();
    onSelect(id);
  };
  return (
    <div className="sheet-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="sheet more-sheet" role="dialog" aria-modal="true" aria-labelledby="more-sheet-title">
        <div className="sheet-head">
          <h2 id="more-sheet-title">Más</h2>
          <button type="button" onClick={onClose}>Cerrar</button>
        </div>
        <ul className="more-list">
          {SECTIONS.filter(([id]) => !PRIMARY.includes(id)).map(([id, label, icon]) => (
            <li key={id}>
              <button type="button" className={current === id ? "active" : ""} aria-current={current === id ? "page" : undefined} onClick={() => choose(id)}>
                <span className="nav-icon" aria-hidden="true">{icon}</span>
                {label}
              </button>
            </li>
          ))}
          {onTheme && (
            <li>
              <button type="button" onClick={onTheme}>
                <span className="nav-icon" aria-hidden="true">{theme === "light" ? "☾" : "☀"}</span>
                {theme === "light" ? "Modo oscuro" : "Modo claro"}
              </button>
            </li>
          )}
        </ul>
        {user && (
          <div className="more-account">
            <span>
              <strong>{user.username}</strong>
              <small>{user.rol}</small>
            </span>
            <button type="button" onClick={() => { onClose(); onLogout(); }}>Cerrar sesión</button>
          </div>
        )}
      </section>
    </div>
  );
}

export default function Sidebar({ current, onSelect, collapsed, onToggle, pendingAlerts = 0, user, onLogout, theme, onTheme }) {
  const [more, setMore] = useState(false);
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
            className={`${current === id ? "active" : ""}${PRIMARY.includes(id) ? "" : " nav-secondary"}`}
            aria-current={current === id ? "page" : undefined}
            aria-label={label}
            title={collapsed ? label : undefined}
            onClick={() => onSelect(id)}
          >
            <span className="nav-icon" aria-hidden="true">{icon}</span>
            <span className="nav-label">{label}</span>
            {id === "alerts" && pendingAlerts > 0 && (
              <span className="nav-count" aria-label={`${pendingAlerts} sin atender`}>{pendingAlerts}</span>
            )}
          </button>
        ))}
        <button type="button" className={`nav-more${PRIMARY.includes(current) ? "" : " active"}`} aria-label="Más" aria-haspopup="dialog" aria-expanded={more} onClick={() => setMore(true)}>
          <span className="nav-icon" aria-hidden="true">⋯</span>
          <span className="nav-label">Más</span>
        </button>
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
      {more && <MoreSheet current={current} onSelect={onSelect} onClose={() => setMore(false)} user={user} onLogout={onLogout} theme={theme} onTheme={onTheme} />}
    </aside>
  );
}
