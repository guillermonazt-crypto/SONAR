import { lazy, Suspense, useEffect, useState } from "react";
import { api } from "./api/client";
import GlobalSearch from "./components/GlobalSearch";
import Login from "./components/Login";
import RefreshControl from "./components/RefreshControl";
import { useAutoRefresh } from "./utils/refresh";
import { loadSite, saveSite } from "./utils/site";
import { setTheme, useTheme } from "./utils/theme";
import { clearView, loadView, saveView } from "./utils/viewState";

const TABS = ["monitoring", "inventory", "overview", "optics", "alerts", "reports"];

// Cada pestaña se descarga al abrirla: chart.js y la tabla de inventario
// no bloquean la carga inicial.
const Inventory = lazy(() => import("./components/Inventory"));
const Monitoring = lazy(() => import("./components/Monitoring"));
const Overview = lazy(() => import("./components/Overview"));
const Optics = lazy(() => import("./components/Optics"));
const Alerts = lazy(() => import("./components/Alerts"));
const Reports = lazy(() => import("./components/Reports"));
export default function App() {
  const [user, setUser] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [tab, setTab] = useState(() => (TABS.includes(loadView("tab")) ? loadView("tab") : "monitoring")),
    [focus, setFocus] = useState(null),
    [pendingAlerts, setPendingAlerts] = useState(0),
    // Plantel global: filtra todas las pestañas y se recuerda al recargar ("" = todos).
    [plantel, setPlantelState] = useState(loadSite),
    [sites, setSites] = useState([]);
  const theme = useTheme();
  function setPlantel(value) {
    const next = value ? String(value) : "";
    saveSite(next);
    setPlantelState(next);
  }
  // Alertas abiertas sin atender: se muestran junto a la pestaña Alertas.
  async function loadAlerts() {
    try {
      const summary = await api.alertSummary(plantel);
      setPendingAlerts(summary?.sin_reconocer || 0);
    } catch {
      // El contador es informativo; la pestaña muestra el error si lo hay.
    }
  }
  useEffect(() => {
    if (user) loadAlerts();
  }, [user, plantel]);
  useEffect(() => {
    if (!user) return;
    api.list("planteles")
      .then((items) => {
        setSites(items);
        // Un plantel guardado que ya no existe no debe dejar todo vacío.
        if (plantel && !items.some((item) => String(item.id) === plantel)) setPlantel("");
      })
      .catch(() => {});
  }, [user]);
  useAutoRefresh(loadAlerts, Boolean(user));

  // Abre un switch (y opcionalmente un puerto) en Monitoreo desde cualquier vista.
  function openDevice(device, portId = null) {
    setFocus({ device, portId });
    setTab("monitoring");
  }
  useEffect(() => saveView("tab", tab), [tab]);
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
      clearView();
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
          {user && <RefreshControl />}
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
              ["optics", "Ópticas"],
              ["alerts", "Alertas"],
              ["reports", "Reportes"],
            ].map(([id, label]) => (
              <button
                className={tab === id ? "active" : ""}
                key={id}
                onClick={() => setTab(id)}
              >
                {label}
                {id === "alerts" && pendingAlerts > 0 && (
                  <span className="nav-count" aria-label={`${pendingAlerts} sin atender`}>{pendingAlerts}</span>
                )}
              </button>
            ))}
            <div className="site-picker">
              <span aria-hidden="true">Plantel</span>
              <select aria-label="Filtrar todo por plantel" value={plantel} onChange={(event) => setPlantel(event.target.value)}>
                <option value="">Todos</option>
                {plantel && !sites.some((item) => String(item.id) === plantel) && <option value={plantel}>Plantel {plantel}</option>}
                {[...sites].sort((a, b) => a.nombre.localeCompare(b.nombre)).map((item) => (
                  <option key={item.id} value={String(item.id)}>{item.nombre}</option>
                ))}
              </select>
            </div>
            <GlobalSearch onOpen={openDevice} plantel={plantel} />
            {user.is_staff && (
              <a href="/admin/" target="_blank" rel="noreferrer">
                Administración Django ↗
              </a>
            )}
          </nav>
          <Suspense
            fallback={
              <section className="card" role="status" aria-label="Cargando vista">
                <div className="skeleton-table">
                  {Array.from({ length: 4 }, (_, index) => <span key={index} className="skeleton" />)}
                </div>
              </section>
            }
          >
          {tab === "monitoring" ? (
            <Monitoring key={plantel} plantel={plantel} focus={focus} onFocusHandled={() => setFocus(null)} />
          ) : tab === "overview" ? (
            <Overview key={plantel} plantel={plantel} onPlantelChange={setPlantel} onOpenPorts={(device) => openDevice(device)} />
          ) : tab === "reports" ? (
            <Reports key={plantel} plantel={plantel} onOpenPort={openDevice} />
          ) : tab === "alerts" ? (
            <Alerts key={plantel} plantel={plantel} user={user} onOpenDevice={(device) => openDevice(device)} />
          ) : tab === "optics" ? (
            <Optics key={plantel} plantel={plantel} onOpenPort={openDevice} />
          ) : tab === "inventory" ? (
            <Inventory key={plantel} plantel={plantel} user={user} />
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
