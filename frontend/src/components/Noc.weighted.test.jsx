import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import Noc, { scoreDetail, siteLevel } from "./Noc";
import { api } from "../api/client";

vi.mock("./NocMap", () => ({
  default: ({ points }) => (
    <ul data-testid="noc-map">
      {points.map((point) => (
        <li key={point.id}>{`${point.nombre}:${point.estado}:${point.detalle}`}</li>
      ))}
    </ul>
  ),
}));
vi.mock("../api/client", () => ({ api: { summary: vi.fn() } }));
vi.mock("../utils/alarm", () => ({ playAlarm: vi.fn(), notify: vi.fn(), requestNotifications: vi.fn(() => Promise.resolve("granted")) }));

const site = (id, nombre, extra) => ({
  id, nombre, division: "Escuelas Superiores", estado: "critical", equipos: 2, inactivos: 0,
  niveles: { ok: 1, warning: 0, critical: 1 }, puertos: { total: 48, up: 30 },
  alertas_abiertas: 0, alertas_sin_reconocer: 0, disponibilidad: 50, ...extra,
});

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("Semáforo ponderado del NOC", () => {
  it("usa el estado ponderado y conserva el peor estado si no viene", () => {
    expect(siteLevel({ estado: "critical", estado_ponderado: "ok" })).toBe("ok");
    expect(siteLevel({ estado: "warning" })).toBe("warning");
  });

  it("describe qué suma el puntaje", () => {
    expect(scoreDetail({ desglose: { critico: 0, caido: 1, lento: 2, puerto: 1 } })).toBe("1 caído · 2 lentos · 1 puerto");
    expect(scoreDetail({})).toBe("");
  });

  it("colorea el mapa y la lista con el puntaje", async () => {
    api.summary.mockResolvedValue({
      ultima_lectura: new Date().toISOString(), umbrales: {}, switches: [],
      planteles: [
        // Peor equipo en rojo, pero sólo un equipo caído: 3 pts, verde.
        site(1, "Escuela Superior Apan", { estado_ponderado: "ok", puntaje: 3, desglose: { caido: 1 } }),
        site(2, "Escuela Superior Tizayuca", { estado_ponderado: "critical", puntaje: 18, desglose: { critico: 3, caido: 1 } }),
      ],
    });
    render(<Noc />);
    expect(await screen.findByText("Escuela Superior Apan:ok:1 caído")).toBeInTheDocument();
    expect(screen.getByText("Escuela Superior Tizayuca:critical:3 críticos · 1 caído")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "1 en rojo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Escuela Superior Tizayuca: Crítico" })).toHaveTextContent("18 pts");
    expect(screen.getByRole("button", { name: "Escuela Superior Apan: Sano" })).toHaveTextContent("3 pts");
  });
});
