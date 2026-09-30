import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, within } from "@testing-library/react";
import TopologyMap from "./TopologyMap";
import { clearView } from "../utils/viewState";

afterEach(cleanup);
beforeEach(() => clearView());

const rows = [
  { switch: "SW-CORE", switch_id: 1, puerto: "Te1/1/1", puerto_id: 10, vecino: "SW-ACC.uaeh.mx", vecino_tipo: "switch", en_inventario: "Sí", uso_pct: 95 },
  { switch: "SW-ACC", switch_id: 2, puerto: "Gi1/1/1", puerto_id: 20, vecino: "SW-DIST", vecino_tipo: "switch", en_inventario: "No", uso_pct: 75 },
  { switch: "SW-ACC", switch_id: 2, puerto: "Gi1/0/5", puerto_id: 25, vecino: "AP-PASILLO", vecino_tipo: "ap", plataforma: "cisco AIR-AP2802I",
    mac: "aa:bb:cc:00:00:01", vecino_ip: "10.0.30.5", vlan: 30, poe_w: 15.4, en_inventario: "No" },
  { switch: "SW-ACC", switch_id: 2, puerto: "Gi1/0/6", puerto_id: 26, vecino: "00:11:22:33:44:55", vecino_tipo: "telefono", plataforma: "",
    mac: "00:11:22:33:44:55", vecino_ip: "", vlan: 110, poe_w: 6.2, en_inventario: "No" },
];

describe("TopologyMap", () => {
  it("cuelga APs y teléfonos del switch y colorea los enlaces por uso", () => {
    render(<TopologyMap rows={rows} />);
    const map = screen.getByRole("img", { name: "Mapa de enlaces CDP" });
    expect(map.querySelectorAll("[data-kind='switch']")).toHaveLength(3);
    expect(map.querySelectorAll("[data-kind='ap']")).toHaveLength(1);
    expect(map.querySelectorAll("[data-kind='telefono']")).toHaveLength(1);
    expect(map.querySelector("[data-kind='ap']")).toHaveTextContent("📶");
    expect(map.querySelector("[data-kind='telefono']")).toHaveTextContent("☎");
    expect(map.querySelector("[data-kind='switch']")).toHaveTextContent("🖥");
    expect(map.querySelectorAll("line.saturated")).toHaveLength(1);
    expect(map.querySelectorAll("line.attention")).toHaveLength(1);
    expect(map.querySelectorAll("circle.external")).toHaveLength(1);
    const legend = screen.getByLabelText("Leyenda del mapa");
    expect(legend).toHaveTextContent("Access point");
    expect(legend).toHaveTextContent("Teléfono IP");
    expect(legend).toHaveTextContent("Enlace saturado");
  });

  it("muestra modelo, MAC, IP, VLAN, puerto y PoE al hacer clic y abre el puerto", () => {
    const onOpenPort = vi.fn();
    render(<TopologyMap rows={rows} onOpenPort={onOpenPort} />);
    fireEvent.click(screen.getByRole("button", { name: "Access point AP-PASILLO" }));
    const detail = screen.getByLabelText("Detalle de AP-PASILLO");
    ["cisco AIR-AP2802I", "aa:bb:cc:00:00:01", "10.0.30.5", "30", "SW-ACC · Gi1/0/5", "15.4 W"].forEach((text) =>
      expect(within(detail).getByText(text)).toBeInTheDocument());
    fireEvent.click(within(detail).getByRole("button", { name: "Ver puerto" }));
    expect(onOpenPort).toHaveBeenCalledWith(expect.objectContaining({ id: 2, nombre: "SW-ACC" }), 25);
    fireEvent.click(screen.getByRole("button", { name: /Teléfono IP 00:11/ }));
    const phone = screen.getByLabelText(/Detalle de 00:11/);
    expect(within(phone).getByText("110")).toBeInTheDocument();
    expect(within(phone).getByText("6.2 W")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch SW-ACC" }));
    expect(within(screen.getByLabelText("Detalle de SW-ACC")).getByText("Access points").nextSibling).toHaveTextContent("1");
  });

  it("oculta APs o teléfonos y recuerda la elección", () => {
    const { unmount } = render(<TopologyMap rows={rows} />);
    fireEvent.click(screen.getByLabelText("Teléfonos (1)"));
    const map = screen.getByRole("img", { name: "Mapa de enlaces CDP" });
    expect(map.querySelectorAll("[data-kind='telefono']")).toHaveLength(0);
    expect(map.querySelectorAll("[data-kind='ap']")).toHaveLength(1);
    fireEvent.click(screen.getByLabelText("Access points (1)"));
    expect(map.querySelectorAll("[data-kind='ap']")).toHaveLength(0);
    unmount();
    render(<TopologyMap rows={rows} />);
    expect(screen.getByLabelText("Teléfonos (1)")).not.toBeChecked();
    expect(screen.getByRole("img", { name: "Mapa de enlaces CDP" }).querySelectorAll("[data-kind='telefono']")).toHaveLength(0);
  });
});
