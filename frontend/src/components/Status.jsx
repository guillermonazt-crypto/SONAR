// Los niveles y motivos los calcula el backend (switches/health.py), el mismo
// código que dispara las alertas; aquí sólo se presentan.
export const LEVELS = {
  ok: { rank: 0, label: "Normal", icon: "●" },
  warning: { rank: 1, label: "Atención", icon: "▲" },
  critical: { rank: 2, label: "En riesgo", icon: "✕" },
  none: { rank: -1, label: "Sin equipos", icon: "○" },
};

export function StatusBadge({ level }) {
  const key = LEVELS[level] ? level : "ok";
  const info = LEVELS[key];
  return <span className={`status-badge status-${key}`}><span aria-hidden="true">{info.icon}</span> {info.label}</span>;
}
