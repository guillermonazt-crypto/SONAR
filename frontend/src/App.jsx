import { lazy, Suspense, useEffect, useState } from "react";
import { api, endSession } from "./api/client";
import Breadcrumb from "./components/Breadcrumb";
import GlobalSearch from "./components/GlobalSearch";
import Login from "./components/Login";
import RefreshControl from "./components/RefreshControl";
import Sidebar, { SECTIONS } from "./components/Sidebar";
import { usePref } from "./utils/prefs";
import { useAutoRefresh, useRefreshInterval } from "./utils/refresh";
import { loadSite, saveSite } from "./utils/site";
import { setTheme, useTheme } from "./utils/theme";
import { clearView, loadView, saveView } from "./utils/viewState";

const VIEWS = SECTIONS.map(([id]) => id);
// Pestañas de la versión anterior guardadas en la sesión → sección nueva.
const LEGACY = { monitoring: "status", overview: "status", inventory: "settings", optics: "network" };

function initialView() {
  const saved = loadView("tab");
  if (VIEWS.includes(saved)) return saved;
  return LEGACY[saved] || "home";
}

// Cada sección se descarga al abrirla: Leaflet, chart.js y las tablas no bloquean la carga inicial.
const Noc = lazy(() => import("./components/Noc"));
const StatusView = lazy(() => import("./components/StatusView"));
const Alerts = lazy(() => import("./components/Alerts"));
const NetworkView = lazy(() => import("./components/NetworkView"));
const Reports = lazy(() => import("./components/Reports"));
const SettingsView = lazy(() => import("./components/SettingsView"));

