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
