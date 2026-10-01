import { useCallback, useState } from "react";

// Preferencias del usuario que sobreviven entre sesiones (menú, sonido).
// localStorage: son del navegador del NOC, no de una pestaña.
export function loadPref(key, initial) {
  try {
    const saved = localStorage.getItem(`sonar-${key}`);
    return saved === null ? initial : JSON.parse(saved);
  } catch {
    return initial;
  }
}

export function savePref(key, value) {
  try {
    localStorage.setItem(`sonar-${key}`, JSON.stringify(value));
  } catch {
    // Sin localStorage la preferencia aplica, sólo no se recuerda.
  }
}

export function usePref(key, initial) {
  const [value, setValue] = useState(() => loadPref(key, initial));
  const update = useCallback(
    (next) =>
      setValue((current) => {
        const resolved = typeof next === "function" ? next(current) : next;
        savePref(key, resolved);
        return resolved;
      }),
    [key],
  );
  return [value, update];
}