export default function App() {
  const [user, setUser] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [view, setView] = useState(initialView),
    // Estado: "sites" (planteles) o "switches" (switches y puertos).
    [statusSegment, setStatusSegment] = useState(() => (loadView("status-segment") === "switches" || loadView("tab") === "monitoring" ? "switches" : "sites")),
    [focus, setFocus] = useState(null),
    [selection, setSelection] = useState({ device: null, port: null }),
    [pendingAlerts, setPendingAlerts] = useState(0),
    // Plantel global: filtra todas las secciones y se recuerda al recargar ("" = todos).
    [plantel, setPlantelState] = useState(loadSite),
    [sites, setSites] = useState([]);
  const [collapsed, setCollapsed] = usePref("sidebar-collapsed", false);
  const [sound, setSound] = usePref("sound", true);
  const theme = useTheme();
  const refreshSeconds = useRefreshInterval();

  function setPlantel(value) {
    const next = value ? String(value) : "";
    saveSite(next);
    setPlantelState(next);
    setSelection({ device: null, port: null });
  }
  // Alertas abiertas sin atender: se muestran junto a Alertas en el menú.
  async function loadAlerts() {
    try {
      const summary = await api.alertSummary(plantel);
      setPendingAlerts(summary?.sin_reconocer || 0);
    } catch {
      // El contador es informativo; la sección muestra el error si lo hay.
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

  useEffect(() => saveView("tab", view), [view]);
  useEffect(() => saveView("status-segment", statusSegment), [statusSegment]);

  function showStatus(segment) {
    setStatusSegment(segment);
    setView("status");
  }
  // Abre un switch (y opcionalmente un puerto) desde cualquier vista.
  function openDevice(device, portId = null) {
    setFocus({ device, portId });
    showStatus("switches");
  }
  // Del mapa o de una tarjeta: el plantel queda como filtro global y se abre su estado.
  function openSite(id) {
    setPlantel(id);
    showStatus("sites");
  }
  async function connect() {
    setLoading(true);
    setError("");
    try {
      setUser((await api.session()).user);
    } catch (e) {
      setError("No se pudo conectar con Django. Comprueba que el backend esté iniciado.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    connect();
  }, []);
  async function logout() {
    // Primero se cancela lo pendiente y se vacía la pantalla: nada de la sesión
    // anterior queda visible mientras el servidor responde. El tema y las
    // preferencias del menú se conservan; el plantel y la vista no.
    endSession();
    setUser(null);
    setSites([]);
    setPendingAlerts(0);
    setFocus(null);
    setSelection({ device: null, port: null });
    saveSite("");
    setPlantelState("");
    clearView();
    setView("home");
    setStatusSegment("sites");
    try {
      await api.logout();
    } catch (e) {
      setError(e.message);
    }
  }

  const siteName = plantel ? sites.find((item) => String(item.id) === plantel)?.nombre || `Plantel ${plantel}` : null;
  const crumbs = [{ label: "Red UAEH", onClick: () => setPlantel("") }];
  if (siteName) crumbs.push({ label: siteName, onClick: () => { setSelection({ device: null, port: null }); showStatus("sites"); } });
  if (view === "status" && statusSegment === "switches" && selection.device) {
    crumbs.push({ label: selection.device.nombre });
    if (selection.port) crumbs.push({ label: selection.port.nombre });
  }
  const themeLabel = theme === "light" ? "Cambiar a modo oscuro" : "Cambiar a modo claro";

  if (loading || error || !user) {
    return (
      <main className="auth-shell">
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true">⬡</span>
          <h1>SONAR</h1>
          <p>Sistema de Observabilidad de Nodos y Análisis de Red</p>
        </div>
        {loading ? (
          <p role="status">Conectando…</p>
        ) : error ? (
          <section className="panel">
            <p role="alert">{error}</p>
            <button onClick={connect}>Reintentar</button>
          </section>
        ) : (
          <Login onLogin={setUser} />
        )}
      </main>
    );
  }

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <Sidebar
        current={view}
        onSelect={setView}
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
        pendingAlerts={pendingAlerts}
        user={user}
        onLogout={logout}
      />
      <main className="content">
        <header className="topbar">
          {view === "home" ? <span className="topbar-title">Centro de operaciones</span> : <Breadcrumb items={crumbs} />}
          <div className="topbar-tools">
            {view !== "home" && (
              <label className="site-picker">
                <select aria-label="Filtrar todo por plantel" value={plantel} onChange={(event) => setPlantel(event.target.value)}>
                  <option value="">Todos los planteles</option>
                  {plantel && !sites.some((item) => String(item.id) === plantel) && <option value={plantel}>Plantel {plantel}</option>}
                  {[...sites].sort((a, b) => a.nombre.localeCompare(b.nombre)).map((item) => (
                    <option key={item.id} value={String(item.id)}>{item.nombre}</option>
                  ))}
                </select>
              </label>
            )}
            <GlobalSearch onOpen={openDevice} plantel={plantel} />
            {view !== "home" && <RefreshControl />}
            <button type="button" className="icon-button theme-toggle" onClick={() => setTheme(theme === "light" ? "dark" : "light")} aria-label={themeLabel} title={themeLabel}>
              {theme === "light" ? "☾" : "☀"}
            </button>
          </div>
        </header>
        <div className="view" key={view}>
          <Suspense
            fallback={
              <section className="panel" role="status" aria-label="Cargando vista">
                <div className="skeleton-table">
                  {Array.from({ length: 4 }, (_, index) => <span key={index} className="skeleton" />)}
                </div>
              </section>
            }
          >
            {view === "home" ? (
              <Noc sites={sites} onOpenSite={openSite} refreshSeconds={refreshSeconds} sound={sound} onSound={setSound} />
            ) : view === "status" ? (
              <StatusView
                plantel={plantel}
                siteName={siteName}
                segment={statusSegment}
                onSegment={(segment) => { setStatusSegment(segment); setSelection({ device: null, port: null }); }}
                onPlantelChange={setPlantel}
                onOpenPorts={(device) => openDevice(device)}
                focus={focus}
                onFocusHandled={() => setFocus(null)}
                onSelect={(device) => setSelection((current) => ({ device, port: device && current.device?.id === device.id ? current.port : null }))}
                onPortChange={(port) => setSelection((current) => ({ ...current, port }))}
              />
            ) : view === "alerts" ? (
              <Alerts key={plantel} plantel={plantel} user={user} onOpenDevice={(device) => openDevice(device)} />
            ) : view === "network" ? (
              <NetworkView plantel={plantel} siteName={siteName} sites={sites} onPlantelChange={setPlantel} onOpenPort={openDevice} />
            ) : view === "reports" ? (
              <Reports key={plantel} plantel={plantel} onOpenPort={openDevice} />
            ) : (
              <SettingsView user={user} plantel={plantel} sound={sound} onSound={setSound} collapsed={collapsed} onCollapsed={setCollapsed} />
            )}
          </Suspense>
        </div>
      </main>
    </div>
  );
}
