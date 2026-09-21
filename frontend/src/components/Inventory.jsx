import { useEffect, useState } from "react";
import { api } from "../api/client";
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
    [ports, setPorts] = useState(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState("");
  async function refresh() {
    setError("");
    try {
      const [d, s] = await Promise.all([
        api.list("switches"),
        api.list("planteles"),
      ]);
      setDevices(d);
      setSites(s);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);
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
  async function showPorts(d) {
    setPorts({ device: d, items: [], loading: true });
    try {
      const items = await api.ports(d.id);
      setPorts({ device: d, items, loading: false });
    } catch (e) {
      setPorts(null);
      setError(e.message);
    }
  }
  const filtered = devices.filter((d) =>
    `${d.nombre} ${d.hostname} ${d.plantel_nombre}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
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
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Dispositivo</th>
                    <th>Rol / Plantel</th>
                    <th>CPU 5m</th>
                    <th>Última consulta</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <strong>{d.nombre}</strong>
                        <small>
                          {d.hostname} · {d.activo ? "Activo" : "Inactivo"}
                        </small>
                      </td>
                      <td>
                        <span className={`badge ${d.rol}`}>{d.rol}</span>
                        <small>{d.plantel_nombre}</small>
                      </td>
                      <td>
                        {d.cpu_5m === null ? "Sin lectura" : `${d.cpu_5m}%`}
                      </td>
                      <td>
                        {d.ultima_consulta ? (
                          <>
                            <small>
                              {new Date(d.ultima_consulta).toLocaleString()}
                            </small>
                            {d.lectura_correcta ? "Recibida" : "Sin respuesta"}
                          </>
                        ) : (
                          "Pendiente"
                        )}
                      </td>
                      <td>
                        <div className="actions">
                          <button onClick={() => showPorts(d)}>Puertos</button>
                          {user.can_edit && (
                            <>
                              <button
                                onClick={() => {
                                  setEditing(d.id);
                                  setForm({
                                    nombre: d.nombre,
                                    hostname: d.hostname,
                                    rol: d.rol,
                                    plantel: d.plantel,
                                    activo: d.activo,
                                  });
                                }}
                              >
                                Editar
                              </button>
                              <button disabled={busy} onClick={() => toggle(d)}>
                                {d.activo ? "Desactivar" : "Activar"}
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!filtered.length && (
                <p className="empty">No hay dispositivos para mostrar.</p>
              )}
            </div>
          )}
        </section>
        {user.can_edit && (
          <section className="card">
            <h2>{editing ? "Editar dispositivo" : "Agregar dispositivo"}</h2>
            <form onSubmit={submit}>
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
      {ports && (
        <section className="card ports">
          <div className="section-title">
            <h2>Puertos · {ports.device.nombre}</h2>
            <button onClick={() => setPorts(null)}>Cerrar</button>
          </div>
          {ports.loading ? (
            <p>Cargando…</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Interfaz</th>
                    <th>Estado operativo</th>
                    <th>Entrada</th>
                    <th>Salida</th>
                    <th>CRC</th>
                    <th>Última observación</th>
                  </tr>
                </thead>
                <tbody>
                  {ports.items.map((p) => (
                    <tr key={p.id}>
                      <td>{p.nombre}</td>
                      <td>
                        {p.estado_operativo === "unknown"
                          ? "Desconocido"
                          : p.estado_operativo}
                      </td>
                      <td>{value(p.errores_entrada)}</td>
                      <td>{value(p.errores_salida)}</td>
                      <td>{value(p.errores_crc)}</td>
                      <td>{new Date(p.actualizado).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!ports.items.length && (
                <p className="empty">Aún no hay lecturas de puertos.</p>
              )}
            </div>
          )}
        </section>
      )}
    </>
  );
}
