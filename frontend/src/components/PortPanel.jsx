import { useEffect, useRef, useState } from "react";
import { cssVar, useTheme } from "../utils/theme";
import { loadView, saveView } from "../utils/viewState";
import { Chart, CategoryScale, LinearScale, BarElement, BarController, LineElement, PointElement, LineController, Tooltip, Legend } from "chart.js";
import { api } from "../api/client";
import { formatBytes, formatRate, timeAgo } from "../utils/format";

Chart.register(CategoryScale, LinearScale, BarElement, BarController, LineElement, PointElement, LineController, Tooltip, Legend);

const POE_TEXT = {
  deliveringPower: "Entregando energía",
  searching: "Buscando dispositivo",
  disabled: "Deshabilitado",
  fault: "Falla",
  otherFault: "Falla",
  test: "En prueba",
};

function formatSpeed(mbps) {
  if (!mbps) return null;
  return mbps >= 1000 ? `${mbps / 1000} Gbps` : `${mbps} Mbps`;
}

const statusText = {
  up: "Activo",
  down: "Inactivo",
  testing: "Prueba",
  unknown: "Desconocido",
  dormant: "Dormido",
  notPresent: "No presente",
  lowerLayerDown: "Capa inferior caída",
};

function portFamily(name) {
  if (/FastEthernet0\/|GigabitEthernet0\/[12]|TenGigabit|FortyGigabit|TwentyFiveGigE|Ethernet1\/1/.test(name)) {
    if (/FastEthernet0\//.test(name)) return "access";
    return "uplinks";
  }
  return "access";
}

function isPhysicalPort(name) {
  const value = name || "";
  return !value.endsWith("/0/0") && !value.endsWith("0/0") && /^(FastEthernet0\/\d+|GigabitEthernet0\/[1-9]\d*|GigabitEthernet\d+\/\d+\/\d+|TenGigabitEthernet\d+\/\d+\/\d+|TwentyFiveGigE\d+\/\d+\/\d+|FortyGigabitEthernet\d+\/\d+\/\d+)$/.test(value);
}

function hasVoiceVlan(port) {
  const vlan = Number(port.voice_vlan);
  return Number.isFinite(vlan) && vlan > 0 && vlan !== 4096;
}

function localPortNumber(name, fallback) {
  const match = String(name || "").match(/\/(\d+)$/);
  return match ? match[1] : (fallback ?? "?");
}

function hasDamage(port) {
  return port.estado === "rojo" || [port.errores_entrada, port.errores_salida, port.errores_crc]
    .some((value) => Number.isFinite(value) && value > 0);
}

function errorTotal(port) {
  return [port.errores_entrada, port.errores_salida, port.errores_crc]
    .filter((value) => Number.isFinite(value))
    .reduce((total, value) => total + value, 0);
}

function errorGuidance(port) {
  const input = Number(port.errores_entrada) || 0;
  const output = Number(port.errores_salida) || 0;
  const crc = Number(port.errores_crc) || 0;
  if (crc > 0) return "CRC: revisar cableado, conectores, interferencia y la NIC del equipo.";
  if (input > 0) return "Entrada: revisar cableado, negociación velocidad/dúplex y la NIC del equipo.";
  if (output > 0) return "Salida: revisar congestión, colisiones o saturación del enlace.";
  return "No hay contadores de error reportados.";
}

function TrafficChart({ input, output }) {
  const canvas = useRef(null);
  const chart = useRef(null);
  const theme = useTheme();
  useEffect(() => {
    if (!canvas.current) return undefined;
    const instance = new Chart(canvas.current, {
      type: "bar",
      data: {
        labels: ["Entrada", "Salida"],
        datasets: [{
          label: "Consumo",
          data: [input || 0, output || 0],
          backgroundColor: [cssVar("accent"), cssVar("violet")],
          borderRadius: 5,
          barThickness: 28,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => formatRate(context.raw) } } },
        scales: {
          y: { beginAtZero: true, ticks: { color: cssVar("muted"), callback: (value) => formatRate(value) }, grid: { color: cssVar("grid-line") } },
          x: { ticks: { color: cssVar("text-2") }, grid: { display: false } },
        },
      },
    });
    chart.current = instance;
    return () => {
      instance.destroy();
      chart.current = null;
    };
  }, [theme]);
  // Cada refresco trae una tasa nueva: se actualizan las barras sin recrear la gráfica.
  useEffect(() => {
    if (!chart.current?.canvas) return;
    chart.current.data.datasets[0].data = [input || 0, output || 0];
    chart.current.update("none");
  }, [input, output]);
  return <div className="traffic-chart"><canvas ref={canvas} aria-label="Gráfica de consumo del puerto" /></div>;
}

