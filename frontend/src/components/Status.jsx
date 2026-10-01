// Los niveles y motivos los calcula el backend (switches/health.py), el mismo
// código que dispara las alertas; aquí sólo se presentan.
export const LEVELS = {
  ok: { rank: 0, label: "Normal", icon: "●" },
  warning: { rank: 1, label: "Atención", icon: "▲" },
  critical: { rank: 2, label: "En riesgo", icon: "✕" },
  none: { rank: -1, label: "Sin equipos", icon: "○" },
};

// Conexión SNMP (switches/health.py): activo, iniciando (gracia tras arrancar el worker) o inactivo.
export const isOnline = (device) => (device.conexion ? device.conexion === "activo" : Boolean(device.lectura_correcta));

/** Aviso mientras el worker acaba de arrancar: ningún equipo pasa a rojo hasta su primer sondeo. */
export function StartingNotice({ summary }) {
  if (!summary?.monitoreo?.iniciando) return null;
  return <p role="status" className="status-warning-text">Iniciando monitoreo… los estados se confirman con el primer sondeo de cada switch.</p>;
}

export function StatusBadge({ level, connection }) {
  if (connection === "iniciando" && level !== "critical") {
    return <span className="status-badge status-warning"><span aria-hidden="true">◌</span> Iniciando monitoreo…</span>;
  }
  const key = LEVELS[level] ? level : "ok";
  const info = LEVELS[key];
  return <span className={`status-badge status-${key}`}><span aria-hidden="true">{info.icon}</span> {info.label}</span>;
}

// Tipos de motivo que asigna switches/health.py (y las condiciones compuestas).
export const REASON_TYPES = [
  ["snmp", "Sin respuesta SNMP"],
  ["lectura", "Lectura atrasada"],
  ["iniciando", "Iniciando monitoreo"],
  ["compuesta", "Condición compuesta"],
  ["cpu", "CPU"],
  ["memoria", "Memoria"],
  ["errores", "Errores de puerto"],
  ["inestables", "Puertos inestables"],
  ["saturacion", "Saturación"],
  ["hardware", "Hardware"],
  ["optica", "Ópticas SFP"],
  ["poe", "PoE"],
  ["reinicio", "Reinicio"],
];

export const hasReason = (reasons, type) => (reasons || []).some((reason) => reason.tipo === type);
