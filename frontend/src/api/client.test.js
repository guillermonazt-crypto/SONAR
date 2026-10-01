import { describe, it, expect, vi, afterEach } from "vitest";
import { api, request } from "./client";

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
