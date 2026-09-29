import { useEffect, useState } from "react";
import { api } from "../api/client";
import { timeAgo } from "../utils/format";
import { useAutoRefresh } from "../utils/refresh";
import SonarDataTable from "./DataTable";

const blankWindow = { tipo: "switch", objetivo: "", inicio: "", fin: "", motivo: "" };
const when = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

function duration(alert) {
  const end = alert.fin ? new Date(alert.fin) : new Date();
  const minutes = Math.max(0, Math.round((end - new Date(alert.inicio)) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `${hours} h ${minutes % 60} min` : `${Math.round(hours / 24)} días`;
}

function Reasons({ items }) {
  return (
    <ul className="device-reasons">
      {items.map((reason, index) => (
        <li key={index} className={`reason-${reason.level}`}>{reason.text}</li>
      ))}
    </ul>
  );
}

/** Centro de alertas: episodios en riesgo, reconocimiento y ventanas de mantenimiento. */
export default function Alerts({ user, onOpenDevice = () => {} }) {
  const [open, setOpen] = useState(null);
  const [history, setHistory] = useState([]);
  const [windows, setWindows] = useState([]);
  const [switches, setSwitches] = useState([]);
  const [sites, setSites] = useState([]);
  const [notes, setNotes] = useState({});
  const [form, setForm] = useState(blankWindow);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const [active, all, current] = await Promise.all([api.alerts(true), api.alerts(), api.maintenances()]);
      setOpen(active);
      setHistory(all);
      setWindows(current);
      setError("");
    } catch (exception) {
      setError(exception.message);
    }
  }
  useEffect(() => {
    refresh();
    if (user.can_edit) {
      Promise.all([api.list("switches"), api.list("planteles")])
        .then(([devices, places]) => {
          setSwitches(devices);
          setSites(places);
        })
        .catch(() => {});
    }
  }, []);
  useAutoRefresh(refresh, !busy);

  async function acknowledge(alert) {
    setBusy(true);
    try {
      await api.acknowledge(alert.id, notes[alert.id] || "");
      setNotes((current) => ({ ...current, [alert.id]: "" }));
      await refresh();
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveWindow(event) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.saveMaintenance({
        switch: form.tipo === "switch" ? Number(form.objetivo) : null,
        plantel: form.tipo === "plantel" ? Number(form.objetivo) : null,
        inicio: new Date(form.inicio).toISOString(),
        fin: new Date(form.fin).toISOString(),
        motivo: form.motivo,
      });
      setForm(blankWindow);
      await refresh();
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancelWindow(window) {
    setBusy(true);
    try {
      await api.deleteMaintenance(window.id);
      await refresh();
    } catch (exception) {
      setError(exception.message);
    } finally {
      setBusy(false);
    }
  }

  const columns = [
    { name: "Switch", sortable: true, grow: 1.4, selector: (a) => a.switch.nombre,
      cell: (a) => <div><strong>{a.switch.nombre}</strong><small>{a.switch.plantel_nombre}</small></div> },
    { name: "Inicio", sortable: true, selector: (a) => a.inicio, cell: (a) => <small>{when(a.inicio)}</small> },
    { name: "Duración", sortable: true, selector: (a) => new Date(a.fin || Date.now()) - new Date(a.inicio),
      cell: (a) => (a.fin ? duration(a) : <span className="status-critical-text">Abierta · {duration(a)}</span>) },
    { name: "Motivos", grow: 2, cell: (a) => <Reasons items={a.motivos} /> },
    { name: "Atendida", grow: 1.4, cell: (a) => (a.reconocida_por
      ? <div><strong>{a.reconocida_por}</strong><small>{a.nota || "Sin nota"}</small></div>
      : a.en_mantenimiento ? <small>En mantenimiento</small> : <small>—</small>) },
  ];
  const targets = form.tipo === "switch" ? switches : sites;

  return (
    <>
      <div className="section-title page-heading">
        <div>
          <span className="eyebrow">OPERACIÓN</span>
          <h2>Centro de alertas</h2>
          <p>Episodios en riesgo, quién los atendió y ventanas de mantenimiento programadas.</p>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}

      <section className="card">
        <h2>Alertas abiertas</h2>
        {open === null ? (
          <p role="status">Cargando alertas…</p>
        ) : !open.length ? (
          <p className="empty">No hay alertas abiertas.</p>
        ) : (
          <div className="alert-list">
            {open.map((alert) => (
              <article key={alert.id} className="alert-item">
                <div>
                  <strong>{alert.switch.nombre}</strong>
                  <small>{alert.switch.hostname} · {alert.switch.plantel_nombre} · desde {timeAgo(alert.inicio)}</small>
                  <Reasons items={alert.motivos} />
                  {alert.en_mantenimiento && <span className="status-badge status-maintenance">En mantenimiento: no se notificó</span>}
                </div>
                <div className="alert-actions">
                  {alert.reconocida_por ? (
                    <small>
                      Atendida por <strong>{alert.reconocida_por}</strong> {timeAgo(alert.reconocida_en)}
                      {alert.nota && ` · ${alert.nota}`}
                    </small>
                  ) : user.can_edit ? (
                    <>
                      <input
                        aria-label={`Nota para ${alert.switch.nombre}`}
                        placeholder="Nota (opcional)"
                        value={notes[alert.id] || ""}
                        onChange={(event) => setNotes((current) => ({ ...current, [alert.id]: event.target.value }))}
                      />
                      <button type="button" className="primary" disabled={busy} onClick={() => acknowledge(alert)}>
                        Reconocer
                      </button>
                    </>
                  ) : (
                    <small>Sin atender</small>
                  )}
                  <button type="button" onClick={() => onOpenDevice(alert.switch)}>Ver puertos</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <div className={user.can_edit ? "grid" : "grid single"}>
        <section className="card">
          <h2>Mantenimientos vigentes y programados</h2>
          {!windows.length ? (
            <p className="empty">No hay ventanas de mantenimiento.</p>
          ) : (
            <ul className="maintenance-list">
              {windows.map((window) => (
                <li key={window.id}>
                  <div>
                    <strong>{window.switch_nombre || `Plantel ${window.plantel_nombre}`}</strong>
                    <small>{when(window.inicio)} → {when(window.fin)} · {window.motivo}{window.creado_por && ` · ${window.creado_por}`}</small>
                  </div>
                  {user.can_edit && (
                    <button type="button" disabled={busy} onClick={() => cancelWindow(window)}>Cancelar</button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
        {user.can_edit && (
          <section className="card">
            <h2>Programar mantenimiento</h2>
            <form onSubmit={saveWindow}>
              <label>
                Aplica a
                <select value={form.tipo} onChange={(event) => setForm({ ...form, tipo: event.target.value, objetivo: "" })}>
                  <option value="switch">Un switch</option>
                  <option value="plantel">Todo un plantel</option>
                </select>
              </label>
              <label>
                {form.tipo === "switch" ? "Switch" : "Plantel"}
                <select required value={form.objetivo} onChange={(event) => setForm({ ...form, objetivo: event.target.value })}>
                  <option value="">Selecciona…</option>
                  {targets.map((item) => <option key={item.id} value={item.id}>{item.nombre}</option>)}
                </select>
              </label>
              <label>
                Inicio
                <input type="datetime-local" required value={form.inicio} onChange={(event) => setForm({ ...form, inicio: event.target.value })} />
              </label>
              <label>
                Fin
                <input type="datetime-local" required value={form.fin} onChange={(event) => setForm({ ...form, fin: event.target.value })} />
              </label>
              <label>
                Motivo
                <input required maxLength={255} value={form.motivo} onChange={(event) => setForm({ ...form, motivo: event.target.value })} />
              </label>
              <button className="primary" disabled={busy}>Guardar ventana</button>
            </form>
          </section>
        )}
      </div>

      <section className="card">
        <h2>Historial</h2>
        <div className="table-scroll sonar-table">
          <SonarDataTable columns={columns} data={history} noDataComponent="Aún no hay alertas registradas." />
        </div>
      </section>
    </>
  );
}
