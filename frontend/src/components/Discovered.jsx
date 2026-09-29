import { useEffect, useState } from "react";
import { api } from "../api/client";
import { timeAgo } from "../utils/format";

const ORIGIN = { cdp: "Vecino CDP", barrido: "Barrido SNMP" };

/** Equipos vistos en la red que no están en el inventario (sólo editores). */
export default function Discovered({ onAdd, refreshKey = 0 }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");

  async function load() {
    try {
      setItems(await api.discovered());
      setError("");
    } catch (exception) {
      setError(exception.message);
    }
  }
  useEffect(() => {
    load();
  }, [refreshKey]);

  async function ignore(item) {
    try {
      await api.ignoreDiscovered(item.id);
      await load();
    } catch (exception) {
      setError(exception.message);
    }
  }

  if (!items.length && !error) return null;
  return (
    <section className="card discovered">
      <div className="section-title">
        <div>
          <h2>Equipos descubiertos ({items.length})</h2>
          <small>Vistos por CDP o por el barrido SNMP y aún no están en el inventario.</small>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
      <ul className="maintenance-list">
        {items.map((item) => (
          <li key={item.id}>
            <div>
              <strong>{item.nombre || item.ip}</strong>
              <small>
                {item.ip} · {ORIGIN[item.origen] || item.origen}
                {item.visto_desde && ` desde ${item.visto_desde}`}
                {item.plataforma && ` · ${item.plataforma}`} · visto {timeAgo(item.ultima_vez)}
              </small>
            </div>
            <div className="report-actions">
              <button type="button" className="primary" onClick={() => onAdd(item)}>Agregar al inventario</button>
              <button type="button" onClick={() => ignore(item)}>Ignorar</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
