import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import GlobalSearch from "./GlobalSearch";
import { api } from "../api/client";

vi.mock("../api/client", () => ({ api: { search: vi.fn() } }));
afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const sw = { id: 3, nombre: "SW-APAN", hostname: "192.0.2.10", plantel: 1, plantel_nombre: "Apan" };

describe("GlobalSearch", () => {
  it("busca por MAC y abre el switch y el puerto encontrados", async () => {
    api.search.mockResolvedValue({
      query: "0050.56ab",
      switches: [],
      puertos: [
        { id: 7, nombre: "Gi1/0/5", es_trunk: false, coincide: "mac", valor: "00:50:56:ab:cd:ef", vlan: 20, estado_operativo: "up", switch: sw },
        { id: 8, nombre: "Gi1/0/48", es_trunk: true, coincide: "mac", valor: "00:50:56:ab:cd:ef", vlan: null, estado_operativo: "up", switch: sw },
      ],
    });
    const onOpen = vi.fn();
    render(<GlobalSearch onOpen={onOpen} plantel="1" />);
    fireEvent.change(screen.getByLabelText("Buscar equipo por MAC, IP o switch"), { target: { value: "0050.56ab" } });
    const first = await screen.findByRole("button", { name: /SW-APAN · Gi1\/0\/5/ });
    // La búsqueda respeta el plantel global.
    expect(api.search).toHaveBeenCalledWith("0050.56ab", "1");
    expect(first).toHaveTextContent("VLAN 20");
    expect(first).toHaveTextContent("Apan");
    expect(screen.getByRole("button", { name: /Gi1\/0\/48/ })).toHaveTextContent("troncal");
    fireEvent.click(first);
    expect(onOpen).toHaveBeenCalledWith(sw, 7);
    expect(screen.queryByRole("region", { name: "Resultados de búsqueda" })).not.toBeInTheDocument();
  });

  it("no consulta con menos de 3 caracteres y avisa si no hay coincidencias", async () => {
    api.search.mockResolvedValue({ query: "zzz9", switches: [], puertos: [] });
    render(<GlobalSearch onOpen={() => {}} />);
    const input = screen.getByLabelText("Buscar equipo por MAC, IP o switch");
    fireEvent.change(input, { target: { value: "10" } });
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(api.search).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "zzz9" } });
    expect(await screen.findByText(/Sin coincidencias/)).toBeInTheDocument();
  });
});
