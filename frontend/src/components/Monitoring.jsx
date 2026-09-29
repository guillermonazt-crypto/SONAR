import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useAutoRefresh } from "../utils/refresh";
import { loadView, saveView } from "../utils/viewState";
import PortPanel from "./PortPanel";

// Mismo nivel verde/amarillo/rojo que Resumen: lo calcula switches/health.py.
const LEVELS = {
  ok: { label: "Normal", icon: "●" },
  warning: { label: "Atención", icon: "▲" },
  critical: { label: "En riesgo", icon: "✕" },
};

function HealthBadge({ device }) {
  if (!device.activo) return <span className="status-badge status-inactive">Inactivo</span>;
  const level = LEVELS[device.estado] ? device.estado : "ok";
  return (
    <span className={`status-badge status-${level}`}>
      <span aria-hidden="true">{LEVELS[level].icon}</span> {LEVELS[level].label}
    </span>
  );
}

function SiteCounts({ devices }) {
  const count = (level) => devices.filter((device) => device.activo && device.estado === level).length;
  const critical = count("critical");
  const warning = count("warning");
  if (!critical && !warning) return null;
  return (
    <span className="folder-health">
      {critical > 0 && <span className="status-critical-text">{critical} en riesgo</span>}
      {warning > 0 && <span className="status-warning-text">{warning} con atención</span>}
    </span>
  );
}

export default function Monitoring({ focus = null, onFocusHandled = () => {} }) {
  const [devices, setDevices] = useState([]);
  const [ports, setPorts] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // Carpetas abiertas por el usuario; null = aún no eligió (se abre la primera).
  const [openSites, setOpenSites] = useState(() => loadView("sites"));
  // Cambia al abrir un switch desde otra vista: el panel se vuelve a montar y abre el puerto pedido.
  const [panelKey, setPanelKey] = useState(0);
  const restored = useRef(false);

  async function refresh() {
    try {
      setDevices(await api.list("switches"));
      setError("");
    } catch (exception) {
      setError(exception.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);
  useAutoRefresh(refresh);

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
    restored.current = true;
    if (loadView("switch") !== device.id) saveView("port", null);
    saveView("switch", device.id);
    setPorts({ device, items: [], loading: true });
    let items = [];
    try {
      items = await api.ports(device.id);
    } catch (exception) {
      // Un fallo de red no cierra el switch que se está viendo: el refresco lo reintenta.
      setError(exception.message);
    }
    setPorts((current) => current?.device.id === device.id ? { device, items, loading: false } : current);
  }

  function closePorts() {
    saveView("switch", null);
    saveView("port", null);
    setPorts(null);
  }

  // Tras recargar la página se vuelve a abrir el switch que se estaba viendo.
  useEffect(() => {
    if (restored.current || loading || focus) return;
    restored.current = true;
    const saved = loadView("switch");
    const device = saved && devices.find((item) => item.id === saved);
    if (device) showPorts(device);
    else saveView("switch", null);
  }, [loading, devices]);

  function toggleSite(site, open, current) {
    if (open === current.includes(site)) return;
    const next = open ? [...current, site] : current.filter((name) => name !== site);
    saveView("sites", next);
    setOpenSites(next);
  }

  async function refreshPorts() {
    if (!ports || ports.loading) return;
    const id = ports.device.id;
    try {
      const items = await api.ports(id);
      // Si mientras tanto se cerró el panel o se abrió otro switch, se descarta.
      setPorts((current) => current?.device.id === id ? { ...current, items } : current);
    } catch (exception) {
      setError(exception.message);
    }
  }

  // Llegada desde Resumen o el buscador: abre ese switch y, si se pidió, el puerto.
  useEffect(() => {
    if (!focus) return;
    showPorts(focus.device);
    saveView("port", focus.portId ?? null);
    setPanelKey((key) => key + 1);
    onFocusHandled();
  }, [focus]);

  useAutoRefresh(refreshPorts, Boolean(ports && !ports.loading));

  const sitesOpen = openSites ?? (folders.length ? [folders[0][0]] : []);
  // El panel muestra los datos del switch recién refrescados, no la copia de cuando se abrió.
  const panelDevice = ports && (devices.find((device) => device.id === ports.device.id) || ports.device);

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
          {folders.map(([site, siteDevices]) => (
            <details
              className="monitor-folder"
              key={site}
              open={sitesOpen.includes(site)}
              onToggle={(event) => toggleSite(site, event.currentTarget.open, sitesOpen)}
            >
              <summary>
                <span className="folder-icon">▾</span>
                <strong>{site}</strong>
                <small>{siteDevices.length} switch{siteDevices.length === 1 ? "" : "es"}</small>
                <SiteCounts devices={siteDevices} />
              </summary>
              <div className="monitor-devices">
                {siteDevices.map((device) => (
                  <article className="monitor-device" key={device.id}>
                    <div>
                      <strong>{device.nombre}</strong>
                      <small>{device.hostname} · {device.modelo || "Modelo pendiente"}</small>
                      {device.activo && device.motivos?.length > 0 && (
                        <ul className="device-reasons monitor-reasons">
                          {device.motivos.map((reason, index) => (
                            <li key={index} className={`reason-${reason.level}`}>{reason.text}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div className="device-status">
                      <HealthBadge device={device} />
                      {device.mantenimiento && (
                        <span className="status-badge status-maintenance" title={device.mantenimiento.motivo}>
                          Mantenimiento hasta {new Date(device.mantenimiento.hasta).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </span>
                      )}
                    </div>
                    <button type="button" onClick={() => showPorts(device)}>Ver puertos</button>
                  </article>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
      {ports && <PortPanel key={panelKey} device={panelDevice} items={ports.items} loading={ports.loading} onClose={closePorts} />}
    </>
  );
}
