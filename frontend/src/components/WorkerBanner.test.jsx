import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, act } from "@testing-library/react";
import WorkerBanner, { WORKER_CHECK_MS } from "./WorkerBanner";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { monitoring: vi.fn() } }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const status = (extra = {}) => ({ latido: new Date().toISOString(), worker_offline: false, influx: { disponible: true, en_cola: 0 }, ...extra });

describe("Aviso del worker", () => {
  it("no muestra nada con el worker latiendo", async () => {
    api.monitoring.mockResolvedValue(status());
    const { container } = render(<WorkerBanner />);
    await act(() => Promise.resolve());
    expect(api.monitoring).toHaveBeenCalledTimes(1);
    expect(container).toBeEmptyDOMElement();
  });

  it("avisa datos congelados cuando falta el latido y se quita al volver", async () => {
    api.monitoring.mockResolvedValueOnce(status({ worker_offline: true, latido: new Date(Date.now() - 10 * 60000).toISOString() }))
      .mockResolvedValue(status());
    render(<WorkerBanner />);
    expect(await screen.findByRole("alert")).toHaveTextContent("⚠ Worker offline, datos congelados · último latido hace 10 min");
    await act(() => vi.advanceTimersByTimeAsync(WORKER_CHECK_MS));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("muestra las métricas en cola si InfluxDB cayó", async () => {
    api.monitoring.mockResolvedValue(status({ influx: { disponible: false, en_cola: 120 } }));
    render(<WorkerBanner />);
    expect(await screen.findByRole("status")).toHaveTextContent("InfluxDB sin conexión: 120 métricas en cola");
  });

  it("sin respuesta del backend no inventa el aviso", async () => {
    api.monitoring.mockRejectedValue(new Error("offline"));
    const { container } = render(<WorkerBanner />);
    await act(() => Promise.resolve());
    expect(container).toBeEmptyDOMElement();
  });
});
