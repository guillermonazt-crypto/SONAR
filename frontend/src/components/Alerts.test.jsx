import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import Alerts from "./Alerts";
import AuditLog from "./AuditLog";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    alerts: vi.fn(), maintenances: vi.fn(), acknowledge: vi.fn(), saveMaintenance: vi.fn(),
    deleteMaintenance: vi.fn(), list: vi.fn(), auditLog: vi.fn(),
  },
}));
afterEach(cleanup);

const sw = { id: 3, nombre: "SW-APAN", hostname: "192.0.2.10", plantel: 1, plantel_nombre: "Apan" };
const alert = {
  id: 9, switch: sw, nivel: "critical", motivos: [{ level: "critical", text: "No responde a SNMP" }],
  inicio: new Date(Date.now() - 30 * 60e3).toISOString(), fin: null, notificada: true, en_mantenimiento: false,
  reconocida_por: null, reconocida_en: null, nota: "",
};

beforeEach(() => {
  vi.resetAllMocks();
  api.alerts.mockImplementation((open) => Promise.resolve(open ? [alert] : [alert]));
  api.maintenances.mockResolvedValue([]);
  api.list.mockImplementation((resource) => Promise.resolve(resource === "switches" ? [sw] : [{ id: 1, nombre: "Apan" }]));
});

describe("Alerts", () => {
  it("usa el plantel global, filtra por tipo y recuerda los filtros", async () => {
    const { unmount } = render(<Alerts user={{ can_edit: true }} plantel="1" />);
    await screen.findAllByText("No responde a SNMP");
    // El plantel ya no tiene selector propio: llega del selector global.
    expect(screen.queryByLabelText("Filtrar alertas por plantel")).not.toBeInTheDocument();
    expect(api.maintenances).toHaveBeenCalledWith("1");
    expect(api.list).toHaveBeenCalledWith("switches", { plantel: "1" });
    fireEvent.change(screen.getByLabelText("Filtrar alertas por tipo"), { target: { value: "snmp" } });
    await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(false, { plantel: "1", tipo: "snmp", estado: "all" }));
    expect(api.alerts).toHaveBeenCalledWith(true, { plantel: "1", tipo: "snmp" });
    unmount();
    api.alerts.mockClear();
    render(<Alerts user={{ can_edit: false }} />);
    await waitFor(() => expect(api.alerts).toHaveBeenCalledWith(true, { plantel: "", tipo: "snmp" }));
    expect(screen.getByLabelText("Filtrar alertas por tipo")).toHaveValue("snmp");
    fireEvent.click(screen.getByRole("button", { name: "Limpiar filtros" }));
    await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(false, { plantel: "", tipo: "all", estado: "all" }));
  });

  it("el editor reconoce una alerta con nota", async () => {
    api.acknowledge.mockResolvedValue({});
    render(<Alerts user={{ can_edit: true }} />);
    expect((await screen.findAllByText("No responde a SNMP")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Nota para SW-APAN"), { target: { value: "Cuadrilla en camino" } });
    fireEvent.click(screen.getByRole("button", { name: "Reconocer" }));
    await waitFor(() => expect(api.acknowledge).toHaveBeenCalledWith(9, "Cuadrilla en camino"));
  });

  it("marca las alertas escaladas por falta de atención", async () => {
    api.alerts.mockResolvedValue([{ ...alert, escalada_en: new Date().toISOString() }]);
    render(<Alerts user={{ can_edit: false }} />);
    expect(await screen.findByText(/Escalada .* por falta de atención/)).toBeInTheDocument();
  });

  it("el lector sólo ve el estado, sin reconocer ni programar", async () => {
    render(<Alerts user={{ can_edit: false }} />);
    expect(await screen.findByText("Sin atender")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconocer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Programar mantenimiento" })).not.toBeInTheDocument();
  });

  it("programa una ventana de mantenimiento para un plantel", async () => {
    api.saveMaintenance.mockResolvedValue({});
    render(<Alerts user={{ can_edit: true }} />);
    await screen.findAllByText("No responde a SNMP");
    const form = screen.getByRole("button", { name: "Guardar ventana" }).closest("form");
    fireEvent.change(within(form).getByLabelText("Aplica a"), { target: { value: "plantel" } });
    await within(form).findByRole("option", { name: "Apan" });
    fireEvent.change(within(form).getByLabelText("Plantel"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Inicio"), { target: { value: "2026-10-01T22:00" } });
    fireEvent.change(screen.getByLabelText("Fin"), { target: { value: "2026-10-02T02:00" } });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "Cambio de UPS" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar ventana" }));
    await waitFor(() => expect(api.saveMaintenance).toHaveBeenCalled());
    const saved = api.saveMaintenance.mock.calls[0][0];
    expect(saved).toMatchObject({ switch: null, plantel: 1, motivo: "Cambio de UPS" });
    expect(new Date(saved.inicio).getTime()).toBe(new Date("2026-10-01T22:00").getTime());
  });
});

describe("AuditLog", () => {
  it("carga la bitácora al abrirla y muestra los cambios", async () => {
    api.auditLog.mockResolvedValue([
      { id: 1, usuario_nombre: "editor", accion: "editar", objeto: "switch", descripcion: "Editó switch SW-CAIDO",
        cambios: { nombre: ["SW-DOWN", "SW-CAIDO"] }, momento: "2026-09-29T10:00:00Z" },
    ]);
    const { container } = render(<AuditLog />);
    expect(api.auditLog).not.toHaveBeenCalled();
    const details = container.querySelector("details");
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await screen.findByText("Editó switch SW-CAIDO")).toBeInTheDocument();
    expect(screen.getByText("nombre: SW-DOWN → SW-CAIDO")).toBeInTheDocument();
  });
});
