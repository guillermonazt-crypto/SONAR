import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
  within,
} from "@testing-library/react";
import App from "./App";
import { api, endSession } from "./api/client";
// Leaflet necesita un navegador real; en las pruebas el mapa es un marcador.
vi.mock("./components/NocMap", () => ({ default: () => <div data-testid="noc-map" /> }));
vi.mock("./api/client", () => ({
  endSession: vi.fn(),
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
    report: vi.fn(),
  },
}));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  api.alertSummary.mockResolvedValue({ abiertas: 0, sin_reconocer: 0 });
  api.discovered.mockResolvedValue([]);
  api.report.mockResolvedValue({ tipo: "topologia", titulo: "Topología", descripcion: "", columnas: [], filas: [] });
  api.zabbix.mockResolvedValue({ configured: false, hosts: [], detail: "No configurado" });
  api.portHistory.mockResolvedValue({ points: [] });
  api.switchHistory.mockResolvedValue({ points: [] });
  api.summary.mockResolvedValue({ generado: null, ultima_lectura: null, umbrales: {}, planteles: [], switches: [] });
  localStorage.clear();
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
    // Se entra al NOC; los switches están en Estado › Switches y puertos.
    expect(await screen.findByRole("heading", { name: "Red UAEH" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Estado" }));
    fireEvent.click(await screen.findByRole("button", { name: "Switches y puertos" }));
    expect(await screen.findByText("SW-LAB")).toBeInTheDocument();
    expect(screen.getByText("No responde a SNMP")).toBeInTheDocument();
    expect(screen.getByText("En riesgo")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Configuración" }));
    await screen.findByText("Dispositivos monitoreados");
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
    fireEvent.click(await screen.findByRole("button", { name: "Configuración" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Estado" }));
    fireEvent.click(await screen.findByRole("button", { name: "Switches y puertos" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ver puertos" }));
    // Migas: Red UAEH › SW-LAB (y el puerto al abrirlo).
    const crumbs = screen.getByRole("navigation", { name: "Ubicación" });
    expect(crumbs).toHaveTextContent("SW-LAB");
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
    expect(crumbs).toHaveTextContent("GigabitEthernet1/0/1");
  });
  it("filtra todas las secciones por el plantel global y lo recuerda al recargar", async () => {
    api.session.mockResolvedValue({ user: { username: "reader", rol: "lector", can_edit: false } });
    api.optics.mockResolvedValue({ transceptores: [], umbrales: {} });
    api.list.mockImplementation((resource) => Promise.resolve(resource === "planteles"
      ? [{ id: 1, nombre: "Lab" }, { id: 2, nombre: "Apan" }]
      : []));
    const { unmount } = render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Estado" }));
    const picker = await screen.findByLabelText("Filtrar todo por plantel");
    await screen.findByRole("option", { name: "Apan" });
    expect(picker).toHaveValue("");
    await waitFor(() => expect(api.summary).toHaveBeenCalledWith(false, ""));
    fireEvent.change(picker, { target: { value: "2" } });
    expect(localStorage.getItem("sonar-plantel")).toBe("2");
    // Estado se recarga con el plantel, las migas lo muestran y el contador de alertas también.
    await waitFor(() => expect(api.summary).toHaveBeenCalledWith(false, "2"));
    expect(screen.getByRole("navigation", { name: "Ubicación" })).toHaveTextContent("Apan");
    await waitFor(() => expect(api.alertSummary).toHaveBeenLastCalledWith("2"));
    fireEvent.click(screen.getByRole("button", { name: "Switches y puertos" }));
    await waitFor(() => expect(api.list).toHaveBeenCalledWith("switches", { plantel: "2" }));
    fireEvent.click(screen.getByRole("button", { name: "Red" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ópticas" }));
    await waitFor(() => expect(api.optics).toHaveBeenCalledWith(false, "2"));
    api.list.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Configuración" }));
    await waitFor(() => expect(api.list).toHaveBeenCalledWith("switches", { plantel: "2" }));
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
  it("abre el plantel elegido en el NOC dentro de Estado", async () => {
    api.session.mockResolvedValue({ user: { username: "reader", rol: "lector", can_edit: false } });
    api.list.mockImplementation((resource) => Promise.resolve(resource === "planteles" ? [{ id: 9, nombre: "Escuela Superior Apan" }] : []));
    const site = { id: 9, nombre: "Escuela Superior Apan", division: "Escuelas Superiores", estado: "critical", equipos: 2, inactivos: 0,
      niveles: { ok: 1, warning: 0, critical: 1 }, puertos: { total: 48, up: 30, con_errores: 0 }, alertas_abiertas: 1, alertas_sin_reconocer: 1, disponibilidad: 50 };
    api.summary.mockResolvedValue({ generado: null, ultima_lectura: null, umbrales: {}, planteles: [site], switches: [] });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Escuela Superior Apan: Crítico" }));
    expect(await screen.findByRole("heading", { name: "Escuela Superior Apan" })).toBeInTheDocument();
    expect(localStorage.getItem("sonar-plantel")).toBe("9");
    await waitFor(() => expect(api.summary).toHaveBeenCalledWith(false, "9"));
    expect(screen.getByRole("navigation", { name: "Ubicación" })).toHaveTextContent("Escuela Superior Apan");
    expect(screen.getByRole("button", { name: "Planteles" })).toHaveAttribute("aria-pressed", "true");
    // Botón para regresar a elegir entre todos los planteles.
    fireEvent.click(screen.getByRole("button", { name: "‹ Todos los planteles" }));
    expect(await screen.findByRole("heading", { name: "Estado" })).toBeInTheDocument();
    expect(localStorage.getItem("sonar-plantel")).toBeNull();
    await waitFor(() => expect(api.summary).toHaveBeenLastCalledWith(false, ""));
  });
  it("Red pide elegir un plantel por división y muestra su topología", async () => {
    api.session.mockResolvedValue({ user: { username: "reader", rol: "lector", can_edit: false } });
    api.list.mockImplementation((resource) => Promise.resolve(resource === "planteles" ? [
      { id: 3, nombre: "Instituto de Ciencias Básicas e Ingeniería", division_nombre: "Institutos" },
      { id: 9, nombre: "Escuela Superior Apan", division_nombre: "Escuelas Superiores" },
    ] : []));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Red" }));
    const institutes = await screen.findByRole("region", { name: "Institutos" });
    expect(screen.getByRole("region", { name: "Escuelas Superiores" })).toHaveTextContent("Escuela Superior Apan");
    expect(api.report).not.toHaveBeenCalled();
    fireEvent.click(within(institutes).getByRole("button", { name: /Instituto de Ciencias Básicas/ }));
    expect(await screen.findByRole("heading", { name: "Instituto de Ciencias Básicas e Ingeniería" })).toBeInTheDocument();
    await waitFor(() => expect(api.report).toHaveBeenCalledWith("topologia", "?plantel=3"));
    fireEvent.click(screen.getByRole("button", { name: "‹ Todos los planteles" }));
    expect(await screen.findByRole("region", { name: "Institutos" })).toBeInTheDocument();
  });
  it("recuerda el menú lateral contraído y lleva las pestañas antiguas a su sección nueva", async () => {
    api.session.mockResolvedValue({ user: { username: "reader", rol: "lector", can_edit: false } });
    sessionStorage.setItem("sonar-view", JSON.stringify({ tab: "inventory" }));
    const { unmount } = render(<App />);
    expect(await screen.findByRole("heading", { name: "Configuración" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Configuración" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: "Contraer menú" }));
    expect(localStorage.getItem("sonar-sidebar-collapsed")).toBe("true");
    unmount();
    render(<App />);
    expect(await screen.findByRole("button", { name: "Expandir menú" })).toHaveAttribute("aria-expanded", "false");
  });
  it("al cerrar sesión cancela lo pendiente y no deja datos visibles", async () => {
    api.session.mockResolvedValue({ user: { username: "reader", rol: "lector", can_edit: false } });
    api.list.mockImplementation((resource) => Promise.resolve(resource === "planteles" ? [{ id: 2, nombre: "Apan" }] : []));
    localStorage.setItem("sonar-theme", "light");
    localStorage.setItem("sonar-sidebar-collapsed", "false");
    // El servidor tarda en responder: la pantalla se vacía antes.
    let finish;
    api.logout.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Estado" }));
    fireEvent.change(await screen.findByLabelText("Filtrar todo por plantel"), { target: { value: "2" } });
    expect(localStorage.getItem("sonar-plantel")).toBe("2");
    fireEvent.click(screen.getByRole("button", { name: "Salir" }));
    expect(endSession).toHaveBeenCalledTimes(1);
    expect(await screen.findByLabelText("Usuario")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("Apan")).not.toBeInTheDocument();
    expect(localStorage.getItem("sonar-plantel")).toBeNull();
    expect(JSON.parse(sessionStorage.getItem("sonar-view") || "{}")).toEqual({ tab: "home" });
    // El tema y las preferencias del menú se conservan.
    expect(localStorage.getItem("sonar-theme")).toBe("light");
    expect(localStorage.getItem("sonar-sidebar-collapsed")).toBe("false");
    finish();
    await waitFor(() => expect(api.logout).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Usuario")).toBeInTheDocument();
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
