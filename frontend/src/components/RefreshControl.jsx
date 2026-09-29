import {
  REFRESH_OPTIONS,
  setRefreshInterval,
  useRefreshActivity,
  useRefreshInterval,
} from "../utils/refresh";

const label = (seconds) => (seconds ? `Cada ${seconds} s` : "Desactivado");

/** Selector del refresco automático con indicador de estado. */
export default function RefreshControl() {
  const seconds = useRefreshInterval();
  const busy = useRefreshActivity();
  const state = !seconds ? "paused" : busy ? "busy" : "live";
  return (
    <label className={`refresh-control refresh-${state}`} title="Refresco automático de datos">
      <span className="refresh-dot" aria-hidden="true" />
      <span className="refresh-state" aria-live="polite">
        {seconds ? "En vivo" : "Pausado"}
      </span>
      <select
        aria-label="Refresco automático"
        value={seconds}
        onChange={(event) => setRefreshInterval(Number(event.target.value))}
      >
        {REFRESH_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {label(option)}
          </option>
        ))}
      </select>
    </label>
  );
}
