import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "./api/client";
import Login from "./components/Login";
import { setTheme, useTheme } from "./utils/theme";

// Cada pestaña se descarga al abrirla: chart.js y la tabla de inventario
// no bloquean la carga inicial.
const Inventory = lazy(() => import("./components/Inventory"));
const Monitoring = lazy(() => import("./components/Monitoring"));
const Overview = lazy(() => import("./components/Overview"));
export default function App() {
  const [user, setUser] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [tab, setTab] = useState("monitoring"),
    [focusDevice, setFocusDevice] = useState(null);
  const theme = useTheme();
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
      setTab("monitoring");
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
        <div className="header-tools">
          <button
            className="theme-toggle"
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            aria-label={theme === "light" ? "Cambiar a modo oscuro" : "Cambiar a modo claro"}
            title={theme === "light" ? "Cambiar a modo oscuro" : "Cambiar a modo claro"}
          >
            {theme === "light" ? "☾ Modo oscuro" : "☀ Modo claro"}
          </button>
          {user && (
            <div className="account">
              <span>
                {user.username} · {user.rol}
              </span>
              <button onClick={logout}>Salir</button>
            </div>
          )}
        </div>
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
              ["monitoring", "Monitoreo"],
              ["inventory", "Inventario"],
              ["overview", "Resumen"],
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
          <Suspense fallback={<p role="status">Cargando…</p>}>
          {tab === "monitoring" ? (
            <Monitoring focusDevice={focusDevice} onFocusHandled={() => setFocusDevice(null)} />
          ) : tab === "overview" ? (
            <Overview onOpenPorts={(device) => { setFocusDevice(device); setTab("monitoring"); }} />
          ) : tab === "inventory" ? (
            <Inventory user={user} />
          ) : (
            <section className="card">
              <h2>Dashboards de red</h2>
              {dashboard ? (
                <iframe
                  title="Grafana · Monitoreo de red"
                  src={dashboard}
                  className="grafana-frame"
                  allowFullScreen
                />
              ) : (
                <p>
                  Configura VITE_GRAFANA_URL en frontend/.env.local para abrir
                  tus dashboards.
                </p>
              )}
            </section>
          )}
          </Suspense>
        </>
      )}
      <footer>SONAR · Observabilidad de red</footer>
    </main>
  );
}
