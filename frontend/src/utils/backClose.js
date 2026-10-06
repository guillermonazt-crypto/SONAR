// En el celular, el botón Atrás del teléfono cierra la hoja abierta (detalle de
// switch o puerto, "Más"…) en lugar de salir de SONAR. Cada diálogo modal que se
// abre agrega una entrada al historial; Atrás pulsa su botón "Cerrar…" y, si se
// cierra con el botón, se retira la entrada que había agregado.
export const MOBILE_QUERY = "(max-width: 768px)";
// Diálogos modales y popovers que en el celular se muestran como hoja inferior.
const SHEETS = '[role="dialog"][aria-modal="true"], .topology-detail';

const isMobile = () => Boolean(window.matchMedia?.(MOBILE_QUERY).matches);

function openDialogs(root) {
  return [...root.querySelectorAll(SHEETS)];
}

/** Botón "Cerrar…" propio del diálogo (no el de un diálogo anidado). */
export function closeButton(dialog) {
  return [...dialog.querySelectorAll("button")].find((button) => {
    const label = (button.getAttribute("aria-label") || button.textContent || "").trim();
    return /^cerrar/i.test(label) && button.closest(SHEETS) === dialog;
  });
}

export function installBackClose(root = document.body) {
  let count = openDialogs(root).length;
  let pushed = 0; // entradas agregadas por hojas abiertas
  let ignore = 0; // popstate provocados por history.go de este módulo
  let closingFromBack = 0; // cierres pedidos por Atrás que el observador aún no ve

  const observer = new MutationObserver(() => {
    const now = openDialogs(root).length;
    if (now > count && isMobile()) {
      for (let index = count; index < now; index += 1) {
        window.history.pushState({ sonarSheet: true }, "");
        pushed += 1;
      }
    } else if (now < count) {
      let closed = count - now;
      const fromBack = Math.min(closed, closingFromBack);
      closingFromBack -= fromBack;
      closed -= fromBack;
      const extra = Math.min(closed, pushed);
      if (extra > 0) {
        pushed -= extra;
        ignore += 1;
        window.history.go(-extra);
      }
    }
    count = now;
  });
  observer.observe(root, { childList: true, subtree: true });

  const onPop = () => {
    if (ignore > 0) {
      ignore -= 1;
      return;
    }
    if (pushed <= 0) return;
    pushed -= 1;
    const dialogs = openDialogs(root);
    const last = dialogs[dialogs.length - 1];
    if (!last) return;
    closingFromBack += 1;
    const button = closeButton(last);
    if (button) button.click();
    else document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  };
  window.addEventListener("popstate", onPop);
  return () => {
    observer.disconnect();
    window.removeEventListener("popstate", onPop);
  };
}
