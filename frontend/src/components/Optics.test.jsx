import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, within } from "@testing-library/react";
import Optics from "./Optics";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { optics: vi.fn() } }));
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const sw = { id: 4, nombre: "SW-CORE", hostname: "192.0.2.30", plantel: 1, plantel_nombre: "Apan" };
const reading = (interfaz, nivel, motivos = [], extra = {}) => ({
  device: "SW-CORE", interfaz, nivel, motivos, switch: sw, puerto_id: 11, time: new Date().toISOString(),
  rx_dbm: -4.2, tx_dbm: -2.1, temperatura: 35, atenuacion: 2.1, estado: "ok", rx_base_dbm: -4, voltaje_v: 3.3, bias_ma: 5.1,
  niveles: { rx: "ok", tx: "ok", temp: "ok" }, umbrales: {}, ...extra,
});
const limits = { rx_atencion: -14, rx_riesgo: -17, rx_saturacion: 0, tx_minimo: -9.5, temp_atencion: 70, temp_riesgo: 75, caida_rx: 2 };
const module = { baja_alarma: -21, baja_aviso: -17, alta_aviso: 0, alta_alarma: 3, origen: "switch" };

describe("Optics", () => {
  it("lista transceptores con su nivel, filtra y abre el puerto", async () => {
    api.optics.mockResolvedValue({
      detalle: null, umbrales: limits,
      transceptores: [
        reading("Te1/1/2", "critical", [{ level: "critical", text: "RX -21.4 dBm (≤ -20)" }], { rx_dbm: -21.4 }),
        reading("Te1/1/1", "ok"),
      ],
    });
    const onOpenPort = vi.fn();
    render(<Optics onOpenPort={onOpenPort} />);
    expect(await screen.findByText("RX -21.4 dBm (≤ -20)")).toBeInTheDocument();
    expect(screen.getByText("-21.4 dBm")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "En riesgo (1)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Normales (1)" }));
    expect(screen.queryByText("RX -21.4 dBm (≤ -20)")).not.toBeInTheDocument();
    const row = screen.getByText("Te1/1/1 · Apan").closest(".rdt_TableRow");
    fireEvent.click(within(row).getByRole("button", { name: "Ver puerto" }));
    expect(onOpenPort).toHaveBeenCalledWith(sw, 11);
  });

  it("explica cuando InfluxDB no responde", async () => {
    api.optics.mockResolvedValue({ detalle: "Lecturas ópticas no disponibles: sin influx", umbrales: limits, transceptores: [] });
    render(<Optics />);
    expect(await screen.findByText(/sin influx/)).toBeInTheDocument();
    expect(screen.getByText(/no publican potencia óptica/)).toBeInTheDocument();
  });

  it("colorea cada métrica según su umbral y distingue puertos apagados", async () => {
    api.optics.mockResolvedValue({
      detalle: null, umbrales: limits,
      transceptores: [
        reading("Gi1/0/25", "critical", [{ level: "critical", text: "RX -21.5 dBm (≤ -21, umbral del módulo)" }], {
          rx_dbm: -21.5, niveles: { rx: "critical", tx: "ok", temp: "ok" }, umbrales: { rx: module },
        }),
        reading("Gi1/0/26", "ok", [{ level: "ok", text: "Puerto deshabilitado (shutdown): no se evalúa la óptica" }], {
          rx_dbm: -40, sin_senal: true, admin: "down",
        }),
      ],
    });
    render(<Optics />);
    const value = await screen.findByText("-21.5 dBm");
    expect(value).toHaveClass("status-critical-text");
    expect(screen.getByText("alarma ≤ -21 · aviso ≤ -17 · aviso ≥ 0 · alarma ≥ 3 dBm (módulo)")).toBeInTheDocument();
    expect(screen.getByText("base 7 d: -4.0 dBm")).toBeInTheDocument();
    expect(screen.getByText("Puerto deshabilitado")).toBeInTheDocument();
    expect(screen.getByText("-40.0 dBm")).not.toHaveClass("status-critical-text");
    expect(screen.getAllByText("5.1 mA")).toHaveLength(2);
  });
});
