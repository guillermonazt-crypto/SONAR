import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import Reports, { NETWORK_REPORTS } from "./Reports";
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
    expect(within(document.querySelector(".sonar-table")).getByText("En riesgo")).toHaveClass("status-critical");
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
    render(<Reports kinds={NETWORK_REPORTS} />);
    fireEvent.click(screen.getByRole("button", { name: "Topología" }));
    const map = await screen.findByRole("img", { name: "Mapa de enlaces CDP" });
    expect(map.querySelectorAll("line")).toHaveLength(2);
    expect(map.querySelectorAll("circle.external")).toHaveLength(1);
  });

  it("dibuja APs y teléfonos como hojas del switch, con columna Tipo", async () => {
    api.report.mockImplementation((kind, query) => Promise.resolve(report(kind,
      [{ clave: "switch", titulo: "Switch" }, { clave: "tipo_equipo", titulo: "Tipo" }, { clave: "vecino", titulo: "Vecino" }], [
        { switch: "SW-CORE", puerto: "Gi1/0/1", vecino: "AP-01", vecino_tipo: "ap", tipo_equipo: "Access point", en_inventario: "No" },
        { switch: "SW-CORE", puerto: "Gi1/0/2", vecino: "SEP001122334455", vecino_tipo: "telefono", tipo_equipo: "Teléfono IP", en_inventario: "No" },
      ], `${kind} ${query}`)));
    render(<Reports kinds={NETWORK_REPORTS} />);
    fireEvent.click(screen.getByRole("button", { name: "Topología" }));
    const map = await screen.findByRole("img", { name: "Mapa de enlaces CDP" });
    expect(map.querySelectorAll("circle")).toHaveLength(3);
    expect(map.querySelector("[data-kind='ap']")).toHaveTextContent("AP");
    expect(map.querySelector("[data-kind='telefono']")).toHaveTextContent("TEL");
    expect(document.querySelector(".neighbor-ap")).toHaveTextContent(/^s*Access point$/);
    expect(document.querySelector(".neighbor-telefono .neighbor-dot")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "APs y teléfonos" }));
    await waitFor(() => expect(api.report).toHaveBeenLastCalledWith("aps-telefonos", "?equipo="));
    fireEvent.change(screen.getByLabelText("Equipo"), { target: { value: "ap" } });
    await waitFor(() => expect(api.report).toHaveBeenLastCalledWith("aps-telefonos", "?equipo=ap"));
  });

  it("la sección Reportes no repite los reportes de Red", async () => {
    api.report.mockImplementation((kind) => Promise.resolve(report(kind, [{ clave: "switch", titulo: "Switch" }], [])));
    render(<Reports />);
    await waitFor(() => expect(api.report).toHaveBeenCalledWith("inventario", ""));
    expect(screen.queryByRole("button", { name: "Topología" })).not.toBeInTheDocument();
    // Menú agrupado por tema en lugar de una fila de botones.
    const menu = screen.getByRole("navigation", { name: "Reportes disponibles" });
    expect(within(menu).getByText("Puertos")).toBeInTheDocument();
    expect(within(menu).getByText("Energía y fibra")).toBeInTheDocument();
    expect(within(menu).getByRole("button", { name: "Inventario" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "PoE" })).toBeInTheDocument();
  });

  it("pide cada reporte y su CSV con el plantel global", async () => {
    api.report.mockImplementation((kind) => Promise.resolve(report(kind, [{ clave: "switch", titulo: "Switch" }], [{ switch: "SW-APAN" }])));
    render(<Reports plantel="4" />);
    expect(await screen.findByText("SW-APAN")).toBeInTheDocument();
    expect(api.report).toHaveBeenLastCalledWith("inventario", "?plantel=4");
    expect(screen.getByRole("link", { name: "Descargar CSV" })).toHaveAttribute("href", "/api/reportes/inventario/?plantel=4&formato=csv");
    fireEvent.click(screen.getByRole("button", { name: "Puertos sin uso" }));
    await waitFor(() => expect(api.report).toHaveBeenLastCalledWith("puertos-sin-uso", "?dias=30&plantel=4"));
  });

  it("muestra tendencias de 7 o 30 días y avisa si InfluxDB no respondió", async () => {
    const serie = [
      { dia: "2026-09-28", cpu: 20, memoria: 50, entrada_bps: 1000, salida_bps: 500, alertas: 2 },
      { dia: "2026-09-29", cpu: null, memoria: null, entrada_bps: null, salida_bps: null, alertas: 1 },
    ];
    api.report.mockImplementation((kind, query) => Promise.resolve(kind === "tendencias"
      ? { ...report(kind, [{ clave: "switch", titulo: "Switch" }, { clave: "cpu_max", titulo: "CPU máx. %" }],
        [{ switch: "SW-CORE", cpu_max: 91.5 }], `Tendencias ${query}`),
      serie, detalle: query.includes("30") ? "InfluxDB no respondió (timeout); sólo se muestran alertas registradas en SONAR." : null }
      : report(kind, [], [])));
    const { unmount } = render(<Reports />);
    fireEvent.click(screen.getByRole("button", { name: "Tendencias" }));
    expect(await within(await screen.findByRole("table")).findByText("91.5%")).toBeInTheDocument();
    expect(screen.getByText("CPU máxima").closest(".report-kpi")).toHaveClass("tone-critical");
    expect(api.report).toHaveBeenLastCalledWith("tendencias", "?dias=7");
    expect(document.querySelector(".trend-total")).toHaveTextContent("3");
    expect(document.querySelector(".report-kpi")).toHaveTextContent("3");
    expect(screen.getByText(/Día con más alertas/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Periodo"), { target: { value: "30" } });
    expect(await screen.findByText(/InfluxDB no respondió/)).toBeInTheDocument();
    unmount();
    // Al volver se abre el mismo reporte con el mismo periodo.
    render(<Reports />);
    await waitFor(() => expect(api.report).toHaveBeenLastCalledWith("tendencias", "?dias=30"));
  });

  it("muestra APs y teléfonos como tarjetas con estado, búsqueda y filtro por VLAN", async () => {
    api.report.mockResolvedValue(report("aps-telefonos", [{ clave: "switch", titulo: "Switch" }], [
      { switch: "SW-CORE", switch_id: 1, puerto: "Gi1/0/1", puerto_id: 11, vecino: "AP-BIBLIO", vecino_tipo: "ap", tipo_equipo: "Access point", vecino_ip: "10.0.0.5", plataforma: "AIR-AP2802I", vlan: 20, poe_w: 15.4, enlace: "up" },
      { switch: "SW-CORE", switch_id: 1, puerto: "Gi1/0/2", puerto_id: 12, vecino: "SEP001122334455", vecino_tipo: "telefono", tipo_equipo: "Teléfono IP", vecino_ip: "10.0.1.9", plataforma: "CP-7841", vlan: 110, poe_w: 4.2, enlace: "down" },
    ]));
    const onOpenPort = vi.fn();
    render(<Reports kinds={NETWORK_REPORTS} onOpenPort={onOpenPort} />);
    fireEvent.click(screen.getByRole("button", { name: "APs y teléfonos" }));
    const card = (await screen.findByText("AP-BIBLIO")).closest("article");
    expect(within(card).getByText("AIR-AP2802I")).toBeInTheDocument();
    expect(within(card).getByText("15.4 W")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: "Con enlace" })).toHaveClass("mark-ok");
    const phone = screen.getByText("SEP001122334455").closest("article");
    expect(within(phone).getByRole("img", { name: "Sin enlace" })).toHaveClass("mark-critical");
    expect(document.querySelector(".sonar-table")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Buscar equipo"), { target: { value: "cp-78" } });
    expect(screen.queryByText("AP-BIBLIO")).not.toBeInTheDocument();
    expect(screen.getByText("SEP001122334455")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Buscar equipo"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("VLAN"), { target: { value: "20" } });
    expect(screen.queryByText("SEP001122334455")).not.toBeInTheDocument();
    // La tarjeta se volvió a montar al limpiar la búsqueda.
    fireEvent.click(within(screen.getByText("AP-BIBLIO").closest("article")).getByRole("button", { name: "Ver puerto" }));
    expect(onOpenPort).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), 11);
  });

  it("marca en rojo las ópticas con RX menor a -24 dBm", async () => {
    api.report.mockImplementation((kind) => Promise.resolve(kind === "opticas"
      ? report(kind, [{ clave: "switch", titulo: "Switch" }, { clave: "puerto", titulo: "Interfaz" }], [
        { switch: "SW-CORE", puerto: "Te1/1/1", rx_dbm: -26.3, tx_dbm: -2.1, nivel: "critical", motivos: "" },
        { switch: "SW-CORE", puerto: "Te1/1/2", rx_dbm: -8.4, tx_dbm: -2.0, nivel: "ok", motivos: "" },
      ])
      : report(kind, [], [])));
    render(<Reports />);
    fireEvent.click(screen.getByRole("button", { name: "Ópticas" }));
    const bad = (await screen.findByText("RX -26.3 dBm")).closest(".optic-row");
    expect(bad.querySelector(".fill-critical")).toBeInTheDocument();
    expect(screen.getByText("RX -8.4 dBm").closest(".optic-row").querySelector(".fill-ok")).toBeInTheDocument();
    expect(screen.getByText("RX bajo -24 dBm").closest(".report-kpi")).toHaveTextContent("1");
  });

  it("resume la disponibilidad por plantel e indica el estado del inventario", async () => {
    api.report.mockImplementation((kind) => Promise.resolve(kind === "disponibilidad"
      ? report(kind, [{ clave: "switch", titulo: "Switch" }], [
        { switch: "SW-A", plantel: "Actopan", minutos_caido: 600, disponibilidad: 98.6 },
        { switch: "SW-B", plantel: "Pachuca", minutos_caido: 0, disponibilidad: 100 },
      ])
      : report(kind, [{ clave: "switch", titulo: "Switch" }], [
        { switch: "SW-A", activo: "Sí", estado: "critical", uptime_dias: 3, puertos: 48, activos: 20 },
        { switch: "SW-B", activo: "Sí", estado: "ok", uptime_dias: 40, puertos: 48, activos: 28 },
      ])));
    render(<Reports />);
    expect(await screen.findByRole("img", { name: "Switches por estado" })).toBeInTheDocument();
    expect(screen.getByText("48 / 96")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disponibilidad" }));
    expect(await screen.findByText("Disponibilidad por plantel")).toBeInTheDocument();
    expect(document.querySelector(".report-bar[title^='Actopan:'] .fill-critical")).toBeInTheDocument();
    expect(document.querySelector(".report-bar[title^='Pachuca:'] .fill-ok")).toBeInTheDocument();
  });

  it("grafica el uso de puertos y del presupuesto PoE con colores por nivel", async () => {
    api.report.mockImplementation((kind) => Promise.resolve(kind === "puertos-saturados"
      ? report(kind, [{ clave: "switch", titulo: "Switch" }], [
        { switch: "SW-A", puerto: "Gi1/0/1", uso_pct: 95, troncal: "Sí" },
        { switch: "SW-A", puerto: "Gi1/0/2", uso_pct: 72, troncal: "No" },
      ])
      : kind === "poe"
        ? report(kind, [{ clave: "switch", titulo: "Switch" }], [
          { switch: "SW-POE", presupuesto_w: 370, consumo_w: 100, uso_pct: 27, puertos_falla: 0, preparacion: "Listo" },
        ])
        : report(kind, [], [])));
    render(<Reports />);
    fireEvent.click(screen.getByRole("button", { name: "Puertos saturados" }));
    expect(await screen.findByText("Uso por puerto")).toBeInTheDocument();
    expect(document.querySelector(".report-bar[title^='SW-A · Gi1/0/1'] .fill-critical")).toBeInTheDocument();
    expect(document.querySelector(".report-bar[title^='SW-A · Gi1/0/2'] .fill-warning")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "PoE" }));
    expect(await screen.findByText("Uso del presupuesto PoE por switch")).toBeInTheDocument();
    expect(screen.getByText("100 W")).toBeInTheDocument();
    expect(document.querySelector(".report-bar[title^='SW-POE'] .fill-ok")).toBeInTheDocument();
  });
});
