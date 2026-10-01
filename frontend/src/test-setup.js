import "@testing-library/jest-dom/vitest";

// react-data-table-component consulta matchMedia para sus breakpoints;
// jsdom no lo implementa de forma nativa.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// La vista abierta (pestaña, switch, puerto) se recuerda en sessionStorage:
// cada prueba empieza desde cero.
import { beforeEach } from "vitest";
beforeEach(() => sessionStorage.clear());
