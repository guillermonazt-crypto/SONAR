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
    const row = screen.getByText("Te1/1/1 · Apan").closest(".optic-card");
    fireEvent.click(within(row).getByRole("button", { name: "Ver puerto" }));
    expect(onOpenPort).toHaveBeenCalledWith(sw, 11);
  });

  it("muestra de entrada voltaje, bias, enlace, tendencia, errores y módulo", async () => {
    const serie = [-6.0, -6.1, -6.3, -6.4].map((rx, index) => ({ time: new Date(Date.now() - (3 - index) * 3600000).toISOString(), rx_dbm: rx, tx_dbm: -5.6 }));
    api.optics.mockResolvedValue({
      detalle: null, umbrales: limits,
      transceptores: [reading("Gi1/0/25", "warning", [{ level: "warning", text: "RX baja 0.80 dB/día: llegará a -24 dBm en ~6 días (revisar conectores o fibra)" }], {
        rx_dbm: -6.4, tx_dbm: -5.6, voltaje_v: 3.31, bias_ma: 4.6,
        niveles: { rx: "warning", tx: "ok", temp: "ok", voltaje: "ok", bias: "ok" },
        umbrales: { rx: module, voltaje: { baja_alarma: 2.97, baja_aviso: 3.14, alta_aviso: 3.47, alta_alarma: 3.63, origen: "switch" } },
        margen_rx_db: 17.6, objetivo_dbm: -24, perdida_enlace_db: 0.9,
        remoto: { switch: "SW_6_APAN_CASETA", puerto: "GigabitEthernet1/0/25", tx_dbm: -5.5 },
        delta_rx_24h: -0.4, delta_rx_7d: -1.2, serie,
        prediccion: { pendiente_db_dia: -0.8, eta_dias: 6, nivel: "warning", muestras: 120, objetivo_dbm: -24 },
        errores: { errores_crc: 17, errores_entrada: 20, errores_salida: 0, errores_nuevos: 3, ultimo_error: new Date().toISOString() },
        modulo: { modelo: "GLC-SX-MMD", serie: "AGJ1816R69C", revision: "V01", longitud_onda_nm: 850 },
      })],
    });
    render(<Optics />);
    const card = (await screen.findByText("GLC-SX-MMD · 850 nm · S/N AGJ1816R69C · rev. V01")).closest(".optic-card");
    const inCard = within(card);
    expect(inCard.getByText("3.31 V")).toBeInTheDocument();
    expect(inCard.getByText("alarma ≤ 2.97 · aviso ≤ 3.14 · aviso ≥ 3.47 · alarma ≥ 3.63 V (módulo)")).toBeInTheDocument();
    expect(inCard.getByText("4.6 mA")).toBeInTheDocument();
    expect(inCard.getByText("-6.4 dBm")).toHaveClass("status-warning-text");
    expect(inCard.getByText("+17.6 dB")).toBeInTheDocument();
    expect(inCard.getByText("0.9 dB")).toBeInTheDocument();
    expect(inCard.getByText(/TX remoto -5.5 dBm \(SW_6_APAN_CASETA GigabitEthernet1\/0\/25\)/)).toBeInTheDocument();
    expect(inCard.getByText("-0.40 dB")).toBeInTheDocument();
    expect(inCard.getByText("-1.20 dB")).toBeInTheDocument();
    expect(inCard.getByText("-0.80 dB/día")).toBeInTheDocument();
    expect(inCard.getByText("~6 días")).toHaveClass("status-warning-text");
    expect(inCard.getByText("RX -6.4 dBm a -6.0 dBm · TX -5.6 dBm a -5.6 dBm")).toBeInTheDocument();
    expect(inCard.getByText("17")).toHaveClass("status-warning-text");
    expect(inCard.getByText("3")).toHaveClass("status-critical-text");
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
