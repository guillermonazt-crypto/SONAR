// Formateadores compartidos por Monitoreo y Resumen.

export function formatBytes(value) {
  if (!Number.isFinite(value)) return "Sin lectura";
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`;
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

export function formatRate(value, { digits = 2, empty = "Calculando…" } = {}) {
  if (!Number.isFinite(value)) return empty;
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(digits)} Gbps`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(digits)} Mbps`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(digits)} Kbps`;
  return `${Math.round(value)} bps`;
}

export function formatUptime(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "Sin lectura";
  const days = Math.floor(Number(value) / 86400);
  const hours = Math.floor((Number(value) % 86400) / 3600);
  return `${days}d ${hours}h`;
}

export function timeAgo(iso, now = Date.now()) {
  if (!iso) return "nunca";
  const minutes = Math.round((now - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "hace menos de 1 min";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} días`;
}
