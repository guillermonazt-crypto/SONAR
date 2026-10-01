import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { notify, playAlarm, requestNotifications } from "../utils/alarm";
import { siteCoordinates } from "../utils/locations";
import { setRefreshInterval, useAutoRefresh } from "../utils/refresh";
import { timeAgo } from "../utils/format";
import { useTheme } from "../utils/theme";

// Leaflet sólo se descarga en el NOC.
const NocMap = lazy(() => import("./NocMap"));

const NOC_REFRESH = [3, 10, 30];
const LEVEL_TEXT = { critical: "Crítico", warning: "Atención", ok: "Sano", none: "Sin equipos" };
const ORDER = { critical: 0, warning: 1, ok: 2, none: 3 };

function Kpi({ label, value, detail, tone = "" }) {
  return (
    <article className={`noc-kpi${tone ? ` tone-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </article>
  );
}

/** Planteles que pasaron a crítico desde la lectura anterior (no en la primera). */
export function newlyCritical(previous, sites) {
  if (!previous) return [];
  return sites.filter((site) => site.estado === "critical" && previous.get(site.id) !== "critical");
}

/** Panel NOC: mapa de los planteles, KPIs de la red y aviso cuando uno pasa a rojo. */
export default function Noc({ sites = [], onOpenSite = () => {}, refreshSeconds, sound = true, onSound = () => {} }) {
  const theme = useTheme();
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [incidents, setIncidents] = useState([]);
  const previous = useRef(null);
  const soundRef = useRef(sound);
  soundRef.current = sound;

  async function refresh() {
    try {
      // El NOC siempre muestra toda la red, sin importar el plantel elegido.
      const data = await api.summary(false, "");
      const board = data?.planteles || [];
      const changed = newlyCritical(previous.current, board);
      previous.current = new Map(board.map((site) => [site.id, site.estado]));
      if (changed.length) {
        const names = changed.map((site) => site.nombre).join(", ");
        if (soundRef.current) playAlarm();
        notify("SONAR · plantel en rojo", `${names} pasó a estado crítico.`);
        const at = new Date().toISOString();
        setIncidents((current) => [...changed.map((site) => ({ id: site.id, nombre: site.nombre, at })), ...current.filter((item) => !changed.some((site) => site.id === item.id))].slice(0, 5));
      }
      setSummary(data);
      setError("");
    } catch (exception) {
      setError(exception.message);
    }
  }
  useEffect(() => {
    refresh();
  }, []);
  useAutoRefresh(refresh);

  const board = summary?.planteles || [];
  const devices = (summary?.switches || []).filter((device) => device.activo !== false);
  const online = devices.filter((device) => device.lectura_correcta).length;
  const availability = devices.length ? Math.round((online * 1000) / devices.length) / 10 : null;
  const openAlerts = board.reduce((sum, site) => sum + (site.alertas_abiertas || 0), 0);
  const pending = board.reduce((sum, site) => sum + (site.alertas_sin_reconocer || 0), 0);
  const count = (level) => board.filter((site) => site.estado === level).length;
  const critical = board.filter((site) => site.estado === "critical");

  // Ubicación: la del administrador (planteles) o la tabla conocida; los repetidos se separan un poco.
  const points = useMemo(() => {
    const extra = new Map(sites.map((site) => [site.id, site]));
    const seen = new Map();
    return board
      .map((site) => {
        const coords = siteCoordinates({ ...site, ubicacion: extra.get(site.id)?.ubicacion });
        if (!coords) return null;
        const key = coords.join(",");
        const repeat = seen.get(key) || 0;
        seen.set(key, repeat + 1);
        return { ...site, coords: [coords[0] + repeat * 0.012, coords[1] + repeat * 0.012] };
      })
      .filter(Boolean);
  }, [board, sites]);
  const ordered = [...board].sort((a, b) => ORDER[a.estado] - ORDER[b.estado] || a.nombre.localeCompare(b.nombre));

  function toggleSound() {
    const next = !sound;
    onSound(next);
    // El permiso de notificaciones sólo se puede pedir tras un clic del usuario.
    if (next) requestNotifications();
  }

  return (
    <div className="noc">
      <div className="page-head">
        <div>
          <h1 className="page-title">Red UAEH</h1>
          <p className="page-subtitle">
            {board.length} planteles · {summary ? `actualizado ${timeAgo(summary.ultima_lectura)}` : "cargando…"}
          </p>
        </div>
        <div className="page-actions">
          <div className="segmented" role="group" aria-label="Frecuencia de actualización">
            {NOC_REFRESH.map((seconds) => (
              <button key={seconds} type="button" aria-pressed={refreshSeconds === seconds} className={refreshSeconds === seconds ? "active" : ""} onClick={() => setRefreshInterval(seconds)}>
                {seconds} s
              </button>
            ))}
          </div>
          <button type="button" className={`icon-button${sound ? "" : " muted"}`} aria-pressed={sound} onClick={toggleSound} title={sound ? "Silenciar alarma" : "Activar alarma sonora"}>
            {sound ? "🔔 Alarma activa" : "🔕 Silenciada"}
          </button>
        </div>
      </div>

      {error && <p role="alert">{error}</p>}
      {summary?.worker_atrasado && (
        <p role="alert" className="worker-alert">El worker SNMP no ha escrito lecturas {timeAgo(summary.ultima_lectura)}. Los estados pueden estar desactualizados.</p>
      )}
      {incidents.length > 0 && (
        <div className="noc-incidents" role="alert" aria-live="assertive">
          {incidents.map((item) => (
            <div key={item.id} className="noc-incident">
              <span className="dot dot-critical" aria-hidden="true" />
              <span><strong>{item.nombre}</strong> pasó a crítico <small>{timeAgo(item.at)}</small></span>
              <button type="button" className="text-button" onClick={() => onOpenSite(item.id)}>Ver plantel</button>
              <button type="button" className="text-button" aria-label={`Descartar aviso de ${item.nombre}`} onClick={() => setIncidents((current) => current.filter((entry) => entry.id !== item.id))}>✕</button>
            </div>
          ))}
        </div>
      )}

      <div className="noc-kpis">
        <Kpi label="Disponibilidad" value={availability === null ? "—" : `${availability}%`} detail="switches que responden a SNMP" tone={availability !== null && availability < 95 ? (availability < 80 ? "critical" : "warning") : ""} />
        <Kpi label="Switches en línea" value={`${online}/${devices.length}`} detail={devices.length - online ? `${devices.length - online} sin respuesta` : "todos responden"} />
        <Kpi label="Alertas abiertas" value={openAlerts} detail={pending ? `${pending} sin reconocer` : "todas atendidas"} tone={pending ? "critical" : ""} />
        <article className="noc-kpi">
          <span>Planteles</span>
          <div className="noc-levels">
            <span className="level-count"><i className="dot dot-critical" />{count("critical")}</span>
            <span className="level-count"><i className="dot dot-warning" />{count("warning")}</span>
            <span className="level-count"><i className="dot dot-ok" />{count("ok")}</span>
          </div>
          <small>crítico · atención · sano</small>
        </article>
      </div>

      <div className="noc-body">
        <section className="panel noc-map-panel">
          <Suspense fallback={<div className="noc-map skeleton" aria-hidden="true" />}>
            <NocMap points={points} theme={theme} onSelect={onOpenSite} />
          </Suspense>
          <div className="noc-legend">
            {["critical", "warning", "ok", "none"].map((level) => (
              <span key={level}><i className={`dot dot-${level}`} />{LEVEL_TEXT[level]}</span>
            ))}
          </div>
        </section>
        <section className="panel noc-sites" aria-label="Planteles por estado">
          <h2 className="panel-title">{critical.length ? `${critical.length} en rojo` : "Planteles"}</h2>
          {!summary ? (
            <p className="muted">Cargando…</p>
          ) : (
            <ul className="noc-site-list">
              {ordered.map((site) => (
                <li key={site.id}>
                  <button type="button" className={`noc-site site-${site.estado}`} onClick={() => onOpenSite(site.id)} aria-label={`${site.nombre}: ${LEVEL_TEXT[site.estado]}`}>
                    <i className={`dot dot-${site.estado}`} aria-hidden="true" />
                    <span className="noc-site-name">{site.nombre}</span>
                    <span className="noc-site-meta">
                      {site.alertas_abiertas > 0 ? `${site.alertas_abiertas} alerta${site.alertas_abiertas === 1 ? "" : "s"}` : site.equipos ? `${site.disponibilidad}%` : "—"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
