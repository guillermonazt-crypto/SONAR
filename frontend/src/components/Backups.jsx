import { useEffect, useState } from "react";
import { api } from "../api/client";

/** Historial de configuraciones de un switch, con diferencias entre versiones. */
export default function Backups({ device, onClose }) {
  const [versions, setVersions] = useState(null);
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState("diferencias");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(runNow = false) {
    setBusy(runNow);
    try {
      const list = await (runNow ? api.runBackup(device.id) : api.backups(device.id));
      setVersions(list);
      setError("");
      const latest = list.find((version) => version.exito);
      if (latest) setSelected(await api.backupDetail(latest.id));
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load();
    const closeOnEscape = (event) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [device.id]);

  async function open(version) {
    try {
      setSelected(await api.backupDetail(version.id));
    } catch (exception) {
      setError(exception.message);
    }
  }

  const text = selected ? (view === "diferencias" ? selected.diferencias || "Sin cambios respecto a la versión anterior." : selected.contenido) : "";
  return (
    <div className="port-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="card port-modal backups-modal" role="dialog" aria-modal="true" aria-labelledby="backups-title">
        <div className="section-title">
          <div>
            <span className="eyebrow">CONFIGURACIÓN</span>
            <h2 id="backups-title">Respaldos · {device.nombre}</h2>
            <small>Sólo se guarda una versión nueva cuando la configuración cambia.</small>
          </div>
          <div className="report-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => load(true)}>
              {busy ? "Respaldando…" : "Respaldar ahora"}
            </button>
            <button type="button" onClick={onClose}>Cerrar</button>
          </div>
        </div>
        {error && <p role="alert">{error}</p>}
        {versions === null ? (
          <p role="status">Cargando respaldos…</p>
        ) : !versions.length ? (
          <p className="empty">Aún no hay respaldos. Configura BACKUP_SSH_USER en .env y pulsa “Respaldar ahora”.</p>
        ) : (
          <div className="backups-layout">
            <ul className="backup-versions">
              {versions.map((version) => (
                <li key={version.id}>
                  {version.exito ? (
                    <button type="button" className={selected?.id === version.id ? "active" : ""} onClick={() => open(version)}>
                      <strong>{new Date(version.momento).toLocaleString()}</strong>
                      <small>+{version.lineas_agregadas} / −{version.lineas_eliminadas} líneas{version.verificado && ` · verificado ${new Date(version.verificado).toLocaleDateString()}`}</small>
                    </button>
                  ) : (
                    <div className="backup-failed">
                      <strong>{new Date(version.momento).toLocaleString()}</strong>
                      <small className="status-critical-text">Falló: {version.error}</small>
                    </div>
                  )}
                </li>
              ))}
            </ul>
            <div>
              {selected && (
                <>
                  <div className="filter-row">
                    {[["diferencias", "Diferencias"], ["contenido", "Configuración completa"]].map(([id, label]) => (
                      <button key={id} type="button" className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>
                    ))}
                  </div>
                  {selected.secretos_ocultos && <small className="detail-note">Contraseñas y comunidades ocultas: sólo un administrador las ve.</small>}
                  <pre className="config-view" aria-label={view === "diferencias" ? "Diferencias" : "Configuración"}>
                    {text.split("\n").map((line, index) => (
                      <span key={index} className={view === "diferencias" ? (line.startsWith("+") ? "diff-add" : line.startsWith("-") ? "diff-del" : "") : ""}>
                        {line + "\n"}
                      </span>
                    ))}
                  </pre>
                </>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
