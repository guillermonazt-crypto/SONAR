import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import LivePanel, { SwitchLive, age, groupProblems } from "./LivePanel";
import Sidebar from "./Sidebar";
import { closeButton, installBackClose } from "../utils/backClose";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: { live: vi.fn(), liveSwitch: vi.fn(), liveAcknowledge: vi.fn() },
}));
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const problem = (overrides = {}) => ({
  eventid: "5001", nombre: "Unavailable by ICMP ping", severidad: 4, severidad_nombre: "Alta", reconocido: false,
  suprimido: false, datos: "", desde: "2026-10-06T20:00:00Z", antiguedad_s: 3900,
  switch: { id: 2, nombre: "SW-TULA" }, plantel: { id: 3, nombre: "Tula" }, ...overrides,
});
const live = (overrides = {}) => ({
  configurado: true, fuente: "zabbix", detalle: null, puede_reconocer: true,
  problemas: [problem(), problem({ eventid: "5002", nombre: "High CPU", severidad: 2, severidad_nombre: "Advertencia", reconocido: true, antiguedad_s: 120 })],
  switches: [
    { id: 1, nombre: "SW-APAN", ip: "192.0.2.1", plantel_nombre: "Apan", hostid: "101", disponible: true, ultimos: { ping: true, latencia_ms: 4, perdida_pct: 0 } },
    { id: 2, nombre: "SW-TULA", ip: "192.0.2.2", plantel_nombre: "Tula", hostid: "102", disponible: false, ultimos: { ping: false, latencia_ms: null, perdida_pct: 100 } },
  ],
  resumen: { problemas: 2, sin_reconocer: 1, por_severidad: { Desastre: 0, Alta: 1, Media: 0, Advertencia: 1, "Información": 0 }, relacionados: 2, sin_relacionar: 0 },
  ...overrides,
});

describe("LivePanel", () => {
  it("agrupa los síntomas debajo de su causa (correlación de eventos)", async () => {
    const cause = problem({ eventid: "7001", nombre: "SONAR: enlace físico dañado en Gi1/1/1", sintomas: 1, causa: null });
    const other = problem({ eventid: "7005", nombre: "High CPU", severidad: 2, severidad_nombre: "Advertencia" });
    const symptom = problem({ eventid: "7002", nombre: "SONAR: errores CRC en Gi1/1/1", severidad: 2, severidad_nombre: "Advertencia",
      causa: { eventid: "7001", nombre: "SONAR: enlace físico dañado en Gi1/1/1" } });
    expect(groupProblems([cause, other, symptom]).map((p) => p.eventid)).toEqual(["7001", "7002", "7005"]);
    api.live.mockResolvedValue(live({ problemas: [cause, other, symptom] }));
    render(<LivePanel />);
    expect(await screen.findByText("Causa probable · agrupa 1 síntoma")).toBeInTheDocument();
    const line = screen.getByText("↳ Síntoma de: SONAR: enlace físico dañado en Gi1/1/1");
    expect(line.closest("li")).toHaveClass("live-symptom");
  });

  it("muestra problemas con severidad, antigüedad, equipos caídos y la fuente", async () => {
    api.live.mockResolvedValue(live());
    render(<LivePanel />);
    expect(await screen.findByText("Unavailable by ICMP ping")).toBeInTheDocument();
    expect(screen.getByText("Zabbix en vivo")).toBeInTheDocument();
    expect(screen.getByText(/SW-TULA · Tula · desde hace 1 h 5 min/)).toBeInTheDocument();
    expect(screen.getByText("Sin reconocer")).toHaveClass("ack-no");
    expect(screen.getByText("Sin respuesta en Zabbix")).toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();
    expect(screen.getByText("Alta 1")).toBeInTheDocument();
  });

  it("reconoce desde el panel con comentario y vuelve a leer", async () => {
    api.live.mockResolvedValue(live());
    api.liveAcknowledge.mockResolvedValue({});
    render(<LivePanel plantel="3" />);
    const input = await screen.findByLabelText("Comentario para Unavailable by ICMP ping en SW-TULA");
    fireEvent.change(input, { target: { value: "Voy en camino" } });
    fireEvent.click(screen.getByRole("button", { name: "Reconocer" }));
    await waitFor(() => expect(api.liveAcknowledge).toHaveBeenCalledWith("5001", { mensaje: "Voy en camino", reconocer: true }));
    await waitFor(() => expect(api.live).toHaveBeenCalledTimes(2));
    expect(api.live).toHaveBeenCalledWith("3");
  });

  it("sin permiso no ofrece reconocer; sin Zabbix lo explica", async () => {
    api.live.mockResolvedValueOnce(live({ puede_reconocer: false }));
    render(<LivePanel />);
    await screen.findByText("Unavailable by ICMP ping");
    expect(screen.queryByRole("button", { name: "Reconocer" })).toBeNull();
    cleanup();
    api.live.mockResolvedValueOnce({ configurado: false, problemas: [], switches: [], resumen: null });
    render(<LivePanel />);
    expect(await screen.findByText(/Zabbix no está configurado/)).toBeInTheDocument();
  });

  it("formatea la antigüedad", () => {
    expect(age(30)).toBe("menos de 1 min");
    expect(age(600)).toBe("10 min");
    expect(age(3 * 86400 + 7200)).toBe("3 d 2 h");
  });
});

