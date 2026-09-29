import { useCallback, useState } from "react";

const KEY = "sonar-view";

// Lo que el usuario estaba viendo (pestaña, switch, puerto, carpetas) sobrevive
// a una recarga de la página. sessionStorage: es por pestaña y se borra al cerrarla.
function read() {
  try {
    return JSON.parse(sessionStorage.getItem(KEY)) || {};
  } catch {
    return {};
  }
}

export function loadView(key) {
  return read()[key] ?? null;
}

export function saveView(key, value) {
  try {
    const view = read();
    if (value === null || value === undefined) delete view[key];
    else view[key] = value;
    sessionStorage.setItem(KEY, JSON.stringify(view));
  } catch {
    // Sin sessionStorage la vista simplemente no se recuerda.
  }
}

export function clearView() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nada que limpiar.
  }
}

/**
 * useState que se recuerda con el resto de la vista (filtros, selecciones).
 * Los valores guardados se combinan con `initial`, así un filtro nuevo no rompe
 * lo que quedó de una versión anterior.
 */
export function useViewState(key, initial) {
  const [value, setValue] = useState(() => {
    const saved = loadView(key);
    if (saved === null) return initial;
    const isObject = (item) => item && typeof item === "object" && !Array.isArray(item);
    return isObject(initial) && isObject(saved) ? { ...initial, ...saved } : saved;
  });
  const update = useCallback(
    (next) =>
      setValue((current) => {
        const resolved = typeof next === "function" ? next(current) : next;
        saveView(key, resolved);
        return resolved;
      }),
    [key],
  );
  return [value, update];
}
