import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import Reports from "./Reports";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { report: vi.fn() } }));
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const report = (tipo, columnas, filas, titulo = tipo) => ({ tipo, titulo, descripcion: "", columnas, filas });

describe("Reports", () => {
  it("muestra el inventario, cambia de reporte con parámetros y ofrece CSV", async () => {
    api.report.mockImplementation((kind, query) => Promise.resolve(kind === "inventario"
      ? report(kind, [{ clave: "switch", titulo: "Switch" }, { clave: "estado", titulo: "Estado" }],
        [{ switch: "SW-CORE", estado: "critical" }], "Inventario de switches")
      : report(kind, [{ clave: "switch", titulo: "Switch" }, { clave: "puerto", titulo: "Puerto" }],
        [{ switch: "SW-ACC", switch_id: 2, puerto: "Gi1/0/7", puerto_id: 70 }], `Puertos sin uso ${query}`)));
    const onOpenPort = vi.fn();
    render(<Reports onOpenPort={onOpenPort} />);
    expect(await screen.findByText("SW-CORE")).toBeInTheDocument();
    expect(screen.getByText("En riesgo")).toHaveClass("status-critical");
    fireEvent.click(screen.getByRole("button", { name: "Puertos sin uso" }));
    expect(await screen.findByText("Gi1/0/7")).toBeInTheDocument();
    expect(api.report).toHaveBeenLastCalledWith("puertos-sin-uso", "?dias=30");
    expect(screen.getByRole("link", { name: "Descargar CSV" })).toHaveAttribute("href", "/api/reportes/puertos-sin-uso/?dias=30&formato=csv");
    fireEvent.change(screen.getByLabelText("Días sin enlace"), { target: { value: "90" } });
    await waitFor(() => expect(api.report).toHaveBeenLastCalledWith("puertos-sin-uso", "?dias=90"));
    fireEvent.click(await screen.findByRole("button", { name: "Ver puerto" }));
    expect(onOpenPort).toHaveBeenCalledWith(expect.objectContaining({ id: 2, nombre: "SW-ACC" }), 70);
  });

  it("dibuja el mapa de topología con vecinos dentro y fuera del inventario", async () => {
    api.report.mockResolvedValue(report("topologia", [{ clave: "switch", titulo: "Switch" }, { clave: "vecino", titulo: "Vecino" }], [
      { switch: "SW-CORE", vecino: "SW-ACC.uaeh.mx", en_inventario: "Sí" },
      { switch: "SW-ACC", vecino: "SW-CORE", en_inventario: "Sí" },
      { switch: "SW-CORE", vecino: "AP-01", en_inventario: "No" },
    ]));
    render(<Reports />);
    fireEvent.click(screen.getByRole("button", { name: "Topología" }));
    const map = await screen.findByRole("img", { name: "Mapa de enlaces CDP" });
    expect(map.querySelectorAll("line")).toHaveLength(2);
    expect(map.querySelectorAll("circle.external")).toHaveLength(1);
  });

  it("marca APs y teléfonos: ícono en el mapa, teléfonos fuera del dibujo y columna Tipo", async () => {
    api.report.mockImplementation((kind, query) => Promise.resolve(report(kind,
      [{ clave: "switch", titulo: "Switch" }, { clave: "tipo_equipo", titulo: "Tipo" }, { clave: "vecino", titulo: "Vecino" }], [
        { switch: "SW-CORE", vecino: "AP-01", vecino_tipo: "ap", tipo_equipo: "Access point", en_inventario: "No" },
        { switch: "SW-CORE", vecino: "SEP001122334455", vecino_tipo: "telefono", tipo_equipo: "Teléfono IP", en_inventario: "No" },
      ], `${kind} ${query}`)));
    render(<Reports />);
    fireEvent.click(screen.getByRole("button", { name: "Topología" }));
    const map = await screen.findByRole("img", { name: "Mapa de enlaces CDP" });
    expect(map.querySelectorAll("circle")).toHaveLength(2);
    expect(map.querySelector("[aria-label='Access point']")).toHaveTextContent("📶");
    expect(screen.getByText(/1 teléfono IP conectado/)).toBeInTheDocument();
    expect(screen.getByText("Access point").closest(".neighbor-type")).toHaveTextContent("📶 Access point");
    expect(screen.getByText("Teléfono IP").closest(".neighbor-type")).toHaveTextContent("☎ Teléfono IP");
    fireEvent.click(screen.getByRole("button", { name: "APs y teléfonos" }));
    await waitFor(() => expect(api.report).toHaveBeenLastCalledWith("aps-telefonos", "?equipo="));
    fireEvent.change(screen.getByLabelText("Equipo"), { target: { value: "ap" } });
    await waitFor(() => expect(api.report).toHaveBeenLastCalledWith("aps-telefonos", "?equipo=ap"));
  });

  it("muestra tendencias de 7 o 30 días y avisa si InfluxDB no respondió", async () => {
    const serie = [
      { dia: "2026-09-28", cpu: 20, memoria: 50, entrada_bps: 1000, salida_bps: 500, alertas: 2 },
      { dia: "2026-09-29", cpu: null, memoria: null, entrada_bps: null, salida_bps: null, alertas: 1 },
    ];
    api.report.mockImplementation((kind, query) => Promise.resolve(kind === "tendencias"
      ? { ...report(kind, [{ clave: "switch", titulo: "Switch" }, { clave: "cpu_max", titulo: "CPU máx. %" }],
        [{ switch: "SW-CORE", cpu_max: 91.5 }], `Tendencias ${query}`),
      serie, detalle: query.includes("30") ? "InfluxDB no respondió (timeout); sólo se muestran alertas registradas en SONAR." : null }
      : report(kind, [], [])));
    const { unmount } = render(<Reports />);
    fireEvent.click(screen.getByRole("button", { name: "Tendencias" }));
    expect(await screen.findByText("91.5%")).toBeInTheDocument();
    expect(api.report).toHaveBeenLastCalledWith("tendencias", "?dias=7");
    expect(screen.getByText("3")).toHaveClass("trend-total");
    expect(screen.getByText(/Día con más alertas/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Periodo"), { target: { value: "30" } });
    expect(await screen.findByText(/InfluxDB no respondió/)).toBeInTheDocument();
    unmount();
    // Al volver se abre el mismo reporte con el mismo periodo.
    render(<Reports />);
    await waitFor(() => expect(api.report).toHaveBeenLastCalledWith("tendencias", "?dias=30"));
  });
});