describe("SwitchLive", () => {
  it("muestra los últimos valores y los uplinks del switch", async () => {
    api.liveSwitch.mockResolvedValue({
      configurado: true, puede_reconocer: false, problemas: [],
      switch: { hostid: "101", host: "SW-APAN", disponible: true, ultimos: {
        ping: true, perdida_pct: 0, latencia_ms: 4.2, cpu: 12, memoria: 41.3, snmp: true, momento: new Date().toISOString(),
        interfaces: [{ nombre: "Gi1/1/1", entrada_bps: 9e6, salida_bps: 1e6, errores_entrada: 3, errores_salida: 0 }],
      } },
    });
    render(<SwitchLive device={{ id: 1, nombre: "SW-APAN" }} />);
    expect(await screen.findByText("4.2 ms")).toBeInTheDocument();
    expect(screen.getByText("41.3 %")).toBeInTheDocument();
    expect(screen.getByText("Gi1/1/1")).toBeInTheDocument();
    expect(screen.getByText("9.0 Mbps")).toBeInTheDocument();
    expect(api.liveSwitch).toHaveBeenCalledWith(1);
  });

  it("no ocupa espacio si Zabbix no está configurado", async () => {
    api.liveSwitch.mockResolvedValue({ configurado: false });
    const { container } = render(<SwitchLive device={{ id: 1 }} />);
    await waitFor(() => expect(api.liveSwitch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Barra inferior del celular", () => {
  it("'Más' abre una hoja con Reportes, Configuración, tema y cierre de sesión", () => {
    const onSelect = vi.fn();
    const onLogout = vi.fn();
    const onTheme = vi.fn();
    render(<Sidebar current="home" onSelect={onSelect} onToggle={() => {}} user={{ username: "ana", rol: "editor" }} onLogout={onLogout} theme="dark" onTheme={onTheme} />);
    fireEvent.click(screen.getByRole("button", { name: "Más" }));
    const sheet = screen.getByRole("dialog", { name: "Más" });
    fireEvent.click(screen.getByRole("button", { name: "Modo claro" }));
    expect(onTheme).toHaveBeenCalled();
    fireEvent.click(sheet.querySelector(".more-list button"));
    expect(onSelect).toHaveBeenCalledWith("reports");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Atrás cierra la hoja", () => {
  it("encuentra el botón Cerrar propio del diálogo, no el de uno anidado", () => {
    document.body.innerHTML = `
      <section role="dialog" aria-modal="true" id="outer"><button>Cerrar</button>
        <section role="dialog" aria-modal="true" id="inner"><button aria-label="Cerrar detalle">✕</button></section>
      </section>`;
    expect(closeButton(document.getElementById("outer")).textContent).toBe("Cerrar");
    expect(closeButton(document.getElementById("inner")).getAttribute("aria-label")).toBe("Cerrar detalle");
    document.body.innerHTML = "";
  });

  it("en el celular agrega una entrada al abrir y Atrás pulsa Cerrar", async () => {
    const original = window.matchMedia;
    window.matchMedia = () => ({ matches: true });
    const push = vi.spyOn(window.history, "pushState");
    const uninstall = installBackClose(document.body);
    const sheet = document.createElement("section");
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    const close = document.createElement("button");
    close.textContent = "Cerrar";
    const onClose = vi.fn(() => sheet.remove());
    close.addEventListener("click", onClose);
    sheet.append(close);
    document.body.append(sheet);
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(onClose).toHaveBeenCalled();
    uninstall();
    push.mockRestore();
    window.matchMedia = original;
  });
});
