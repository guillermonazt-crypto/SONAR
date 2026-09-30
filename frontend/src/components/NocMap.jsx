import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import hidalgo from "../utils/hidalgo.geo.json";
import { HIDALGO_CENTER } from "../utils/locations";
import { cssVar } from "../utils/theme";

const LEVEL_COLOR = { critical: "signal-critical", warning: "signal-warning", ok: "signal-ok", none: "faint" };
const LEVEL_TEXT = { critical: "Crítico", warning: "Atención", ok: "Sano", none: "Sin equipos" };
const HIDALGO = hidalgo.features.find((feature) => feature.properties.id === "hid");
const NEIGHBORS = { ...hidalgo, features: hidalgo.features.filter((feature) => feature.properties.id !== "hid") };
// Rectángulo amplio con Hidalgo como hueco: atenúa todo lo que queda fuera del estado.
const MASK = {
  type: "Feature",
  geometry: {
    type: "Polygon",
    coordinates: [[[-106, 13], [-90, 13], [-90, 27], [-106, 27], [-106, 13]], ...HIDALGO.geometry.coordinates],
  },
};
const HIDALGO_BOUNDS = L.geoJSON(HIDALGO).getBounds();


/** Mapa de Hidalgo con un punto por plantel coloreado por su peor estado. */
export default function NocMap({ points, theme = "dark", onSelect }) {
  const container = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);
  const shapes = useRef(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  useEffect(() => {
    map.current = L.map(container.current, {
      center: HIDALGO_CENTER,
      zoom: 8,
      minZoom: 7,
      maxBounds: HIDALGO_BOUNDS.pad(0.6),
      maxBoundsViscosity: 0.8,
      zoomSnap: 0.25,
      zoomControl: false,
      attributionControl: true,
      scrollWheelZoom: false,
    });
    // Sin mapa base de internet (CARTO ya pide API key): Hidalgo se dibuja en vectorial.
    // fitBounds con el contenedor en 0×0 da "Invalid LatLng NaN": se ajusta cuando ya tiene tamaño.
    const fit = () => {
      const { clientWidth, clientHeight } = container.current || {};
      if (!map.current || !clientWidth || !clientHeight) return;
      map.current.invalidateSize();
      map.current.fitBounds(HIDALGO_BOUNDS, { padding: [24, 24] });
    };
    fit();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    observer?.observe(container.current);
    map.current.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
    L.control.zoom({ position: "bottomright" }).addTo(map.current);
    map.current.attributionControl.addAttribution('Contornos: <a href="https://mapsvg.com/maps/mexico">MapSVG</a> (CC BY 4.0)');
    shapes.current = L.layerGroup().addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => {
      observer?.disconnect();
      map.current.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    // Estado de Hidalgo resaltado; lo de alrededor (estados vecinos) queda atenuado.
    shapes.current.clearLayers();
    const bg = cssVar("bg") || "#000";
    L.geoJSON(MASK, { interactive: false, style: { stroke: false, fillColor: bg, fillOpacity: 0.55 } }).addTo(shapes.current);
    L.geoJSON(NEIGHBORS, {
      interactive: false,
      style: { color: cssVar("border-heavy") || "#888", weight: 1, fill: false, opacity: 0.8 },
      onEachFeature: (feature, shape) => shape.bindTooltip(feature.properties.nombre, { permanent: true, direction: "center", className: "noc-state-label" }),
    }).addTo(shapes.current);
    L.geoJSON(HIDALGO, {
      interactive: false,
      style: { color: cssVar("accent") || "#0a84ff", weight: 2, fillColor: cssVar("accent") || "#0a84ff", fillOpacity: 0.08 },
    }).addTo(shapes.current);
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
  }, [points, theme]);

  return <div ref={container} className="noc-map" role="img" aria-label="Mapa de planteles de la UAEH por estado" />;
}
