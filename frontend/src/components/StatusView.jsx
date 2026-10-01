import Monitoring from "./Monitoring";
import Overview from "./Overview";
import Segmented from "./Segmented";

/** Estado: salud por plantel y, un nivel abajo, sus switches y puertos. */
export default function StatusView({ plantel, siteName, segment, onSegment, onPlantelChange, onOpenPorts, focus, onFocusHandled, onSelect, onPortChange }) {
  return (
    <>
      <div className="page-head">
        <div>
          {plantel && (
            <button type="button" className="back-button" onClick={() => onPlantelChange("")}>‹ Todos los planteles</button>
          )}
          <h1 className="page-title">{plantel ? siteName : "Estado"}</h1>
          <p className="page-subtitle">{plantel ? "Salud del plantel, sus switches y puertos." : "Salud de cada plantel, sus switches y puertos."}</p>
        </div>
        <Segmented label="Nivel de detalle" value={segment} onChange={onSegment} options={[["sites", "Planteles"], ["switches", "Switches y puertos"]]} />
      </div>
      {segment === "switches" ? (
        <Monitoring key={plantel} plantel={plantel} focus={focus} onFocusHandled={onFocusHandled} onSelect={onSelect} onPortChange={onPortChange} />
      ) : (
        <Overview key={plantel} plantel={plantel} onPlantelChange={onPlantelChange} onOpenPorts={onOpenPorts} />
      )}
    </>
  );
}
