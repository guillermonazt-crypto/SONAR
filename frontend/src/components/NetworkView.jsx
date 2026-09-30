import { useViewState } from "../utils/viewState";
import Optics from "./Optics";
import Reports from "./Reports";
import Segmented from "./Segmented";
import SitePicker from "./SitePicker";

/** Red: por plantel, su topología CDP/LLDP, APs y teléfonos conectados y ópticas de fibra. */
export default function NetworkView({ plantel, siteName, sites = [], onPlantelChange, onOpenPort }) {
  const [segment, setSegment] = useViewState("network", "topologia");
  if (!plantel) {
    return (
      <>
        <div className="page-head">
          <div>
            <h1 className="page-title">Red</h1>
            <p className="page-subtitle">Elige un plantel para ver su topología, equipos conectados y fibra.</p>
          </div>
        </div>
        <SitePicker sites={sites} onSelect={onPlantelChange} />
      </>
    );
  }
  return (
    <>
      <div className="page-head">
        <div>
          <button type="button" className="back-button" onClick={() => onPlantelChange("")}>‹ Todos los planteles</button>
          <h1 className="page-title">{siteName || "Red"}</h1>
          <p className="page-subtitle">Enlaces entre switches, equipos conectados y fibra de este plantel.</p>
        </div>
        <Segmented
          label="Vista de red"
          value={segment}
          onChange={setSegment}
          options={[["topologia", "Topología"], ["aps-telefonos", "APs y teléfonos"], ["opticas", "Ópticas"]]}
        />
      </div>
      {segment === "opticas" ? (
        <Optics key={plantel} plantel={plantel} onOpenPort={onOpenPort} />
      ) : (
        <Reports key={`${plantel}-${segment}`} plantel={plantel} onOpenPort={onOpenPort} kinds={[segment]} viewKey="network-report" heading={false} />
      )}
    </>
  );
}
