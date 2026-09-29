import { useEffect, useRef, useState } from "react";

const KEY = "sonar-refresh";
const EVENT = "sonar-refresh-change";
const ACTIVITY = "sonar-refresh-activity";

/** Intervalos disponibles en segundos; 0 desactiva el refresco automático. */
export const REFRESH_OPTIONS = [3, 5, 30, 0];
export const DEFAULT_REFRESH = 3;

function storedInterval() {
  try {
    const saved = Number(localStorage.getItem(KEY));
    if (localStorage.getItem(KEY) !== null && REFRESH_OPTIONS.includes(saved)) return saved;
  } catch {
    // Sin localStorage (modo privado): se usa el valor por defecto.
  }
  return DEFAULT_REFRESH;
}

let interval = storedInterval();

export function currentRefreshInterval() {
  return interval;
}

export function setRefreshInterval(seconds) {
  interval = REFRESH_OPTIONS.includes(seconds) ? seconds : DEFAULT_REFRESH;
  try {
    localStorage.setItem(KEY, String(interval));
  } catch {
    // Se aplica aunque no se pueda recordar.
  }
  window.dispatchEvent(new Event(EVENT));
}

/** Relee la preferencia guardada (útil en pruebas). */
export function resetRefreshInterval() {
  interval = storedInterval();
  window.dispatchEvent(new Event(EVENT));
}

export function useRefreshInterval() {
  const [value, setValue] = useState(currentRefreshInterval);
  useEffect(() => {
    const update = () => setValue(currentRefreshInterval());
    window.addEventListener(EVENT, update);
    return () => window.removeEventListener(EVENT, update);
  }, []);
  return value;
}

// Número de refrescos automáticos en curso: el indicador del encabezado pulsa mientras sea > 0.
let active = 0;
function track(delta) {
  active = Math.max(0, active + delta);
  window.dispatchEvent(new Event(ACTIVITY));
}

export function useRefreshActivity() {
  const [busy, setBusy] = useState(active > 0);
  useEffect(() => {
    const update = () => setBusy(active > 0);
    window.addEventListener(ACTIVITY, update);
    return () => window.removeEventListener(ACTIVITY, update);
  }, []);
  return busy;
}

/**
 * Ejecuta `load` al ritmo elegido en el encabezado. No encima peticiones (si la
 * anterior sigue en curso se salta el ciclo), se pausa con la pestaña oculta y
 * refresca en cuanto vuelve a ser visible.
 */
export function useAutoRefresh(load, enabled = true) {
  const seconds = useRefreshInterval();
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    if (!enabled || !seconds) return undefined;
    let running = false;
    const tick = async () => {
      if (running || document.visibilityState === "hidden") return;
      running = true;
      track(1);
      try {
        await loadRef.current();
      } catch {
        // Cada vista muestra sus propios errores; el ciclo sigue.
      } finally {
        running = false;
        // El pulso dura al menos lo que su animación, aunque la respuesta llegue en milisegundos.
        setTimeout(() => track(-1), 800);
      }
    };
    const timer = setInterval(tick, seconds * 1000);
    const onVisibility = () => {
      if (document.visibilityState === "visible") tick();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [seconds, enabled]);
  return seconds;
}
