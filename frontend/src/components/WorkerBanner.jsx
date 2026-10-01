import { useEffect, useState } from "react";
import { api } from "../api/client";
import { timeAgo } from "../utils/format";
import "./contextual.css";

// El worker escribe su latido cada 30 s; se revisa con la misma frecuencia.
export const WORKER_CHECK_MS = 30000;

/** Aviso global cuando el worker dejó de latir (datos congelados) o InfluxDB tiene métricas en cola. */
export default function WorkerBanner() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let active = true;
    const check = () =>
      api.monitoring()
        .then((data) => active && setStatus(data))
        // Sin respuesta del backend no se sabe nada del worker: no se inventa el aviso.
        .catch(() => active && setStatus(null));
    check();
    const timer = setInterval(check, WORKER_CHECK_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  if (!status) return null;
  const influx = status.influx || {};
  return (
    <>
      {status.worker_offline && (
        <p role="alert" className="worker-offline">
          ⚠ Worker offline, datos congelados · último latido {timeAgo(status.latido)}
        </p>
      )}
      {!status.worker_offline && influx.disponible === false && (
        <p role="status" className="worker-alert">
          InfluxDB sin conexión: {influx.en_cola} métrica{influx.en_cola === 1 ? "" : "s"} en cola; el histórico se completa al volver.
        </p>
      )}
    </>
  );
}
