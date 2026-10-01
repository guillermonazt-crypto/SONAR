import { describe, it, expect, vi, afterEach } from "vitest";
import { api, endSession, request } from "./client";

const reply = (body, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

afterEach(() => vi.unstubAllGlobals());

describe("request", () => {
  it("devuelve el mismo objeto si el refresco trae lo mismo", async () => {
    const fetch = vi.fn()
      .mockImplementationOnce(() => reply([{ id: 1, cpu: 10 }]))
      .mockImplementationOnce(() => reply([{ id: 1, cpu: 10 }]))
      .mockImplementationOnce(() => reply([{ id: 1, cpu: 20 }]));
    vi.stubGlobal("fetch", fetch);
    const first = await request("dedupe-test/");
    const same = await request("dedupe-test/");
    const changed = await request("dedupe-test/");
    expect(same).toBe(first);
    expect(changed).not.toBe(first);
    expect(changed[0].cpu).toBe(20);
  });

  it("sigue lanzando el detalle de los errores", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply({ detail: "Inicia sesión para continuar." }, 403)));
    await expect(request("privado/")).rejects.toThrow("Inicia sesión para continuar.");
  });

  it("arma la consulta de alertas omitiendo filtros vacíos", async () => {
    const fetch = vi.fn(() => reply([]));
    vi.stubGlobal("fetch", fetch);
    await api.alerts(true, { plantel: "", tipo: "cpu" });
    await api.alerts(false, { plantel: 4, tipo: "all", estado: "cerradas" });
    expect(fetch.mock.calls[0][0]).toBe("/api/alertas/?estado=abiertas&tipo=cpu");
    expect(fetch.mock.calls[1][0]).toBe("/api/alertas/?limit=100&plantel=4&estado=cerradas");
  });

  it("pasa el plantel global a los listados, resumen, ópticas, búsqueda y mantenimientos", async () => {
    const fetch = vi.fn(() => reply([]));
    vi.stubGlobal("fetch", fetch);
    await api.list("switches", { plantel: "3" });
    await api.list("planteles");
    await api.summary(true, "3");
    await api.summary(false, "");
    await api.optics(false, 3);
    await api.search("aa:bb", "3");
    await api.alertSummary("3");
    await api.maintenances("3");
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/switches/?plantel=3",
      "/api/planteles/",
      "/api/resumen/?refresh=1&plantel=3",
      "/api/resumen/",
      "/api/opticas/?plantel=3",
      "/api/buscar/?q=aa%3Abb&plantel=3",
      "/api/alertas/resumen/?plantel=3",
      "/api/mantenimientos/?vigentes=1&plantel=3",
    ]);
  });
});

// fetch que sólo responde cuando se le pide; rechaza como el navegador al abortar.
function pendingFetch() {
  const calls = [];
  vi.stubGlobal("fetch", vi.fn((url, { signal }) => new Promise((resolve, reject) => {
    calls.push({ url, signal, resolve });
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  })));
  return calls;
}

describe("endSession", () => {
  it("cancela las peticiones en curso", async () => {
    const calls = pendingFetch();
    const summary = api.summary();
    const alerts = api.alertSummary();
    endSession();
    await expect(summary).rejects.toThrow("Aborted");
    await expect(alerts).rejects.toThrow("Aborted");
    expect(calls.every((call) => call.signal.aborted)).toBe(true);
    // Las peticiones nuevas (el propio logout) ya no quedan canceladas.
    const logout = api.logout();
    expect(calls.at(-1).signal.aborted).toBe(false);
    calls.at(-1).resolve(new Response(null, { status: 204 }));
    await expect(logout).resolves.toEqual({});
  });

  it("respeta la cancelación propia de cada vista", async () => {
    const calls = pendingFetch();
    const controller = new AbortController();
    const pending = request("resumen/", { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toThrow("Aborted");
    expect(calls[0].signal.aborted).toBe(true);
  });

  it("olvida las respuestas guardadas de la sesión anterior", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply({ switches: [1] })));
    const first = await request("sesion-test/");
    expect(await request("sesion-test/")).toBe(first);
    endSession();
    const next = await request("sesion-test/");
    expect(next).toEqual(first);
    expect(next).not.toBe(first);
  });
});
