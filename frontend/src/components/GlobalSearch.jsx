import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

const MIN_LENGTH = 3;
const MATCH_LABEL = { ip: "IP", mac: "MAC", telefono: "MAC teléfono", descripcion: "Descripción" };
const STATUS = { up: "Activo", down: "Inactivo" };

/** Buscador global: ¿en qué switch y puerto está conectado este equipo? */
export default function GlobalSearch({ onOpen }) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const latest = useRef(0);

  useEffect(() => {
    const text = query.trim();
    if (text.length < MIN_LENGTH) {
      setResult(null);
      setError("");
      return undefined;
    }
    const timer = setTimeout(async () => {
      const id = ++latest.current;
      try {
        const data = await api.search(text);
        // Sólo cuenta la respuesta de lo último que se escribió.
        if (id === latest.current) {
          setResult(data);
          setError("");
        }
      } catch (exception) {
        if (id === latest.current) setError(exception.message);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const closeOutside = (event) => {
      if (box.current && !box.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", closeOutside);
    return () => document.removeEventListener("mousedown", closeOutside);
  }, []);

  function choose(device, portId = null) {
    setOpen(false);
    onOpen(device, portId);
  }

  const ports = result?.puertos || [];
  const switches = result?.switches || [];
  const showPanel = open && query.trim().length >= MIN_LENGTH && (result || error);
  return (
    <div className="global-search" ref={box}>
      <input
        type="search"
        aria-label="Buscar equipo por MAC, IP o switch"
        placeholder="Buscar MAC, IP o switch…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => event.key === "Escape" && setOpen(false)}
      />
      {showPanel && (
        <div className="search-results" role="region" aria-label="Resultados de búsqueda">
          {error && <p role="alert">{error}</p>}
          {!error && !ports.length && !switches.length && (
            <p className="empty">Sin coincidencias para “{result.query}”.</p>
          )}
          {switches.length > 0 && (
            <>
              <h3>Switches</h3>
              {switches.map((device) => (
                <button type="button" key={`sw-${device.id}`} onClick={() => choose(device)}>
                  <strong>{device.nombre}</strong>
                  <small>{device.hostname} · {device.plantel_nombre}</small>
                </button>
              ))}
            </>
          )}
          {ports.length > 0 && (
            <>
              <h3>Equipos conectados</h3>
              {ports.map((port) => (
                <button type="button" key={`port-${port.id}`} onClick={() => choose(port.switch, port.id)}>
                  <strong>
                    {port.switch.nombre} · {port.nombre}
                    {port.es_trunk && <span className="badge search-trunk">troncal</span>}
                  </strong>
                  <small>
                    {MATCH_LABEL[port.coincide]}: <mark>{port.valor}</mark>
                    {port.vlan != null && ` · VLAN ${port.vlan}`} · {port.switch.plantel_nombre}
                    {` · ${STATUS[port.estado_operativo] || "Desconocido"}`}
                  </small>
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
