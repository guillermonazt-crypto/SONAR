import { useEffect, useState } from "react";
import { api } from "../api/client";
import AuditLog from "./AuditLog";
import Backups from "./Backups";
import Discovered from "./Discovered";
import Sites from "./Sites";
import SonarDataTable from "./DataTable";
import { useAutoRefresh } from "../utils/refresh";
const blank = {
  nombre: "",
  hostname: "",
  rol: "access",
  plantel: "",
  activo: true,
};
const value = (v) => (v === null || v === undefined ? "Sin lectura" : v);
export default function Inventory({ user }) {
  const [devices, setDevices] = useState([]),
    [sites, setSites] = useState([]),
    [form, setForm] = useState(blank),
    [editing, setEditing] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState(""),
    [backupsFor, setBackupsFor] = useState(null);
  async function refresh() {
    try {
      const [d, s] = await Promise.all([
        api.list("switches"),
        api.list("planteles"),
      ]);
      setDevices(d);
      setSites(s);
      setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);
  // Mientras se guarda no se refresca para no pisar la respuesta de la edición.
  useAutoRefresh(refresh, !busy);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.save(
        "switches",
        { ...form, plantel: Number(form.plantel) },
        editing,
      );
      setForm(blank);
      setEditing(null);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function toggle(d) {
    setBusy(true);
    try {
      await api.save("switches", { activo: !d.activo }, d.id);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const filtered = devices.filter((d) =>
    `${d.nombre} ${d.hostname} ${d.plantel_nombre}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const columns = [
    {
      name: "Dispositivo",
      sortable: true,
      grow: 1.5,
      selector: (d) => d.nombre,
      cell: (d) => <div><strong>{d.nombre}</strong><small>{d.hostname} · {d.modelo || "Modelo pendiente"} · {d.activo ? "Activo" : "Inactivo"}</small></div>,
    },
    {
      name: "Rol / Plantel",
      sortable: true,
      selector: (d) => `${d.rol} ${d.plantel_nombre || ""}`,
      cell: (d) => <div><span className={`badge ${d.rol}`}>{d.rol}</span><small>{d.plantel_nombre}</small></div>,
    },
    { name: "CPU 5m", sortable: true, selector: (d) => d.cpu_5m ?? -1, cell: (d) => d.cpu_5m === null ? "Sin lectura" : `${d.cpu_5m}%` },
    {
      name: "Última consulta",
      sortable: true,
      selector: (d) => d.ultima_consulta || "",
      cell: (d) => d.ultima_consulta ? <div><small>{new Date(d.ultima_consulta).toLocaleString()}</small>{d.lectura_correcta ? "Recibida" : "Sin respuesta"}</div> : "Pendiente",
    },
    {
      name: "Acciones",
      button: true,
      omit: !user.can_edit,
      cell: (d) => <div className="actions">
        <button onClick={() => { setEditing(d.id); setForm({ nombre: d.nombre, hostname: d.hostname, rol: d.rol, plantel: d.plantel, activo: d.activo }); }}>Editar</button>
        <button disabled={busy} onClick={() => toggle(d)}>{d.activo ? "Desactivar" : "Activar"}</button>
        <button onClick={() => setBackupsFor(d)}>Respaldos</button>
      </div>,
    },
  ];
  return (
    <>
      <div className="stats">
        <article>
          <span>INVENTARIO</span>
          <strong>{devices.length}</strong>
          <small>switches registrados</small>
        </article>
        <article>
          <span>MONITOREO</span>
          <strong>{devices.filter((d) => d.activo).length}</strong>
          <small>habilitados para consulta</small>
        </article>
        <article>
          <span>COBERTURA</span>
          <strong>{sites.length}</strong>
          <small>planteles</small>
        </article>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {user.can_edit && (
        <Discovered
          refreshKey={devices.length}
          onAdd={(item) => {
            // Prellena el formulario; el editor elige plantel y rol antes de guardar.
            setEditing(null);
            setForm({ ...blank, nombre: (item.nombre || "").split(".")[0].slice(0, 100), hostname: item.ip });
            document.getElementById("inventory-form")?.scrollIntoView({ behavior: "smooth" });
          }}
        />
      )}
      <div className={user.can_edit ? "grid" : "grid single"}>
        <section className="card">
          <div className="section-title">
            <h2>Dispositivos monitoreados</h2>
            <button onClick={refresh}>Actualizar</button>
          </div>
          <input
            aria-label="Buscar switches"
            placeholder="Buscar por nombre, IP o plantel"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {loading ? (
            <p role="status">Cargando inventario…</p>
          ) : (
            <div className="table-scroll sonar-table">
              <SonarDataTable columns={columns} data={filtered} noDataComponent="No hay dispositivos para mostrar." />
            </div>
          )}
        </section>
        {user.can_edit && (
          <section className="card">
            <h2>{editing ? "Editar dispositivo" : "Agregar dispositivo"}</h2>
            <form id="inventory-form" onSubmit={submit}>
              <label>
                Nombre del switch
                <input
                  required
                  maxLength={100}
                  value={form.nombre}
                  onChange={(e) => setForm({ ...form, nombre: e.target.value })}
                />
              </label>
              <label>
                Dirección IP
                <input
                  required
                  value={form.hostname}
                  onChange={(e) =>
                    setForm({ ...form, hostname: e.target.value })
                  }
                />
              </label>
              <label>
                Rol
                <select
                  value={form.rol}
                  onChange={(e) => setForm({ ...form, rol: e.target.value })}
                >
                  <option value="core">Core</option>
                  <option value="distribution">Distribución</option>
                  <option value="access">Acceso</option>
                </select>
              </label>
              <label>
                Plantel
                <select
                  required
                  value={form.plantel}
                  onChange={(e) =>
                    setForm({ ...form, plantel: e.target.value })
                  }
                >
                  <option value="">Selecciona un plantel</option>
                  {sites.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.nombre}
                      {s.activo ? "" : " (inactivo)"}
                    </option>
                  ))}
                </select>
              </label>
              <button className="primary" disabled={busy || !sites.length}>
                {busy ? "Guardando…" : "Guardar switch"}
              </button>
              {editing && (
                <button
                  type="button"
                  onClick={() => {
                    setEditing(null);
                    setForm(blank);
                  }}
                >
                  Cancelar edición
                </button>
              )}
              {!sites.length && (
                <p>
                  Primero registra una división y un plantel en la pestaña
                  Planteles.
                </p>
              )}
            </form>
          </section>
        )}
      </div>
      <details className="inventory-secondary">
        <summary>Administrar planteles y divisiones</summary>
        <Sites user={user} />
      </details>
      {user.can_edit && <AuditLog />}
      {backupsFor && <Backups device={backupsFor} onClose={() => setBackupsFor(null)} />}
    </>
  );
}
