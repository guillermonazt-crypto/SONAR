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
});
