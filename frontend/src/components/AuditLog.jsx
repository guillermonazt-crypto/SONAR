import { useState } from "react";
import { api } from "../api/client";
import SonarDataTable from "./DataTable";

const ACTIONS = { crear: "Alta", editar: "Edición", eliminar: "Baja", reconocer: "Reconoció alerta", sesion: "Inicio de sesión" };

function changesText(changes) {
  return Object.entries(changes || {})
    .map(([field, value]) => (Array.isArray(value) ? `${field}: ${value[0] ?? "—"} → ${value[1] ?? "—"}` : `${field}: ${value}`))
    .join(" · ");
}

/** Bitácora de cambios; se carga al abrir la sección. */
export default function AuditLog() {
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    try {
      setEntries(await api.auditLog());
      setError("");
    } catch (exception) {
      setError(exception.message);
    }
  }

  const columns = [
    { name: "Fecha", sortable: true, width: "180px", selector: (e) => e.momento, cell: (e) => <small>{new Date(e.momento).toLocaleString()}</small> },
    { name: "Usuario", sortable: true, width: "140px", selector: (e) => e.usuario_nombre },
    { name: "Acción", sortable: true, width: "150px", selector: (e) => ACTIONS[e.accion] || e.accion },
    { name: "Detalle", grow: 3, cell: (e) => <div><strong>{e.descripcion}</strong><small>{changesText(e.cambios)}</small></div> },
  ];
  return (
    <details className="inventory-secondary" onToggle={(event) => event.currentTarget.open && load()}>
      <summary>Bitácora de cambios</summary>
      {error && <p role="alert">{error}</p>}
      {entries === null ? (
        <p role="status">Cargando bitácora…</p>
      ) : (
        <div className="table-scroll sonar-table">
          <SonarDataTable columns={columns} data={entries} noDataComponent="Sin cambios registrados." />
        </div>
      )}
    </details>
  );
}
