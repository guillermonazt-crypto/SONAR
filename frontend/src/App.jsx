import { useEffect, useState } from "react";
import { api } from "./api/client";
import Login from "./components/Login";
import Inventory from "./components/Inventory";
import Sites from "./components/Sites";
export default function App() {
  const [user, setUser] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [tab, setTab] = useState("inventory");
  async function connect() {
    setLoading(true);
    setError("");
    try {
      setUser((await api.session()).user);
    } catch (e) {
      setError(
        "No se pudo conectar con Django. Comprueba que el backend esté iniciado.",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    connect();
  }, []);
  async function logout() {
    try {
      await api.logout();
      setUser(null);
      setTab("inventory");
    } catch (e) {
      setError(e.message);
    }
  }
  const dashboard = import.meta.env.VITE_GRAFANA_URL;
  return (
    <main>
      <header>
        <div>
          <h1>⬡ S.O.N.A.R.</h1>
          <p>Sistema de Observabilidad de Nodos y Análisis de Red</p>
        </div>
        {user && (
          <div className="account">
            <span>
              {user.username} · {user.rol}
            </span>
            <button onClick={logout}>Salir</button>
          </div>
        )}
      </header>
      {loading ? (
        <p role="status">Conectando…</p>
      ) : error ? (
        <section className="card">
          <p role="alert">{error}</p>
          <button onClick={connect}>Reintentar</button>
        </section>
      ) : !user ? (
        <Login onLogin={setUser} />
      ) : (
        <>
          <nav>
            {[
              ["inventory", "Inventario"],
              ["sites", "Planteles"],
              ["dashboards", "Dashboards"],
            ].map(([id, label]) => (
              <button
                className={tab === id ? "active" : ""}
                key={id}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
            {user.is_staff && (
              <a href="/admin/" target="_blank" rel="noreferrer">
                Administración Django ↗
              </a>
            )}
          </nav>
          {tab === "inventory" ? (
            <Inventory user={user} />
          ) : tab === "sites" ? (
            <Sites user={user} />
          ) : (
            <section className="card">
              <h2>Dashboards de red</h2>
              {dashboard ? (
                <a
                  className="primary link"
                  href={dashboard}
                  target="_blank"
                  rel="noreferrer"
                >
                  Abrir Grafana ↗
                </a>
              ) : (
                <p>
                  Configura VITE_GRAFANA_URL en frontend/.env.local para abrir
                  tus dashboards.
                </p>
              )}
            </section>
          )}
        </>
      )}
      <footer>SONAR · Observabilidad de red</footer>
    </main>
  );
}
