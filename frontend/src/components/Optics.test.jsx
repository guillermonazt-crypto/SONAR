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
  rx_dbm: -4.2, tx_dbm: -2.1, temperatura: 35, atenuacion: 2.1, estado: "ok", rx_max_24h: -4, ...extra,
});
const limits = { rx_atencion: -17, rx_riesgo: -20, rx_saturacion: 0, tx_minimo: -9.5, temp_atencion: 65, temp_riesgo: 75, caida_rx: 3 };

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
    expect(screen.getByText(/no publican DOM/)).toBeInTheDocument();
  });
});
