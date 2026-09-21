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
  },
}));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
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
    expect(screen.getByText("0%")).toBeInTheDocument();
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
        nombre: "Gi1",
        estado_operativo: "unknown",
        errores_entrada: null,
        errores_salida: 0,
        errores_crc: null,
        actualizado: "2026-01-01T00:00:00Z",
      },
    ]);
    render(<App />);
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
    fireEvent.click(screen.getByRole("button", { name: "Puertos" }));
    expect(await screen.findByText("Desconocido")).toBeInTheDocument();
    expect(screen.getAllByText("Sin lectura").length).toBe(2);
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
