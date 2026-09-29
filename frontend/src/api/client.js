let csrfToken = "";
// Última respuesta GET por ruta. Si el refresco trae exactamente lo mismo
// (normalmente un 304 revalidado por ETag), se devuelve el mismo objeto y
// React no vuelve a pintar la vista.
const lastGet = new Map();

export async function request(
  path,
  { method = "GET", data, form = false, signal } = {},
) {
  const headers = {};
  if (method !== "GET") headers["X-CSRFToken"] = csrfToken;
  if (data && !form) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/${path}`, {
    method,
    headers,
    credentials: "same-origin",
    signal,
    body: data
      ? form
        ? new URLSearchParams(data)
        : JSON.stringify(data)
      : undefined,
  });
  const text = await response.text().catch(() => "");
  if (response.ok && method === "GET" && lastGet.get(path)?.text === text) return lastGet.get(path).body;
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = {};
  }
  if (response.ok && method === "GET") {
    lastGet.delete(path);
    lastGet.set(path, { text, body });
    // Las búsquedas crean rutas nuevas: se conservan sólo las 50 más recientes.
    if (lastGet.size > 50) lastGet.delete(lastGet.keys().next().value);
  }
  if (!response.ok)
    throw new Error(
      body.detail ||
        Object.entries(body)
          .map(([key, value]) => `${key}: ${value}`)
          .join(" · ") ||
        "No se pudo completar la solicitud.",
    );
  if (body.csrfToken) csrfToken = body.csrfToken;
  return body;
}
export const api = {
  session: () => request("auth/session/"),
  login: (data) => request("auth/login/", { method: "POST", data, form: true }),
  logout: () => request("auth/logout/", { method: "POST" }),
  list: (resource) => request(`${resource}/`),
  save: (resource, data, id) =>
    request(`${resource}/${id ? `${id}/` : ""}`, {
      method: id ? "PATCH" : "POST",
      data,
    }),
  ports: (id) => request(`switches/${id}/puertos/`),
  zabbix: () => request("integrations/zabbix/"),
  portHistory: (id) => request(`puertos/${id}/historial/`),
  switchHistory: (id) => request(`switches/${id}/historial/`),
  summary: (refresh = false) => request(`resumen/${refresh ? "?refresh=1" : ""}`),
  optics: (refresh = false) => request(`opticas/${refresh ? "?refresh=1" : ""}`),
  search: (query) => request(`buscar/?q=${encodeURIComponent(query)}`),
  // filters: {plantel, tipo, estado: "abiertas" | "cerradas"}; los vacíos se omiten.
  alerts: (open = false, filters = {}) => {
    const params = new URLSearchParams(open ? { estado: "abiertas" } : { limit: "100" });
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== "" && value !== "all") params.set(key, value);
    });
    return request(`alertas/?${params}`);
  },
  alertSummary: () => request("alertas/resumen/"),
  acknowledge: (id, nota) => request(`alertas/${id}/reconocer/`, { method: "POST", data: { nota } }),
  maintenances: () => request("mantenimientos/?vigentes=1"),
  saveMaintenance: (data) => request("mantenimientos/", { method: "POST", data }),
  deleteMaintenance: (id) => request(`mantenimientos/${id}/`, { method: "DELETE" }),
  auditLog: () => request("bitacora/?limit=200"),
  report: (kind, query = "") => request(`reportes/${kind}/${query}`),
  discovered: () => request("descubiertos/"),
  ignoreDiscovered: (id) => request(`descubiertos/${id}/ignorar/`, { method: "POST" }),
  backups: (switchId) => request(`switches/${switchId}/respaldos/`),
  runBackup: (switchId) => request(`switches/${switchId}/respaldos/`, { method: "POST" }),
  backupDetail: (id) => request(`respaldos/${id}/`),
};
