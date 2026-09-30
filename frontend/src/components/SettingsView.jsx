import { REFRESH_OPTIONS, setRefreshInterval, useRefreshInterval } from "../utils/refresh";
import { setTheme, useTheme } from "../utils/theme";
import Inventory from "./Inventory";
import Segmented from "./Segmented";

const refreshLabel = (seconds) => (seconds ? `${seconds} s` : "Pausa");

/** Configuración: preferencias de este navegador e inventario de switches. */
export default function SettingsView({ user, plantel, sound, onSound, collapsed, onCollapsed }) {
  const theme = useTheme();
  const seconds = useRefreshInterval();
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Configuración</h1>
          <p className="page-subtitle">Preferencias de este navegador e inventario de equipos.</p>
        </div>
        {user.is_staff && (
          <a className="button" href="/admin/" target="_blank" rel="noreferrer">Administración Django ↗</a>
        )}
      </div>
      <section className="panel prefs">
        <h2 className="panel-title">Preferencias</h2>
        <div className="pref-row">
          <span><strong>Apariencia</strong><small>Claro u oscuro</small></span>
          <Segmented label="Apariencia" value={theme} onChange={setTheme} options={[["light", "Claro"], ["dark", "Oscuro"]]} />
        </div>
        <div className="pref-row">
          <span><strong>Actualización automática</strong><small>Cada cuánto se consultan los datos</small></span>
          <Segmented label="Actualización automática" value={seconds} onChange={setRefreshInterval} options={REFRESH_OPTIONS.map((option) => [option, refreshLabel(option)])} />
        </div>
        <div className="pref-row">
          <span><strong>Alarma sonora</strong><small>Suena cuando un plantel pasa a rojo</small></span>
          <Segmented label="Alarma sonora" value={sound} onChange={onSound} options={[[true, "Activa"], [false, "Silenciada"]]} />
        </div>
        <div className="pref-row">
          <span><strong>Menú lateral</strong><small>Expandido o sólo íconos</small></span>
          <Segmented label="Menú lateral" value={collapsed} onChange={onCollapsed} options={[[false, "Expandido"], [true, "Compacto"]]} />
        </div>
      </section>
      <Inventory key={plantel} plantel={plantel} user={user} />
    </>
  );
}
