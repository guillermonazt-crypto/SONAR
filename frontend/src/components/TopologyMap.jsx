import { useMemo, useState } from "react";
import { useViewState } from "../utils/viewState";

// Ícono y color de cada nodo del mapa. Lo que no es AP ni teléfono se dibuja como switch.
const KINDS = {
  switch: { icon: "🖥", label: "Switch / enlace" },
  ap: { icon: "📶", label: "Access point" },
  telefono: { icon: "☎", label: "Teléfono IP" },
};
const LEAF_KINDS = ["ap", "telefono"];
// Uso del puerto que colorea el enlace (igual que el reporte de puertos saturados).
const SATURATED = 90;
const ATTENTION = 70;
const LEAF_GAP = 22;

const shortName = (name) => (name || "").split(".")[0];
const kindOf = (row) => (LEAF_KINDS.includes(row.vecino_tipo) ? row.vecino_tipo : "switch");

function linkLevel(usage) {
  if (usage === null || usage === undefined) return "";
  if (usage >= SATURATED) return "saturated";
  if (usage >= ATTENTION) return "attention";
  return "";
}

/** Coloca las hojas (APs/teléfonos) en abanico hacia afuera del switch, en anillos si son muchas. */
function placeLeaves(parent, leaves, center, fullCircle) {
  const base = fullCircle ? -Math.PI / 2 : Math.atan2(parent.y - center, parent.x - center);
  const spread = fullCircle ? 2 * Math.PI : Math.PI * 0.8;
  let ring = 0;
  let placed = 0;
  let farthest = 0;
  while (placed < leaves.length) {
    const distance = 56 + ring * 30;
    const capacity = Math.max(1, Math.floor((spread * distance) / LEAF_GAP));
    const count = Math.min(capacity, leaves.length - placed);
    for (let index = 0; index < count; index += 1) {
      const angle = fullCircle
        ? base + (spread * index) / count
        : base + (count === 1 ? 0 : -spread / 2 + (spread * index) / (count - 1));
      const leaf = leaves[placed + index];
      leaf.x = parent.x + distance * Math.cos(angle);
      leaf.y = parent.y + distance * Math.sin(angle);
    }
    placed += count;
    farthest = distance;
    ring += 1;
  }
  return farthest;
}

function Detail({ node, onOpenPort, onClose }) {
  const row = node.row;
  const fields = node.kind === "switch"
    ? [
        ["IP", node.ip],
        ["En inventario", node.known ? "Sí" : "No"],
        ["Access points", node.counts.ap],
        ["Teléfonos", node.counts.telefono],
      ]
    : [
        ["Modelo", row.plataforma],
        ["MAC", row.mac],
        ["IP", row.vecino_ip],
        ["VLAN", row.vlan],
        ["Switch / puerto", `${row.switch} · ${row.puerto}`],
        ["PoE", row.poe_w !== null && row.poe_w !== undefined ? `${row.poe_w} W` : null],
      ];
  return (
    <aside className={`topology-detail topology-kind-${node.kind}`} aria-label={`Detalle de ${node.name}`}>
      <header>
        <span className="topology-detail-icon" aria-hidden="true">{KINDS[node.kind].icon}</span>
        <div>
          <strong>{node.name}</strong>
          <small>{KINDS[node.kind].label}</small>
        </div>
        <button type="button" className="chip" onClick={onClose} aria-label="Cerrar detalle">✕</button>
      </header>
      <dl>
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value === null || value === undefined || value === "" ? "—" : String(value)}</dd>
          </div>
        ))}
      </dl>
      {row?.puerto_id && (
        <button type="button" onClick={() => onOpenPort({ id: row.switch_id, nombre: row.switch, hostname: "" }, row.puerto_id)}>
          Ver puerto
        </button>
      )}
    </aside>
  );
}

/**
 * Mapa de enlaces CDP/LLDP: switches (y vecinos de infraestructura) en círculo y,
 * colgando de cada uno, los access points y teléfonos detectados en sus puertos.
 * El enlace se colorea por el uso del puerto; al hacer clic en un nodo se ve su detalle.
 */
