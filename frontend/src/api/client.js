let csrfToken = "";
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
  const body = await response.json().catch(() => ({}));
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
};
