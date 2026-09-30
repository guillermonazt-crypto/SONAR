import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { HIDALGO_CENTER } from "../utils/locations";
import { cssVar } from "../utils/theme";

const LEVEL_COLOR = { critical: "critical", warning: "warning", ok: "ok", none: "faint" };
const LEVEL_TEXT = { critical: "Crítico", warning: "Atención", ok: "Sano", none: "Sin equipos" };
const TILES = {
  light: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
  dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
};

/** Mapa de Hidalgo con un punto por plantel coloreado por su peor estado. */
export default function NocMap({ points, theme = "dark", onSelect }) {
  const container = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);
  const tiles = useRef(null);
  const fitted = useRef(false);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  useEffect(() => {
    map.current = L.map(container.current, {
      center: HIDALGO_CENTER,
      zoom: 8,
      zoomControl: false,
      attributionControl: true,
      scrollWheelZoom: false,
    });
    L.control.zoom({ position: "bottomright" }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => {
      map.current.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    tiles.current?.remove();
    tiles.current = L.tileLayer(TILES[theme] || TILES.dark, {
      subdomains: "abcd",
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map.current);
  }, [theme]);

  useEffect(() => {
    layer.current.clearLayers();
    // Los críticos se dibujan al final para quedar encima.
    const order = { none: 0, ok: 1, warning: 2, critical: 3 };
    [...points].sort((a, b) => order[a.estado] - order[b.estado]).forEach((point) => {
      const color = cssVar(LEVEL_COLOR[point.estado] || "faint") || "#888";
      if (point.estado === "critical") {
        L.circleMarker(point.coords, { radius: 18, stroke: false, fillColor: color, fillOpacity: 0.18, interactive: false, className: "noc-pulse" }).addTo(layer.current);
      }
      L.circleMarker(point.coords, {
        radius: point.estado === "critical" ? 9 : 7,
        color: cssVar("surface") || "#fff",
        weight: 2,
        fillColor: color,
        fillOpacity: 1,
      })
        .bindTooltip(`<strong>${point.nombre}</strong><br/>${LEVEL_TEXT[point.estado] || ""}${point.equipos ? ` · ${point.equipos} switches` : ""}`, { direction: "top", offset: [0, -8] })
        .on("click", () => selectRef.current?.(point.id))
        .addTo(layer.current);
    });
    if (!fitted.current && points.length > 1) {
      fitted.current = true;
      map.current.fitBounds(points.map((point) => point.coords), { padding: [36, 36] });
    }
  }, [points, theme]);

  return <div ref={container} className="noc-map" role="img" aria-label="Mapa de planteles de la UAEH por estado" />;
}
