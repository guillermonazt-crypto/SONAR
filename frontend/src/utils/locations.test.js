import { describe, it, expect } from "vitest";
import { parseCoordinates, siteCoordinates } from "./locations";

describe("ubicación de planteles", () => {
  it("usa latitud, longitud del campo ubicación antes que la tabla", () => {
    expect(parseCoordinates("20.1, -98.7")).toEqual([20.1, -98.7]);
    expect(parseCoordinates("Carretera Pachuca km 4")).toBeNull();
    expect(siteCoordinates({ nombre: "Escuela Superior Apan", ubicacion: "19.5,-98.1" })).toEqual([19.5, -98.1]);
  });

  it("reconoce el plantel por nombre sin importar acentos ni mayúsculas", () => {
    expect(siteCoordinates({ nombre: "Escuela Superior Zimapán" })).toEqual([20.7372, -99.3822]);
    expect(siteCoordinates({ nombre: "ESCUELA SUPERIOR ZIMAPAN" })).toEqual([20.7372, -99.3822]);
    expect(siteCoordinates({ nombre: "Plantel desconocido" })).toBeNull();
  });
});
