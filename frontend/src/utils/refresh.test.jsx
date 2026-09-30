import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import RefreshControl from "../components/RefreshControl";
import {
  currentRefreshInterval,
  resetRefreshInterval,
  setRefreshInterval,
  useAutoRefresh,
} from "./refresh";

function Probe({ load, enabled = true }) {
  useAutoRefresh(load, enabled);
  return null;
}

function setVisibility(state) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  localStorage.clear();
  resetRefreshInterval();
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  setVisibility("visible");
});

describe("refresco automático", () => {
  it("usa 10 s por defecto y recuerda la elección", () => {
    expect(currentRefreshInterval()).toBe(10);
    setRefreshInterval(30);
    expect(localStorage.getItem("sonar-refresh")).toBe("30");
    resetRefreshInterval();
    expect(currentRefreshInterval()).toBe(30);
    localStorage.setItem("sonar-refresh", "7");
    resetRefreshInterval();
    expect(currentRefreshInterval()).toBe(10);
  });

  it("consulta al ritmo elegido y se puede desactivar", async () => {
    const load = vi.fn().mockResolvedValue();
    setRefreshInterval(3);
    render(<Probe load={load} />);
    await act(() => vi.advanceTimersByTimeAsync(9000));
    expect(load).toHaveBeenCalledTimes(3);

    act(() => setRefreshInterval(10));
    load.mockClear();
    await act(() => vi.advanceTimersByTimeAsync(20000));
    expect(load).toHaveBeenCalledTimes(2);

    act(() => setRefreshInterval(0));
    load.mockClear();
    await act(() => vi.advanceTimersByTimeAsync(60000));
    expect(load).not.toHaveBeenCalled();
  });

  it("no encima peticiones mientras una sigue en curso", async () => {
    let finish;
    const load = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
    render(<Probe load={load} />);
    await act(() => vi.advanceTimersByTimeAsync(12000));
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => finish());
    await act(() => vi.advanceTimersByTimeAsync(10000));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("se pausa con la pestaña oculta y refresca al volver", async () => {
    const load = vi.fn().mockResolvedValue();
    render(<Probe load={load} />);
    setVisibility("hidden");
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(load).not.toHaveBeenCalled();
    await act(async () => setVisibility("visible"));
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("no consulta cuando la vista lo deshabilita", async () => {
    const load = vi.fn().mockResolvedValue();
    render(<Probe load={load} enabled={false} />);
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(load).not.toHaveBeenCalled();
  });

  it("el selector del encabezado cambia el intervalo y muestra el estado", () => {
    render(<RefreshControl />);
    const select = screen.getByLabelText("Refresco automático");
    expect(select).toHaveValue("10");
    expect(screen.getByText("En vivo")).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "0" } });
    expect(currentRefreshInterval()).toBe(0);
    expect(screen.getByText("Pausado")).toBeInTheDocument();
    expect(select.closest("label")).toHaveClass("refresh-paused");
  });
});
