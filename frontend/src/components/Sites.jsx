import { useEffect, useState } from "react";
import { api } from "../api/client";
export default function Sites({ user }) {
  const [sites, setSites] = useState([]),
    [divisions, setDivisions] = useState([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function refresh() {
    try {
      const [s, d] = await Promise.all([
        api.list("planteles"),
        api.list("divisiones"),
      ]);
      setSites(s);
      setDivisions(d);
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => {
    refresh();
  }, []);
  async function save(e, resource) {
    e.preventDefault();
    const form = e.currentTarget;
    setBusy(true);
    setError("");
    try {
      await api.save(resource, Object.fromEntries(new FormData(form)));
      form.reset();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function toggle(s) {
    setBusy(true);
    try {
      await api.save("planteles", { activo: !s.activo }, s.id);
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      {error && <p role="alert">{error}</p>}
      <div className="grid">
        <section className="card">
          <h2>Planteles</h2>
          {sites.map((s) => (
            <article className="site" key={s.id}>
              <div>
                <strong>{s.nombre}</strong>
                <small>
                  {s.division_nombre} · {s.activo ? "Activo" : "Inactivo"}
                </small>
              </div>
              {user.can_edit && (
                <button disabled={busy} onClick={() => toggle(s)}>
                  {s.activo ? "Desactivar" : "Activar"}
                </button>
              )}
            </article>
          ))}
          {!sites.length && <p>No hay planteles registrados.</p>}
        </section>
        {user.can_edit && (
          <section className="card">
            <h2>Agregar plantel</h2>
            <form onSubmit={(e) => save(e, "planteles")}>
              <label>
                Nombre
                <input name="nombre" required maxLength={200} />
              </label>
              <label>
                División
                <select name="division" required>
                  <option value="">Selecciona</option>
                  {divisions.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.nombre}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Ubicación
                <input name="ubicacion" maxLength={200} />
              </label>
              <button className="primary" disabled={busy}>
                Guardar plantel
              </button>
            </form>
            <h2 className="spaced">Agregar división</h2>
            <form onSubmit={(e) => save(e, "divisiones")}>
              <label>
                Nombre de división
                <input name="nombre" required maxLength={100} />
              </label>
              <button disabled={busy}>Guardar división</button>
            </form>
          </section>
        )}
      </div>
    </>
  );
}
