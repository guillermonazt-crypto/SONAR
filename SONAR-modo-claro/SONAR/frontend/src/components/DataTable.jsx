import DataTable from "react-data-table-component";

const customStyles = {
  table: { style: { backgroundColor: "transparent" } },
  headRow: { style: { backgroundColor: "var(--surface-3)", borderBottomColor: "var(--border-strong)", color: "var(--muted)", minHeight: "44px" } },
  headCells: { style: { fontSize: "11px", fontWeight: 700, letterSpacing: "0.7px", textTransform: "uppercase" } },
  rows: { style: { backgroundColor: "var(--surface-2)", color: "var(--text)", borderBottomColor: "var(--border)", minHeight: "66px" }, highlightOnHoverStyle: { backgroundColor: "var(--accent-soft)", color: "var(--text)", transitionDuration: "0.15s" } },
  cells: { style: { padding: "10px 14px" } },
  pagination: { style: { backgroundColor: "var(--surface-3)", color: "var(--muted)", borderTopColor: "var(--border-strong)" }, pageButtonsStyle: { color: "var(--text-2)", fill: "var(--text-2)", '&:disabled': { opacity: 0.35 }, '&:hover:not(:disabled)': { backgroundColor: "var(--accent-soft)" } } },
};

/** Tabla común de SONAR: búsqueda se controla desde la vista y el resto es DataTables. */
export default function SonarDataTable({ columns, data, progressPending, noDataComponent, ...props }) {
  return (
    <DataTable
      columns={columns}
      data={data}
      customStyles={customStyles}
      pagination
      paginationPerPage={10}
      paginationRowsPerPageOptions={[10, 25, 50, 100]}
      persistTableHead
      highlightOnHover
      pointerOnHover
      responsive
      progressPending={progressPending}
      noDataComponent={noDataComponent || "No hay registros para mostrar."}
      {...props}
    />
  );
}
