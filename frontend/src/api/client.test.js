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
});
