const KEY = "sonar-plantel";

// Plantel elegido en la barra superior: filtra todas las pestañas y se recuerda
// entre sesiones (localStorage). "" = todos los planteles.
export function loadSite() {
  try {
    const saved = localStorage.getItem(KEY);
    return saved && /^\d+$/.test(saved) ? saved : "";
  } catch {
    return "";
  }
}

export function saveSite(value) {
  try {
    if (value) localStorage.setItem(KEY, String(value));
    else localStorage.removeItem(KEY);
  } catch {
    // Sin localStorage el filtro aplica igual, sólo no se recuerda.
  }
}

/** Parámetros de consulta sin los vacíos: {plantel: ""} → "". */
export function queryString(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "" && value !== "all") query.set(key, value);
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}
