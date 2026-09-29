import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import Backups from "./Backups";
import Discovered from "./Discovered";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { backups: vi.fn(), runBackup: vi.fn(), backupDetail: vi.fn(), discovered: vi.fn(), ignoreDiscovered: vi.fn() },
}));
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const versions = [
  { id: 2, exito: true, momento: "2026-09-29T10:00:00Z", verificado: null, lineas_agregadas: 1, lineas_eliminadas: 1, error: "" },
  { id: 1, exito: false, momento: "2026-09-28T10:00:00Z", verificado: null, lineas_agregadas: 0, lineas_eliminadas: 0, error: "timed out" },
];

describe("Backups", () => {
  it("muestra versiones, diferencias coloreadas y respalda a pedido", async () => {
    api.backups.mockResolvedValue(versions);
    api.runBackup.mockResolvedValue(versions);
    api.backupDetail.mockResolvedValue({
      id: 2, secretos_ocultos: true, contenido: "hostname SW\nenable secret 9 <oculto>\n",
      diferencias: "--- versión anterior\n+++ esta versión\n- description Recepcion\n+ description Caja 1",
    });
    render(<Backups device={{ id: 5, nombre: "SW-LAB" }} onClose={() => {}} />);
    expect(await screen.findByText("+ description Caja 1")).toHaveClass("diff-add");
    expect(screen.getByText("- description Recepcion")).toHaveClass("diff-del");
    expect(screen.getByText("Falló: timed out")).toBeInTheDocument();
    expect(screen.getByText(/sólo un administrador las ve/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configuración completa" }));
    expect(screen.getByLabelText("Configuración")).toHaveTextContent("enable secret 9 <oculto>");
    fireEvent.click(screen.getByRole("button", { name: "Respaldar ahora" }));
    await waitFor(() => expect(api.runBackup).toHaveBeenCalledWith(5));
  });
});

describe("Discovered", () => {
  it("propone agregar o ignorar equipos fuera del inventario", async () => {
    api.discovered.mockResolvedValueOnce([
      { id: 3, ip: "192.0.2.21", nombre: "SW-ACC-NUEVO.uaeh.mx", origen: "cdp", visto_desde: "SW-CORE · Gi1/0/48",
        plataforma: "cisco C9200L", ultima_vez: new Date().toISOString() },
    ]).mockResolvedValue([]);
    api.ignoreDiscovered.mockResolvedValue({});
    const onAdd = vi.fn();
    render(<Discovered onAdd={onAdd} />);
    expect(await screen.findByText(/Vecino CDP desde SW-CORE · Gi1\/0\/48/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Agregar al inventario" }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ ip: "192.0.2.21" }));
    fireEvent.click(screen.getByRole("button", { name: "Ignorar" }));
    await waitFor(() => expect(screen.queryByText("SW-ACC-NUEVO.uaeh.mx")).not.toBeInTheDocument());
    expect(api.ignoreDiscovered).toHaveBeenCalledWith(3);
  });
});
