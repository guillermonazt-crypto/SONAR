import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import App from "./App";
import { api } from "./api/client";
vi.mock("./api/client", () => ({
  api: {
    session: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    list: vi.fn(),
    save: vi.fn(),
    ports: vi.fn(),
    zabbix: vi.fn(),
    portHistory: vi.fn(),
    switchHistory: vi.fn(),
    summary: vi.fn(),
    search: vi.fn(),
    optics: vi.fn(),
    alertSummary: vi.fn(),
    discovered: vi.fn(),
  },
}));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  api.alertSummary.mockResolvedValue({ abiertas: 0, sin_reconocer: 0 });
  api.discovered.mockResolvedValue([]);
  api.zabbix.mockResolvedValue({ configured: false, hosts: [], detail: "No configurado" });
  api.portHistory.mockResolvedValue({ points: [] });
  api.switchHistory.mockResolvedValue({ points: [] });
  api.list.mockImplementation((resource) =>
    Promise.resolve(
      resource === "switches"
        ? [
            {
              id: 1,
              nombre: "SW-LAB",
              hostname: "192.0.2.1",
              rol: "access",
              plantel: 1,
              plantel_nombre: "Lab",
              activo: true,
              cpu_5m: 0,
              ultima_consulta: null,
              estado: "critical",
              motivos: [{ level: "critical", text: "No responde a SNMP" }],
            },
          ]
        : [{ id: 1, nombre: "Lab", activo: true }],
    ),
  );
});
describe("SONAR", () => {
  it("inicia sesión y muestra inventario sin acciones de edición para lectores", async () => {
    api.session.mockResolvedValue({ user: null });
    api.login.mockResolvedValue({
      user: { username: "reader", rol: "lector", can_edit: false },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Usuario"), {
      target: { value: "reader" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña"), {
      target: { value: "pass" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByText("SW-LAB")).toBeInTheDocument();
    expect(screen.getByText("No responde a SNMP")).toBeInTheDocument();
    expect(screen.getByText("En riesgo")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Guardar switch" }),
    ).not.toBeInTheDocument();
    expect(api.login).toHaveBeenCalledWith({
      username: "reader",
      password: "pass",
    });
  });
  it("permite al editor crear switches y consultar puertos desconocidos", async () => {
    api.session.mockResolvedValue({
      user: { username: "editor", rol: "editor", can_edit: true },
    });
    api.save.mockResolvedValue({});
    api.ports.mockResolvedValue([
      {
        id: 1,
        nombre: "GigabitEthernet1/0/1",
        descripcion: "Puesto recepción",
        es_trunk: false,
        estado_operativo: "unknown",
        errores_entrada: null,
        errores_salida: 0,
        errores_crc: null,
        actualizado: "2026-01-01T00:00:00Z",
        ip_equipo: "192.0.2.20",
        mac_equipo: "00:11:22:33:44:55",
        mac_telefono: null,
        vlan: 20,
        voice_vlan: 10,
        dhcp: null,
        trafico_entrada_bps: 1250000,
        trafico_salida_bps: 320000,
      },
    ]);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Inventario" }));
    fireEvent.change(await screen.findByLabelText("Nombre del switch"), {
      target: { value: "Nuevo" },
    });
    fireEvent.change(screen.getByLabelText("Dirección IP"), {
      target: { value: "192.0.2.2" },
    });
    await screen.findByText("SW-LAB");
    fireEvent.change(screen.getByLabelText("Plantel"), {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar switch" }));
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith(
        "switches",
        {
          nombre: "Nuevo",
          hostname: "192.0.2.2",
          rol: "access",
          plantel: 1,
          activo: true,
        },
        null,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Monitoreo" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ver puertos" }));
    expect(
      await screen.findByRole("button", {
        name: "GigabitEthernet1/0/1: Desconocido; 0 errores",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "GigabitEthernet1/0/1: Desconocido; 0 errores" })).toHaveTextContent("1");
    expect(
      screen.getByRole("button", {
        name: "GigabitEthernet1/0/1: Desconocido; 0 errores",
      }),
    ).toHaveClass("port-voice");
    expect(screen.getByText("Ámbar · sin lectura")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "GigabitEthernet1/0/1: Desconocido; 0 errores",
      }),
    );
    expect(screen.getByText("192.0.2.20")).toBeInTheDocument();
    expect(screen.getByText("00:11:22:33:44:55")).toBeInTheDocument();
  });
  it("filtra todas las pestañas por el plantel global y lo recuerda al recargar", async () => {
    localStorage.removeItem("sonar-plantel");
    api.session.mockResolvedValue({ user: { username: "reader", rol: "lector", can_edit: false } });
    api.summary.mockResolvedValue({ generado: null, ultima_lectura: null, umbrales: {}, planteles: [], switches: [] });
    api.optics.mockResolvedValue({ transceptores: [], umbrales: {} });
    api.list.mockImplementation((resource) => Promise.resolve(resource === "planteles"
      ? [{ id: 1, nombre: "Lab" }, { id: 2, nombre: "Apan" }]
      : []));
    const { unmount } = render(<App />);
    const picker = await screen.findByLabelText("Filtrar todo por plantel");
    await screen.findByRole("option", { name: "Apan" });
    expect(picker).toHaveValue("");
    expect(api.list).toHaveBeenCalledWith("switches", { plantel: "" });
    fireEvent.change(picker, { target: { value: "2" } });
    expect(localStorage.getItem("sonar-plantel")).toBe("2");
    // Monitoreo se recarga con el plantel y el contador de alertas también.
    await waitFor(() => expect(api.list).toHaveBeenCalledWith("switches", { plantel: "2" }));
    await waitFor(() => expect(api.alertSummary).toHaveBeenLastCalledWith("2"));
    fireEvent.click(screen.getByRole("button", { name: "Resumen" }));
    await waitFor(() => expect(api.summary).toHaveBeenCalledWith(false, "2"));
    fireEvent.click(screen.getByRole("button", { name: "Ópticas" }));
    await waitFor(() => expect(api.optics).toHaveBeenCalledWith(false, "2"));
    fireEvent.click(screen.getByRole("button", { name: "Inventario" }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith("planteles"));
    expect(api.list).toHaveBeenCalledWith("switches", { plantel: "2" });
    unmount();
    // Al recargar se restaura el plantel guardado.
    api.alertSummary.mockClear();
    render(<App />);
    const restored = await screen.findByLabelText("Filtrar todo por plantel");
    await screen.findByRole("option", { name: "Apan" });
    expect(restored).toHaveValue("2");
    await waitFor(() => expect(api.alertSummary).toHaveBeenCalledWith("2"));
    fireEvent.change(restored, { target: { value: "" } });
    expect(localStorage.getItem("sonar-plantel")).toBeNull();
  });
  it("muestra error y permite reintentar conexión", async () => {
    api.session
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ user: null });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Django");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByLabelText("Usuario")).toBeInTheDocument();
  });
});
