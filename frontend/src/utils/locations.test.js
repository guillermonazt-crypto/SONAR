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

import hidalgo from "./hidalgo.geo.json";

const inside = ([lat, lng], ring) => {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
};

describe("contorno de Hidalgo", () => {
  it("contiene Pachuca, Huejutla, Zimapán y Apan", () => {
    const ring = hidalgo.features.find((feature) => feature.properties.id === "hid").geometry.coordinates[0];
    ["Escuela Preparatoria Número 1", "Escuela Superior Huejutla", "Escuela Superior Zimapán", "Escuela Superior Apan"].forEach((nombre) => {
      expect(inside(siteCoordinates({ nombre }), ring)).toBe(true);
    });
    expect(inside([19.43, -99.13], ring)).toBe(false); // Ciudad de México
  });
});
