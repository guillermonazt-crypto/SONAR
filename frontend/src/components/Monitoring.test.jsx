import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import Monitoring from "./Monitoring";
import { api } from "../api/client";
import { resetRefreshInterval, setRefreshInterval } from "../utils/refresh";

vi.mock("../api/client", () => ({
  api: { list: vi.fn(), ports: vi.fn(), portHistory: vi.fn() },
}));

const device = { id: 1, nombre: "SW-LAB", hostname: "192.0.2.1", plantel_nombre: "Lab", activo: true, lectura_correcta: true };
const port = (estado) => ({
  id: 7, indice: 1, nombre: "GigabitEthernet1/0/1", estado_operativo: estado, es_trunk: false,
  errores_entrada: 0, errores_salida: 0, errores_crc: 0, actualizado: new Date().toISOString(),
});

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  resetRefreshInterval();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  api.list.mockResolvedValue([device]);
  api.portHistory.mockResolvedValue({ points: [] });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Monitoring con refresco automático", () => {
  it("refresca switches y puertos sin cerrar el panel abierto", async () => {
    api.ports.mockResolvedValueOnce([port("up")]).mockResolvedValue([port("down")]);
    render(<Monitoring />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver puertos" }));
    expect(await screen.findByRole("button", { name: /GigabitEthernet1\/0\/1: Activo/ })).toBeInTheDocument();
    const listCalls = api.list.mock.calls.length;

    await act(() => vi.advanceTimersByTimeAsync(3000));

    expect(api.list.mock.calls.length).toBeGreaterThan(listCalls);
    expect(api.ports).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /GigabitEthernet1\/0\/1: Inactivo/ })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("tras recargar la página vuelve a abrir el switch y el puerto que se estaban viendo", async () => {
    api.ports.mockResolvedValue([port("up")]);
    const first = render(<Monitoring />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver puertos" }));
    fireEvent.click(await screen.findByRole("button", { name: /GigabitEthernet1\/0\/1: Activo/}));
    expect(await screen.findByRole("heading", { name: "GigabitEthernet1/0/1" })).toBeInTheDocument();
    first.unmount();

    render(<Monitoring />);
    expect(await screen.findByRole("heading", { name: "Puertos · SW-LAB" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "GigabitEthernet1/0/1" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    cleanup();
    render(<Monitoring />);
    await screen.findByText("SW-LAB");
    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("un fallo al refrescar no cierra el switch abierto", async () => {
    api.ports.mockResolvedValueOnce([port("up")]).mockRejectedValue(new Error("Sin conexión"));
    render(<Monitoring />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver puertos" }));
    await screen.findByRole("button", { name: /GigabitEthernet1\/0\/1: Activo/});
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /GigabitEthernet1\/0\/1: Activo/})).toBeInTheDocument();
  });

  it("muestra el estado de salud y los motivos de cada switch", async () => {
    api.list.mockResolvedValue([
      { ...device, estado: "critical", motivos: [{ level: "critical", text: "No responde a SNMP" }] },
      { ...device, id: 2, nombre: "SW-OK", estado: "ok", motivos: [] },
      { ...device, id: 3, nombre: "SW-OFF", activo: false, estado: "ok", motivos: [] },
    ]);
    render(<Monitoring />);
    expect(await screen.findByText("No responde a SNMP")).toBeInTheDocument();
    expect(screen.getByText("En riesgo")).toBeInTheDocument();
    expect(screen.getByText("Normal")).toBeInTheDocument();
    expect(screen.getByText("Inactivo")).toBeInTheDocument();
    expect(screen.getByText("1 en riesgo")).toBeInTheDocument();
  });

  it("muestra vecino CDP, uso, último cambio y PoE en el detalle del puerto", async () => {
    api.ports.mockResolvedValue([{
      ...port("down"), vecino_nombre: "SW-DIST", vecino_puerto: "Te1/1/4", vecino_plataforma: "cisco C9500", vecino_ip: "10.0.0.2",
      velocidad_mbps: 1000, uso_pct: 93.5, bps_entrada: 935000000, bps_salida: 1000,
      ultimo_cambio: new Date(Date.now() - 2 * 3600e3).toISOString(), ultimo_activo: "2026-01-01T10:00:00Z",
      poe_estado: "deliveringPower", poe_mw: 6500,
    }]);
    render(<Monitoring focus={{ device, portId: 7 }} />);
    expect(await screen.findByText("SW-DIST")).toBeInTheDocument();
    expect(screen.getByText("cisco C9500 · 10.0.0.2")).toBeInTheDocument();
    expect(screen.getByText(/93\.5% de uso/)).toHaveClass("status-critical-text");
    expect(screen.getByText("hace 2 h")).toBeInTheDocument();
    expect(screen.getByText(/Sin enlace desde/)).toBeInTheDocument();
    expect(screen.getByText(/Entregando energía · 6\.5 W/)).toBeInTheDocument();
  });

  it("abre directamente el puerto pedido desde el buscador", async () => {
    api.ports.mockResolvedValue([port("up")]);
    render(<Monitoring focus={{ device, portId: 7 }} />);
    expect(await screen.findByRole("heading", { name: "Puertos · SW-LAB" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "GigabitEthernet1/0/1" })).toBeInTheDocument();
  });

  it("no consulta de nuevo con el refresco desactivado", async () => {
    setRefreshInterval(0);
    render(<Monitoring />);
    await screen.findByText("SW-LAB");
    await act(() => vi.advanceTimersByTimeAsync(60000));
    expect(api.list).toHaveBeenCalledTimes(1);
  });
});
