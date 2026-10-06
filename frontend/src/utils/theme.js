import { useEffect, useState } from "react";

const KEY = "sonar-theme";
const EVENT = "sonar-theme-change";

function storedTheme() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // Sin localStorage (modo privado): se usa la preferencia del sistema.
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

// Color de la barra del navegador en el celular (index.html trae el del sistema).
const BAR_COLORS = { light: "#e7ebf0", dark: "#000000" };

function syncBarColor(theme) {
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => meta.setAttribute("content", BAR_COLORS[theme] || BAR_COLORS.dark));
}

/** Aplica el tema guardado antes del primer render para evitar el parpadeo. */
export function initTheme() {
  document.documentElement.dataset.theme = storedTheme();
  syncBarColor(document.documentElement.dataset.theme);
}

export function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  syncBarColor(theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Se aplica aunque no se pueda recordar.
  }
  window.dispatchEvent(new Event(EVENT));
}

/** Tema activo; los componentes con canvas lo usan para redibujarse. */
export function useTheme() {
  const [theme, setState] = useState(currentTheme);
  useEffect(() => {
    const update = () => setState(currentTheme());
    window.addEventListener(EVENT, update);
    return () => window.removeEventListener(EVENT, update);
  }, []);
  return theme;
}

/** Valor resuelto de una variable CSS (chart.js no entiende var()). */
export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}
