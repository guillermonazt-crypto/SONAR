import DataTable from "react-data-table-component";

const customStyles = {
  table: { style: { backgroundColor: "transparent" } },
  headRow: { style: { backgroundColor: "#11141a", borderBottomColor: "#3a4051", color: "#a4abba", minHeight: "44px" } },
  headCells: { style: { fontSize: "11px", fontWeight: 700, letterSpacing: "0.7px", textTransform: "uppercase" } },
  rows: { style: { backgroundColor: "#161923", color: "#e0e0e0", borderBottomColor: "#2a2d3a", minHeight: "66px" }, highlightOnHoverStyle: { backgroundColor: "#1e2633", color: "#fff", transitionDuration: "0.15s" } },
  cells: { style: { padding: "10px 14px" } },
  pagination: { style: { backgroundColor: "#11141a", color: "#a4abba", borderTopColor: "#3a4051" }, pageButtonsStyle: { color: "#c8d0df", fill: "#c8d0df", '&:disabled': { opacity: 0.35 }, '&:hover:not(:disabled)': { backgroundColor: "#243344" } } },
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
