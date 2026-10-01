// Tipo del equipo vecino (CDP/LLDP), tal como lo clasifica el worker.
export const NEIGHBOR_TYPES = {
  telefono: { icon: "☎", label: "Teléfono IP" },
  ap: { icon: "📶", label: "Access point" },
  switch: { icon: "⇄", label: "Switch" },
  router: { icon: "⌖", label: "Router" },
  otro: { icon: "•", label: "Otro" },
};

export function neighborType(kind) {
  return NEIGHBOR_TYPES[kind] || null;
}
