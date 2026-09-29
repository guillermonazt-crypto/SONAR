import { neighborType } from "../utils/neighbor";

/** Ícono y nombre del tipo de equipo vecino (AP, teléfono, switch…). */
export default function NeighborTypeLabel({ kind, label }) {
  const type = neighborType(kind);
  if (!type) return label || "—";
  return (
    <span className={`neighbor-type neighbor-${kind}`}>
      <span aria-hidden="true">{type.icon}</span> {label || type.label}
    </span>
  );
}
