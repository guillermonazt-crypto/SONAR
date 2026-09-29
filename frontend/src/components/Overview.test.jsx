import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, within } from "@testing-library/react";
import Overview from "./Overview";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { summary: vi.fn(), zabbix: vi.fn() } }));
afterEach(cleanup);

const limits = { cpu_atencion: 70, cpu_riesgo: 90, memoria_atencion: 80, memoria_riesgo: 90 };
const now = new Date().toISOString();
const device = (id, nombre, plantel, estado, motivos = []) => ({
  id, nombre, hostname: `192.0.2.${id}`, plantel_nombre: plantel, division_nombre: "Escuelas", rol: "access",
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

  it("avisa cuando el worker está atrasado", async () => {
    api.summary.mockResolvedValue({
      generado: now, ultima_lectura: "2026-01-01T00:00:00Z", worker_atrasado: true, umbrales: {}, switches: [],
    });
    api.zabbix.mockResolvedValue({ configured: false, hosts: [] });
    render(<Overview />);
    expect(await screen.findByText(/El worker SNMP no ha escrito lecturas/)).toBeInTheDocument();
  });
});