export default function TopologyMap({ rows: allRows, onOpenPort = () => {} }) {
  const [show, setShow] = useViewState("topology-leaves", { ap: true, telefono: true });
  const [selected, setSelected] = useState(null);

  const totals = useMemo(() => ({
    ap: allRows.filter((row) => row.vecino_tipo === "ap").length,
    telefono: allRows.filter((row) => row.vecino_tipo === "telefono").length,
  }), [allRows]);

  const map = useMemo(() => {
    const hubs = new Map();
    const hub = (name, extra) => {
      if (!hubs.has(name)) hubs.set(name, { id: `sw:${name}`, name, kind: "switch", known: true, ip: "", counts: { ap: 0, telefono: 0 }, leaves: [], ...extra });
      return hubs.get(name);
    };
    const links = new Map();
    const leaves = [];
    allRows.forEach((row) => {
      const local = hub(row.switch);
      const kind = kindOf(row);
      if (kind !== "switch") {
        local.counts[kind] += 1;
        if (!show[kind]) return;
        const leaf = { id: `leaf:${row.switch}|${row.puerto}`, name: shortName(row.vecino), kind, row, parent: local };
        local.leaves.push(leaf);
        leaves.push(leaf);
        return;
      }
      const name = shortName(row.vecino);
      const neighbor = hub(name, { known: row.en_inventario === "Sí", ip: row.vecino_ip || "", row: null });
      if (row.en_inventario === "Sí") neighbor.known = true;
      if (!neighbor.ip && row.vecino_ip) neighbor.ip = row.vecino_ip;
      const key = [local.name, name].sort().join("|");
      const usage = Math.max(links.get(key)?.usage ?? -1, row.uso_pct ?? -1);
      links.set(key, { key, from: local, to: neighbor, usage: usage < 0 ? null : usage });
    });
    const list = [...hubs.values()];
    const single = list.length === 1;
    const radius = single ? 0 : Math.max(140, list.length * 22);
    list.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / list.length - Math.PI / 2;
      node.x = radius * Math.cos(angle);
      node.y = radius * Math.sin(angle);
    });
    const reach = Math.max(0, ...list.map((node) => (node.leaves.length ? placeLeaves(node, node.leaves, 0, single) : 0)));
    const half = radius + reach + 70;
    [...list, ...leaves].forEach((node) => {
      node.x += half;
      node.y += half;
    });
    return { hubs: list, leaves, links: [...links.values()], size: half * 2 };
  }, [allRows, show]);

  if (!map.hubs.length) return null;
  const current = selected && [...map.hubs, ...map.leaves].find((node) => node.id === selected);
  const choose = (node) => setSelected((id) => (id === node.id ? null : node.id));
  const keyChoose = (node) => (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(node);
    }
  };
  const nodeClass = (node) => `topology-node-group topology-kind-${node.kind}${node.id === selected ? " selected" : ""}`;

  return (
    <div className="topology">
      <div className="topology-toolbar">
        <div className="topology-legend" aria-label="Leyenda del mapa">
          {Object.entries(KINDS).map(([kind, info]) => (
            <span key={kind} className={`topology-legend-item topology-kind-${kind}`}>
              <i aria-hidden="true">{info.icon}</i> {info.label}
            </span>
          ))}
          <span className="topology-legend-item"><i className="topology-legend-line saturated" aria-hidden="true" /> Enlace saturado (≥ {SATURATED} %)</span>
          <span className="topology-legend-item"><i className="topology-legend-line attention" aria-hidden="true" /> Atención (≥ {ATTENTION} %)</span>
          <span className="topology-legend-item"><i className="topology-legend-line external" aria-hidden="true" /> Fuera del inventario</span>
        </div>
        <div className="topology-toggles" role="group" aria-label="Mostrar en el mapa">
          {LEAF_KINDS.map((kind) => (
            <label key={kind} className="inline-field">
              <input
                type="checkbox"
                checked={show[kind]}
                onChange={(event) => setShow((current) => ({ ...current, [kind]: event.target.checked }))}
              />
              {kind === "ap" ? `Access points (${totals.ap})` : `Teléfonos (${totals.telefono})`}
            </label>
          ))}
        </div>
      </div>
      <div className="topology-body">
        <svg className="topology-map" viewBox={`0 0 ${map.size} ${map.size}`} role="img" aria-label="Mapa de enlaces CDP">
          {map.links.map((link) => (
            <line key={link.key} x1={link.from.x} y1={link.from.y} x2={link.to.x} y2={link.to.y}
              className={`topology-link ${linkLevel(link.usage)}`}>
              {link.usage !== null && <title>{`${link.from.name} ↔ ${link.to.name}: ${Math.round(link.usage)} % de uso`}</title>}
            </line>
          ))}
          {map.leaves.map((leaf) => (
            <line key={`${leaf.id}-link`} x1={leaf.parent.x} y1={leaf.parent.y} x2={leaf.x} y2={leaf.y}
              className={`topology-link leaf ${linkLevel(leaf.row.uso_pct)}`} />
          ))}
          {map.hubs.map((node) => (
            <g key={node.id} transform={`translate(${node.x} ${node.y})`} className={nodeClass(node)}
              role="button" tabIndex={0} aria-label={`Switch ${node.name}`} data-kind="switch"
              onClick={() => choose(node)} onKeyDown={keyChoose(node)}>
              <circle r="14" className={node.known ? "topology-node" : "topology-node external"} />
              <text y="5" textAnchor="middle" className="topology-icon" aria-hidden="true">{KINDS.switch.icon}</text>
              <text y="-20" textAnchor="middle" className="topology-label">{node.name}</text>
            </g>
          ))}
          {map.leaves.map((leaf) => (
            <g key={leaf.id} transform={`translate(${leaf.x} ${leaf.y})`} className={nodeClass(leaf)}
              role="button" tabIndex={0} aria-label={`${KINDS[leaf.kind].label} ${leaf.name}`} data-kind={leaf.kind}
              onClick={() => choose(leaf)} onKeyDown={keyChoose(leaf)}>
              <title>{`${leaf.name} · ${leaf.row.puerto}`}</title>
              <circle r="9" className="topology-node" />
              <text y="4" textAnchor="middle" className="topology-icon small" aria-hidden="true">{KINDS[leaf.kind].icon}</text>
              {(leaf.kind === "ap" || leaf.id === selected) && (
                <text y="-13" textAnchor="middle" className="topology-label small">{leaf.name}</text>
              )}
            </g>
          ))}
        </svg>
        {current && <Detail node={current} onOpenPort={onOpenPort} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}
