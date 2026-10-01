import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act, waitFor } from "@testing-library/react";
import Noc, { newlyCritical } from "./Noc";
import { api } from "../api/client";
import { notify, playAlarm } from "../utils/alarm";
import { currentRefreshInterval, resetRefreshInterval, setRefreshInterval } from "../utils/refresh";

vi.mock("./NocMap", () => ({ default: ({ points }) => <div data-testid="noc-map">{points.length} puntos</div> }));
vi.mock("../api/client", () => ({ api: { summary: vi.fn() } }));
vi.mock("../utils/alarm", () => ({ playAlarm: vi.fn(), notify: vi.fn(), requestNotifications: vi.fn(() => Promise.resolve("granted")) }));

const site = (id, nombre, estado, extra = {}) => ({
  id, nombre, division: "Escuelas Superiores", estado, equipos: 2, inactivos: 0,
  niveles: { ok: 2, warning: 0, critical: 0 }, puertos: { total: 48, up: 30 },
  alertas_abiertas: 0, alertas_sin_reconocer: 0, disponibilidad: 100, ...extra,
});
// El NOC arranca en la disponibilidad global; el detalle se abre con un clic.
const openDetail = async () => fireEvent.click(await screen.findByRole("button", { name: /Disponibilidad global .*Ver detalle/ }));
const summary = (planteles, switches = []) => ({ generado: null, ultima_lectura: new Date().toISOString(), umbrales: {}, planteles, switches });

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  resetRefreshInterval();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Panel NOC", () => {
  it("muestra disponibilidad, switches en línea, alertas y planteles por estado", async () => {
    api.summary.mockResolvedValue(summary(
      [site(9, "Escuela Superior Apan", "critical", { alertas_abiertas: 3, alertas_sin_reconocer: 2 }), site(8, "Escuela Superior Actopan", "ok"), site(1, "Instituto Nuevo", "warning")],
      [{ id: 1, activo: true, lectura_correcta: true }, { id: 2, activo: true, lectura_correcta: true }, { id: 3, activo: true, lectura_correcta: true }, { id: 4, activo: true, lectura_correcta: false }, { id: 5, activo: false, lectura_correcta: false }],
    ));
    render(<Noc refreshSeconds={10} />);
    expect(await screen.findByText("75%")).toBeInTheDocument();
    expect(screen.getByText("3/4 switches responden · 1 plantel en rojo · 2 alertas sin reconocer")).toBeInTheDocument();
    // Sin paginación ni tablas al arrancar: una sola métrica.
    expect(screen.queryByRole("button", { name: /: (Crítico|Atención|Sano)$/ })).toBeNull();
    await openDetail();
    expect(screen.getByText("3/4")).toBeInTheDocument();
    expect(screen.getByText("1 sin respuesta")).toBeInTheDocument();
    expect(screen.getByText("2 sin reconocer")).toBeInTheDocument();
    expect(api.summary).toHaveBeenCalledWith(false, "");
    // Rojos primero en la lista; sólo los planteles con ubicación conocida van al mapa.
    const buttons = screen.getAllByRole("button", { name: /: (Crítico|Atención|Sano)$/ });
    expect(buttons[0]).toHaveAccessibleName("Escuela Superior Apan: Crítico");
    expect(buttons[1]).toHaveAccessibleName("Instituto Nuevo: Atención");
    expect(await screen.findByTestId("noc-map")).toHaveTextContent("2 puntos");
  });

  it("suena y avisa cuando un plantel pasa a rojo, no en la primera lectura", async () => {
    api.summary
      .mockResolvedValueOnce(summary([site(9, "Escuela Superior Apan", "ok"), site(8, "Escuela Superior Actopan", "critical")]))
      .mockResolvedValue(summary([site(9, "Escuela Superior Apan", "critical"), site(8, "Escuela Superior Actopan", "critical")]));
    const onOpenSite = vi.fn();
    render(<Noc refreshSeconds={10} onOpenSite={onOpenSite} />);
    await openDetail();
    await screen.findByText("Escuela Superior Actopan");
    expect(playAlarm).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(10000));
    await waitFor(() => expect(playAlarm).toHaveBeenCalledTimes(1));
    expect(notify).toHaveBeenCalledWith("SONAR · plantel en rojo", "Escuela Superior Apan pasó a estado crítico.");
    const banner = screen.getByText("pasó a crítico", { exact: false }).closest(".noc-incident");
    expect(banner).toHaveTextContent("Escuela Superior Apan");
    fireEvent.click(screen.getByRole("button", { name: "Ver plantel" }));
    expect(onOpenSite).toHaveBeenCalledWith(9);
    fireEvent.click(screen.getByRole("button", { name: "Descartar aviso de Escuela Superior Apan" }));
    expect(document.querySelector(".noc-incident")).toBeNull();
    // Sigue en rojo: no vuelve a sonar.
    await act(() => vi.advanceTimersByTimeAsync(10000));
    expect(playAlarm).toHaveBeenCalledTimes(1);
  });

  it("con la alarma silenciada sólo muestra el aviso", async () => {
    api.summary
      .mockResolvedValueOnce(summary([site(9, "Escuela Superior Apan", "warning")]))
      .mockResolvedValue(summary([site(9, "Escuela Superior Apan", "critical")]));
    const onSound = vi.fn();
    render(<Noc refreshSeconds={10} sound={false} onSound={onSound} />);
    await openDetail();
    await screen.findByText("Escuela Superior Apan");
    await act(() => vi.advanceTimersByTimeAsync(10000));
    await waitFor(() => expect(document.querySelector(".noc-incident")).not.toBeNull());
    expect(playAlarm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "🔕 Silenciada" }));
    expect(onSound).toHaveBeenCalledWith(true);
  });

  it("cambia la frecuencia de actualización entre 3, 10 y 30 s", async () => {
    api.summary.mockResolvedValue(summary([]));
    setRefreshInterval(10);
    const { rerender } = render(<Noc refreshSeconds={10} />);
    expect(screen.getByRole("button", { name: "10 s" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "30 s" }));
    expect(currentRefreshInterval()).toBe(30);
    expect(localStorage.getItem("sonar-refresh")).toBe("30");
    rerender(<Noc refreshSeconds={30} />);
    expect(screen.getByRole("button", { name: "30 s" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(api.summary).toHaveBeenCalled());
  });

  it("profundiza por clic y el botón atrás vuelve a la métrica global", async () => {
    api.summary.mockResolvedValue(summary([site(9, "Escuela Superior Apan", "ok")], [{ id: 1, activo: true, lectura_correcta: true }]));
    const { unmount } = render(<Noc refreshSeconds={10} />);
    expect(await screen.findByText("100%")).toBeInTheDocument();
    await openDetail();
    expect(screen.getByRole("button", { name: "Escuela Superior Apan: Sano" })).toBeInTheDocument();
    // Al volver de un plantel el detalle sigue abierto.
    unmount();
    render(<Noc refreshSeconds={10} />);
    expect(await screen.findByRole("button", { name: "Escuela Superior Apan: Sano" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Disponibilidad global" }));
    expect(screen.queryByRole("button", { name: "Escuela Superior Apan: Sano" })).toBeNull();
    expect(screen.getByRole("button", { name: /Disponibilidad global 100%/ })).toBeInTheDocument();
  });

  it("detecta sólo las transiciones a crítico", () => {
    const sites = [site(1, "A", "critical"), site(2, "B", "critical"), site(3, "C", "ok")];
    expect(newlyCritical(null, sites)).toEqual([]);
    const previous = new Map([[1, "ok"], [2, "critical"], [3, "warning"]]);
    expect(newlyCritical(previous, sites).map((item) => item.id)).toEqual([1]);
  });
});
