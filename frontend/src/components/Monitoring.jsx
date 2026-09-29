import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import PortPanel from "./PortPanel";

function healthLabel(device) {
  if (!device.activo) return "Inactivo";
  return device.lectura_correcta ? "Lectura válida" : "Sin respuesta";
}

export default function Monitoring({ focusDevice = null, onFocusHandled = () => {} }) {
  const [devices, setDevices] = useState([]);
  const [ports, setPorts] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setError("");
    try {
      setDevices(await api.list("switches"));
    } catch (exception) {
      setError(exception.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => clearInterval(timer);
  }, []);

  const folders = useMemo(() => {
    const grouped = new Map();
    devices.forEach((device) => {
      const site = device.plantel_nombre || "Sin plantel asignado";
      if (!grouped.has(site)) grouped.set(site, []);
      grouped.get(site).push(device);
    });
    return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [devices]);

  async function showPorts(device) {
    setPorts({ device, items: [], loading: true });
    try {
      setPorts({ device, items: await api.ports(device.id), loading: false });
    } catch (exception) {
      setPorts(null);
      setError(exception.message);
    }
  }

  async function refreshPorts() {
    if (!ports) return;
    try {
      setPorts((current) => ({ ...current, items: current.items }));
      const items = await api.ports(ports.device.id);
      setPorts((current) => current ? { ...current, items, loading: false } : current);
    } catch (exception) {
      setError(exception.message);
    }
  }

  // Llegada desde "Ver puertos" en Resumen: abre directamente ese switch.
  useEffect(() => {
    if (!focusDevice) return;
    showPorts(focusDevice);
    onFocusHandled();
  }, [focusDevice]);

  useEffect(() => {
    if (!ports || ports.loading) return undefined;
    const timer = setInterval(refreshPorts, 180000);
    return () => clearInterval(timer);
  }, [ports?.device?.id, ports?.loading]);

  return (
    <>
      <div className="section-title page-heading">
        <div>
          <span className="eyebrow">OPERACIÓN</span>
          <h2>Monitoreo por plantel</h2>
          <p>Abre una carpeta para consultar los switches que pertenecen a cada lugar.</p>
        </div>
        <button type="button" onClick={refresh}>Actualizar</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {loading ? (
        <p role="status">Cargando monitoreo…</p>
      ) : !folders.length ? (
        <section className="card empty">No hay switches en el inventario.</section>
      ) : (
        <div className="monitor-folders">
          {folders.map(([site, siteDevices], index) => (
            <details className="monitor-folder" key={site} open={index === 0}>
              <summary>
                <span className="folder-icon">▾</span>
                <strong>{site}</strong>
                <small>{siteDevices.length} switch{siteDevices.length === 1 ? "" : "es"}</small>
              </summary>
              <div className="monitor-devices">
                {siteDevices.map((device) => (
                  <article className="monitor-device" key={device.id}>
                    <div>
                      <strong>{device.nombre}</strong>
                      <small>{device.hostname} · {device.modelo || "Modelo pendiente"}</small>
                    </div>
                    <span className={device.lectura_correcta ? "health-ok" : "health-bad"}>
                      {healthLabel(device)}
                    </span>
                    <button type="button" onClick={() => showPorts(device)}>Ver puertos</button>
                  </article>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
      {ports && <PortPanel device={ports.device} items={ports.items} loading={ports.loading} onClose={() => setPorts(null)} />}
    </>
  );
}
