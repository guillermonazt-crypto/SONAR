import { useViewState } from "../utils/viewState";
import Optics from "./Optics";
import Reports from "./Reports";
import Segmented from "./Segmented";

/** Red: topología CDP/LLDP, APs y teléfonos conectados y ópticas de fibra. */
export default function NetworkView({ plantel, onOpenPort }) {
  const [segment, setSegment] = useViewState("network", "topologia");
  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Red</h1>
          <p className="page-subtitle">Enlaces entre switches, equipos conectados y fibra.</p>
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
