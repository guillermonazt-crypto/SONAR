import { describe, it, expect, vi, afterEach } from "vitest";
import { api, endSession } from "./client";

afterEach(() => vi.unstubAllGlobals());

// fetch que sólo responde cuando se le pide; rechaza como el navegador al abortar.
function pendingFetch() {
  const calls = [];
  vi.stubGlobal("fetch", vi.fn((url, { signal }) => new Promise((resolve, reject) => {
    calls.push({ url, signal, resolve });
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  })));
  return calls;
}
const reply = (body, status = 200) => ({ ok: status < 400, status, text: () => Promise.resolve(body) });

describe("client", () => {
  it("al terminar la sesión cancela las peticiones en curso", async () => {
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
    calls.at(-1).resolve(reply("", 204));
    await expect(logout).resolves.toEqual({});
  });

  it("respeta la cancelación propia de cada vista", async () => {
    const calls = pendingFetch();
    const controller = new AbortController();
    const { request } = await import("./client");
    const pending = request("resumen/", { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toThrow("Aborted");
    expect(calls[0].signal.aborted).toBe(true);
  });

  it("olvida las respuestas guardadas de la sesión anterior", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(reply('{"switches":[1]}'))));
    const first = await api.summary();
    expect(await api.summary()).toBe(first);
    endSession();
    const next = await api.summary();
    expect(next).toEqual(first);
    expect(next).not.toBe(first);
  });
});
