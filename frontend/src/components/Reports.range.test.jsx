import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import Reports, { splitByRange } from "./Reports";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { report: vi.fn() } }));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
});

const columns = [{ clave: "switch", titulo: "Switch" }, { clave: "componente", titulo: "Componente" }, { clave: "estado", titulo: "Estado" }];
const hardware = (filas, total = filas.length) => ({
  tipo: "hardware", titulo: "Salud del hardware", descripcion: "", columnas: columns, filas,
  rango: { total, etiqueta: "componentes sanos" },
});

describe("Reportes por excepción", () => {
  it("si todo está bien muestra una línea en lugar de la tabla", async () => {
    api.report.mockResolvedValue({
      tipo: "puertos-errores", titulo: "Puertos con errores", descripcion: "", columnas: columns, filas: [],
      rango: { total: 48, etiqueta: "puertos sanos" },
    });
    render(<Reports kinds={["puertos-errores"]} />);
    expect(await screen.findByText("✓ 48 puertos sanos")).toBeInTheDocument();
    expect(document.querySelector(".sonar-table")).toBeNull();
  });

  it("sólo lista lo fuera de rango y cuenta los sanos ocultos", async () => {
    api.report.mockResolvedValue(hardware([
      { switch: "SW-CORE", componente: "Ventilador 1", estado: "critical" },
      { switch: "SW-CORE", componente: "Fuente 1", estado: "ok" },
      { switch: "SW-ACC", componente: "Fuente 1", estado: "ok" },
    ]));
    render(<Reports kinds={["hardware"]} />);
    expect(await screen.findByText("Ventilador 1")).toBeInTheDocument();
    expect(screen.queryByText("Fuente 1")).toBeNull();
    expect(screen.getByText("✓ 2 componentes sanos (no se muestran)")).toBeInTheDocument();
  });

  it("'Ver todas' muestra la tabla completa y vuelve a sólo lo fuera de rango", async () => {
    api.report.mockResolvedValue(hardware([
      { switch: "SW-CORE", componente: "Ventilador 1", estado: "critical" },
      { switch: "SW-CORE", componente: "Fuente 1", estado: "ok" },
    ]));
    render(<Reports kinds={["hardware"]} />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver todas (2)" }));
    expect(screen.getByText("Fuente 1")).toBeInTheDocument();
    expect(screen.getByText("Todas: 1 fuera de rango y 1 componentes sanos", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Solo fuera de rango" }));
    expect(screen.queryByText("Fuente 1")).toBeNull();
  });

  it("con todo sano también deja ver la tabla completa", async () => {
    api.report.mockResolvedValue(hardware([{ switch: "SW-ACC", componente: "Fuente 1", estado: "ok" }]));
    render(<Reports kinds={["hardware"]} />);
    expect(await screen.findByText("✓ 1 componentes sanos", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ver todas (1)" }));
    expect(screen.getByText("Fuente 1")).toBeInTheDocument();
  });

  it("los reportes sin rango no se filtran", () => {
    const rows = [{ estado: "ok" }, { estado: "critical" }];
    expect(splitByRange("inventario", rows, undefined)).toEqual({ flagged: rows, healthy: 0 });
    expect(splitByRange("opticas", [{ nivel: "ok" }, { nivel: "warning" }], { total: 2 }).healthy).toBe(1);
    expect(splitByRange("disponibilidad", [{ minutos_caido: 0 }, { minutos_caido: 12 }], { total: 2 }).flagged).toHaveLength(1);
  });
});
