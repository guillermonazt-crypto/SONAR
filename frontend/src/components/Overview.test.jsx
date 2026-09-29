import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, within } from "@testing-library/react";
import Overview from "./Overview";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { summary: vi.fn(), zabbix: vi.fn() } }));
afterEach(cleanup);

const limits = { cpu_atencion: 70, cpu_riesgo: 90, memoria_atencion: 80, memoria_riesgo: 90 };
const now = new Date().toISOString();
const device = (id, nombre, plantel, estado, motivos = [], plantelId = id) => ({
  id, nombre, plantel: plantelId, hostname: `192.0.2.${id}`, plantel_nombre: plantel, division_nombre: "Escuelas", rol: "access",
  activo: true, lectura_correcta: estado !== "critical", cpu_5m: 10, memoria_usada_pct: 40, estado, motivos,
  puertos: { total: 2, up: 1, down: 1, con_errores: 0, danados: 0, troncales: 0, voz: 0 },
  historial: [{ time: now, cpu: 10, memoria: 40, entrada_bps: 2000, salida_bps: 1000 }],
});

describe("Overview", () => {
  it("lista equipos en riesgo, agrupa por plantel y abre puertos", async () => {
    api.summary.mockResolvedValue({
      generado: now, ultima_lectura: now, worker_atrasado: false,
      umbrales: { core: limits, distribution: limits, access: limits },
      switches: [
        device(1, "SW-OK", "Apan", "ok"),
        device(2, "SW-CAIDO", "Tulancingo", "critical", [{ level: "critical", text: "No responde a SNMP" }]),
      ],
    });
    api.zabbix.mockResolvedValue({ configured: false, hosts: [], detail: "No configurado" });
    const onOpenPorts = vi.fn();
    render(<Overview onOpenPorts={onOpenPorts} />);
    const risk = (await screen.findByRole("heading", { name: "Equipos en riesgo" })).closest("section");
    expect(await within(risk).findByText("SW-CAIDO")).toBeInTheDocument();
    expect(within(risk).queryByText("SW-OK")).not.toBeInTheDocument();
    expect(within(risk).getByText("No responde a SNMP")).toBeInTheDocument();
    const analysis = screen.getByRole("heading", { name: "Estado por equipo" }).closest("section");
    expect(within(analysis).getByRole("heading", { name: /Tulancingo/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Normales (1)" }));
    expect(within(analysis).getByText("SW-OK")).toBeInTheDocument();
    expect(within(analysis).queryByText("SW-CAIDO")).not.toBeInTheDocument();
    fireEvent.click(within(analysis).getByRole("button", { name: "Ver puertos" }));
    expect(onOpenPorts).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  });

  it("muestra el tablero por plantel y filtra el análisis al elegir uno", async () => {
    const site = (id, nombre, estado, extra = {}) => ({
      id, nombre, division: "Escuelas", estado, equipos: 1, inactivos: 0,
      niveles: { ok: estado === "ok" ? 1 : 0, warning: 0, critical: estado === "critical" ? 1 : 0 },
      sin_respuesta: 0, disponibilidad: 100, puertos: { total: 2, up: 1, con_errores: 0, inestables: 0, saturados: 0 },
      alertas_abiertas: 0, alertas_sin_reconocer: 0, mantenimiento: false, ...extra,
    });
    api.summary.mockResolvedValue({
      generado: now, ultima_lectura: now, worker_atrasado: false,
      umbrales: { core: limits, distribution: limits, access: limits },
      planteles: [
        site(2, "Tulancingo", "critical", { alertas_abiertas: 1, alertas_sin_reconocer: 1 }),
        site(1, "Apan", "ok", { mantenimiento: true }),
        site(3, "Zimapán", "none", { equipos: 0, disponibilidad: null }),
      ],
      switches: [
        device(1, "SW-OK", "Apan", "ok", [], 1),
        device(2, "SW-CAIDO", "Tulancingo", "critical", [{ level: "critical", tipo: "snmp", text: "No responde a SNMP" }], 2),
      ],
    });
    api.zabbix.mockResolvedValue({ configured: false, hosts: [] });
    render(<Overview />);
    const board = (await screen.findByRole("heading", { name: "Estado por plantel" })).closest("section");
    expect(within(board).getByText("1 de 3 con incidencias")).toBeInTheDocument();
    expect(within(board).getByText("Sin equipos")).toBeInTheDocument();
    expect(within(board).getByText("En mantenimiento")).toBeInTheDocument();
    const analysis = screen.getByRole("heading", { name: "Estado por equipo" }).closest("section");
    fireEvent.click(within(board).getByRole("button", { name: /^Apan/ }));
    expect(within(analysis).getByText("SW-OK")).toBeInTheDocument();
    expect(within(analysis).queryByText("SW-CAIDO")).not.toBeInTheDocument();
    expect(within(analysis).getByRole("button", { name: "Todos (1)" })).toBeInTheDocument();
    fireEvent.click(within(analysis).getByRole("button", { name: "Limpiar filtros" }));
    expect(within(analysis).getByText("SW-CAIDO")).toBeInTheDocument();
  });

  it("combina filtros por plantel y tipo de problema y los recuerda al volver", async () => {
    api.summary.mockResolvedValue({
      generado: now, ultima_lectura: now, worker_atrasado: false,
      umbrales: { core: limits, distribution: limits, access: limits },
      planteles: [],
      switches: [
        device(1, "SW-CPU", "Apan", "warning", [{ level: "warning", tipo: "cpu", text: "CPU en 75% (≥ 70%)" }], 1),
        device(2, "SW-SNMP", "Apan", "critical", [{ level: "critical", tipo: "snmp", text: "No responde a SNMP" }], 1),
        device(3, "SW-TULA", "Tulancingo", "warning", [{ level: "warning", tipo: "cpu", text: "CPU en 80% (≥ 70%)" }], 2),
      ],
    });
    api.zabbix.mockResolvedValue({ configured: false, hosts: [] });
    const { unmount } = render(<Overview />);
    const analysis = (await screen.findByRole("heading", { name: "Estado por equipo" })).closest("section");
    fireEvent.change(within(analysis).getByLabelText("Problema"), { target: { value: "cpu" } });
    expect(within(analysis).getByText("SW-CPU")).toBeInTheDocument();
    expect(within(analysis).getByText("SW-TULA")).toBeInTheDocument();
    expect(within(analysis).queryByText("SW-SNMP")).not.toBeInTheDocument();
    unmount();
    // Al volver a la pestaña el filtro sigue aplicado (sessionStorage).
    render(<Overview />);
    const again = (await screen.findByRole("heading", { name: "Estado por equipo" })).closest("section");
    expect(await within(again).findByText("SW-CPU")).toBeInTheDocument();
    expect(within(again).queryByText("SW-SNMP")).not.toBeInTheDocument();
    expect(within(again).getByLabelText("Problema")).toHaveValue("cpu");
  });

  it("avisa cuando el worker está atrasado", async () => {
    api.summary.mockResolvedValue({
      generado: now, ultima_lectura: "2026-01-01T00:00:00Z", worker_atrasado: true, umbrales: {}, switches: [],
    });
    api.zabbix.mockResolvedValue({ configured: false, hosts: [] });
    render(<Overview />);
    expect(await screen.findByText(/El worker SNMP no ha escrito lecturas/)).toBeInTheDocument();
  });
});