function HistoryChart({ points }) {
  const canvas = useRef(null);
  const theme = useTheme();
  useEffect(() => {
    if (!canvas.current || !points.length) return undefined;
    const chart = new Chart(canvas.current, {
      type: "line",
      data: {
        labels: points.map((point) => new Date(point.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })),
        datasets: [
          { label: "Entrada acumulada", data: points.map((point) => point.entrada), borderColor: cssVar("accent"), backgroundColor: cssVar("accent-ring"), tension: 0.25 },
          { label: "Salida acumulada", data: points.map((point) => point.salida), borderColor: cssVar("violet"), backgroundColor: `${cssVar("violet")}33`, tension: 0.25 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: cssVar("text-2") } }, tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${formatBytes(context.raw)}` } } },
        scales: { y: { ticks: { color: cssVar("muted"), callback: (value) => formatBytes(value) }, grid: { color: cssVar("grid-line") } }, x: { ticks: { color: cssVar("muted") }, grid: { display: false } } },
      },
    });
    return () => chart.destroy();
  }, [points, theme]);
  return <div className="traffic-chart history-chart"><canvas ref={canvas} aria-label="Histórico de tráfico del puerto" /></div>;
}

export default function PortPanel({ device, items, loading, onClose }) {
  const [selected, setSelected] = useState(null);
  const restoredPort = useRef(false);
  async function openPort(port) {
    restoredPort.current = true;
    saveView("port", port.id);
    setSelected(port);
    try {
      const result = await api.portHistory(port.id);
      setHistory((current) => ({ ...current, [port.id]: result.points || [] }));
    } catch {
      setHistory((current) => ({ ...current, [port.id]: [] }));
    }
  }
  function closePort() {
    saveView("port", null);
    setSelected(null);
  }
  // Tras recargar la página se vuelve a abrir el puerto que se estaba viendo.
  useEffect(() => {
    if (restoredPort.current || loading || !items.length) return;
    restoredPort.current = true;
    const port = items.find((item) => item.id === loadView("port"));
    if (port) openPort(port);
  }, [loading, items]);
  const [rates, setRates] = useState({});
  const [history, setHistory] = useState({});
  useEffect(() => {
    const closeOnEscape = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  const previousTraffic = useRef(new Map());
  useEffect(() => {
    const now = Date.now();
    const next = {};
    items.forEach((port) => {
      // El worker ya calcula la tasa entre sus dos últimos sondeos.
      if (port.bps_entrada != null && port.bps_salida != null) {
        next[port.id] = { input: port.bps_entrada, output: port.bps_salida };
        return;
      }
      const input = Number(port.octetos_entrada);
      const output = Number(port.octetos_salida);
      if (!Number.isFinite(input) || !Number.isFinite(output)) return;
      // Se mide contra la hora de la lectura del worker, no la del refresco:
      // refrescar más rápido que el worker no debe dar tasas en cero.
      const at = Date.parse(port.actualizado) || now;
      const previous = previousTraffic.current.get(port.id);
      if (previous && at === previous.at) {
        if (previous.rate) next[port.id] = previous.rate;
        return;
      }
      let rate = null;
      if (previous && at > previous.at && input >= previous.input && output >= previous.output) {
        const seconds = (at - previous.at) / 1000;
        rate = {
          input: Math.round(((input - previous.input) * 8) / seconds),
          output: Math.round(((output - previous.output) * 8) / seconds),
        };
        next[port.id] = rate;
      }
      previousTraffic.current.set(port.id, { input, output, at, rate });
    });
    setRates(next);
    // El detalle abierto muestra la lectura más reciente del mismo puerto.
    setSelected((current) => (current && items.find((port) => port.id === current.id)) || current);
  }, [items]);
  const ordered = items
    .filter((port) => isPhysicalPort(port.nombre))
    .sort((a, b) => a.indice - b.indice);
  const access = ordered.filter((port) => portFamily(port.nombre) === "access");
  const uplinks = ordered.filter(
    (port) => portFamily(port.nombre) === "uplinks",
  );
  const maxTraffic = Math.max(
    1,
    ...ordered.flatMap((port) => [port.octetos_entrada || 0, port.octetos_salida || 0]),
  );
  const summary = ordered.reduce(
    (result, port) => {
      const key =
        port.estado_operativo in statusText ? port.estado_operativo : "unknown";
      result[key] += 1;
      return result;
    },
    {
      up: 0,
      down: 0,
      unknown: 0,
      testing: 0,
      dormant: 0,
      notPresent: 0,
      lowerLayerDown: 0,
    },
  );
  const renderPort = (port) => {
    const state = statusText[port.estado_operativo]
      ? port.estado_operativo
      : "unknown";
    const errors = errorTotal(port);
    const voice = hasVoiceVlan(port);
    const trunk = Boolean(port.es_trunk);
    const damaged = hasDamage(port);
    const localNumber = localPortNumber(port.nombre, port.indice);
    const inputTraffic = Number(port.octetos_entrada) || 0;
    const outputTraffic = Number(port.octetos_salida) || 0;
    return (
      <button
        type="button"
        className={`physical-port port-${state}${voice ? " port-voice" : ""}${trunk ? " port-trunk" : ""}${damaged ? " port-damaged" : ""}`}
        key={port.id}
        data-tooltip={`${port.nombre}${port.descripcion ? ` · ${port.descripcion}` : ""} · ${statusText[state]}${trunk ? " · TRUNK" : ""}${voice ? ` · Voice VLAN ${port.voice_vlan}` : ""}${damaged ? " · DAÑADO" : ""}${port.vecino_nombre ? ` · → ${port.vecino_nombre}` : ""}${port.uso_pct != null ? ` · ${Math.round(port.uso_pct)}% uso` : ""} · ${errors} errores`}
        aria-label={`${port.nombre}: ${statusText[state]}; ${errors} errores`}
        onClick={() => openPort(port)}
      >
        <span className="port-led status-led" aria-hidden="true" />
        {voice && <span className="port-led voice-led" aria-label="Voice VLAN" />}
        {damaged && <span className="port-led damage-led" aria-label="Puerto dañado" />}
        <span>{localNumber}</span>
        <span className="traffic-meter" aria-hidden="true">
          <i className="traffic-in" style={{ width: `${(inputTraffic / maxTraffic) * 100}%` }} />
          <i className="traffic-out" style={{ width: `${(outputTraffic / maxTraffic) * 100}%` }} />
        </span>
      </button>
    );
  };
  return (
    <div className="port-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="card ports port-modal" role="dialog" aria-modal="true" aria-labelledby="port-panel-title" aria-live="polite">
      <div className="section-title">
        <div>
          <span className="eyebrow">VISTA FÍSICA</span>
          <h2 id="port-panel-title">Puertos · {device.nombre}</h2>
          <small>
            {device.hostname} · coloca el cursor sobre un puerto para ver su
            estado
          </small>
        </div>
        <button type="button" onClick={onClose}>
          Cerrar
        </button>
      </div>
      {loading ? (
        <p role="status">Cargando puertos…</p>
      ) : !ordered.length ? (
        <p className="empty">
          Aún no hay lecturas de puertos para este switch.
        </p>
      ) : (
        <>
          <div className="port-summary" aria-label="Resumen de puertos">
            <span>
              <i className="legend-dot dot-up" />
              {summary.up} activos
            </span>
            <span>
              <i className="legend-dot dot-down" />
              {summary.down} inactivos
            </span>
            <span>
              <i className="legend-dot dot-unknown" />
              {summary.unknown} desconocidos
            </span>
            <span>{access.length} acceso</span>
            <span>{uplinks.length} uplinks</span>
          </div>
          <div
            className="switch-face"
            role="img"
            aria-label={`Panel frontal de ${device.nombre}`}
          >
            <div className="switch-brand">
              <strong>CISCO</strong>
              <span>SONAR · {device.modelo || device.rol}</span>
            </div>
            <div className="port-bank">
              <h3>Puertos de acceso</h3>
              <div className="physical-grid">{access.map(renderPort)}</div>
            </div>
            {uplinks.length > 0 && (
              <div className="port-bank">
                <h3>Uplinks</h3>
                <div className="physical-grid uplink-grid">
                  {uplinks.map(renderPort)}
                </div>
              </div>
            )}
            <div className="port-legend" aria-label="Leyenda de estados">
              <span>
                <i className="legend-dot dot-up" />
                Verde · activo
              </span>
              <span>
                <i className="legend-dot dot-down" />
                Rojo · inactivo
              </span>
              <span>
                <i className="legend-dot dot-unknown" />
                Ámbar · sin lectura
              </span>
              <span>
                <i className="legend-dot dot-voice" />
                Azul · Voice VLAN
              </span>
              <span>
                <i className="legend-dot dot-trunk" />
                Borde naranja · Trunk
              </span>
              <span>
                <i className="legend-dot dot-damaged" />
                Amarillo limón · Daño/error
              </span>
            </div>
          </div>
          {selected && (
            <div className="port-detail-backdrop" onMouseDown={(event) => event.target === event.currentTarget && closePort()}>
            <section className="port-detail" role="dialog" aria-modal="true" aria-labelledby="port-detail-title" aria-live="polite">
              <div className="section-title">
                <div>
                  <span className="eyebrow">DETALLE DEL PUERTO</span>
                  <h3 id="port-detail-title">{selected.nombre}</h3>
                </div>
                <button type="button" onClick={closePort}>
                  Cerrar detalle
                </button>
              </div>
              <dl>
                <div>
                  <dt>Descripción</dt>
                  <dd>{selected.descripcion || "Sin descripción"}</dd>
                </div>
                <div>
                  <dt>Tipo de enlace</dt>
                  <dd>{selected.es_trunk ? "Troncal (trunk)" : "Acceso"}</dd>
                </div>
                <div>
                  <dt>Vecino (CDP)</dt>
                  <dd>
                    {selected.vecino_nombre ? (
                      <>
                        <strong>{selected.vecino_nombre}</strong>
                        {selected.vecino_puerto && ` · ${selected.vecino_puerto}`}
                        <small className="detail-note">
                          {[selected.vecino_plataforma, selected.vecino_ip].filter(Boolean).join(" · ")}
                        </small>
                      </>
                    ) : (
                      "Sin vecino CDP"
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Velocidad y uso</dt>
                  <dd>
                    {formatSpeed(selected.velocidad_mbps) || "Sin lectura"}
                    {selected.uso_pct != null && (
                      <span className={selected.uso_pct >= 90 ? "status-critical-text" : selected.uso_pct >= 70 ? "status-warning-text" : ""}>
                        {` · ${selected.uso_pct.toFixed(1)}% de uso`}
                      </span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Último cambio de estado</dt>
                  <dd>
                    {selected.ultimo_cambio ? timeAgo(selected.ultimo_cambio) : "Sin lectura"}
                    {selected.estado_operativo !== "up" && selected.ultimo_activo && (
                      <small className="detail-note">Sin enlace desde {new Date(selected.ultimo_activo).toLocaleString()}</small>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>PoE</dt>
                  <dd>
                    {selected.poe_estado ? (
                      <>
                        {POE_TEXT[selected.poe_estado] || selected.poe_estado}
                        {selected.poe_mw != null && ` · ${(selected.poe_mw / 1000).toFixed(1)} W`}
                      </>
                    ) : (
                      "No publicado"
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Estado</dt>
                  <dd>
                    {statusText[selected.estado_operativo] || "Desconocido"}
                  </dd>
                </div>
                <div>
                  <dt>Diagnóstico</dt>
                  <dd>
                    {errorTotal(selected) > 0
                      ? selected.estado_operativo === "up"
                        ? "Activo con errores acumulados"
                        : "Errores detectados"
                      : "Sin errores reportados"}
                  </dd>
                </div>
                <div>
                  <dt>IP detectada (ARP)</dt>
                  <dd>{selected.ip_equipo || "Sin lectura"}</dd>
                </div>
                <div>
                  <dt>MAC del equipo</dt>
                  <dd>{selected.mac_equipo || "Sin lectura"}</dd>
                </div>
                <div>
                  <dt>VLAN</dt>
                  <dd>{selected.vlan ?? "Sin lectura"}</dd>
                </div>
                <div>
                  <dt>Voice VLAN</dt>
                  <dd>{selected.voice_vlan ?? "Sin lectura"}</dd>
                </div>
                <div>
                  <dt>DHCP snooping</dt>
                  <dd>
                    {selected.dhcp === null || selected.dhcp === undefined
                      ? "No publicado por SNMP"
                      : selected.dhcp
                        ? "Sí"
                        : "No"}
                  </dd>
                </div>
                <div>
                  <dt>MAC del teléfono</dt>
                  <dd>{selected.mac_telefono || "Sin lectura"}</dd>
                </div>
                <div>
                  <dt>Errores entrada / salida / CRC</dt>
                  <dd>
                    {[
                      selected.errores_entrada,
                      selected.errores_salida,
                      selected.errores_crc,
                    ]
                      .map((value) => value ?? "—")
                      .join(" / ")}
                  </dd>
                </div>
                <div>
                  <dt>Qué revisar</dt>
                  <dd>{errorGuidance(selected)}</dd>
                </div>
                <div>
                  <dt>Tráfico acumulado</dt>
                  <dd>
                    Entrada: {formatBytes(selected.octetos_entrada == null ? NaN : Number(selected.octetos_entrada))} · Salida: {formatBytes(selected.octetos_salida == null ? NaN : Number(selected.octetos_salida))}
                    <div className="traffic-detail" aria-label="Gráfica de tráfico acumulado">
                      <i className="traffic-in" style={{ width: `${Math.min(100, ((Number(selected.octetos_entrada) || 0) / maxTraffic) * 100)}%` }} />
                      <i className="traffic-out" style={{ width: `${Math.min(100, ((Number(selected.octetos_salida) || 0) / maxTraffic) * 100)}%` }} />
                    </div>
                  </dd>
                </div>
                <div>
                  <dt>Consumo actual estimado</dt>
                  <dd>
                    Entrada: <strong>{formatRate(rates[selected.id]?.input ?? NaN)}</strong>
                    <br />
                    Salida: <strong>{formatRate(rates[selected.id]?.output ?? NaN)}</strong>
                    <small>Calculado en memoria entre las dos últimas lecturas SNMP. No se guarda en la base.</small>
                    {rates[selected.id] ? (
                      <TrafficChart input={rates[selected.id].input} output={rates[selected.id].output} />
                    ) : (
                      <p className="traffic-pending">Esperando la siguiente lectura para graficar el consumo…</p>
                    )}
                    {history[selected.id]?.length > 0 && <HistoryChart points={history[selected.id]} />}
                  </dd>
                </div>
                <div className="port-note">
                  <dt>Nota</dt>
                  <dd>Los contadores SNMP son acumulativos. Compara una nueva lectura después de corregir o limpiar el contador para confirmar que el error dejó de aumentar.</dd>
                </div>
              </dl>
            </section>
            </div>
          )}
        </>
      )}
    </section>
    </div>
  );
}
