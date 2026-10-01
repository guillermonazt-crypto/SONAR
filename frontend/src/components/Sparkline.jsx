// Mini gráfica de líneas en SVG (sin chart.js) para tendencias dentro de una tarjeta.
const WIDTH = 160;
const HEIGHT = 36;
const PAD = 3;

/**
 * points: [{...}]; series: [[clave, etiqueta, clase CSS]]. Cada serie se dibuja
 * sobre la misma escala vertical para que se comparen entre sí.
 */
export default function Sparkline({ points = [], series, label, format = (value) => value }) {
  const values = points.flatMap((point) => series.map(([key]) => point[key])).filter(Number.isFinite);
  if (points.length < 2 || !values.length) return <small className="sparkline-empty">Sin historial aún</small>;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (max - min < 0.5) {
    // Una señal estable no debe verse como una montaña rusa: rango mínimo de 0.5.
    const middle = (max + min) / 2;
    min = middle - 0.25;
    max = middle + 0.25;
  }
  const x = (index) => PAD + (index * (WIDTH - 2 * PAD)) / (points.length - 1);
  const y = (value) => PAD + ((max - value) * (HEIGHT - 2 * PAD)) / (max - min);
  const path = (key) =>
    points
      .map((point, index) => (Number.isFinite(point[key]) ? `${x(index).toFixed(1)},${y(point[key]).toFixed(1)}` : null))
      .filter(Boolean)
      .join(" ");
  const summary = series
    .map(([key, name]) => {
      const own = points.map((point) => point[key]).filter(Number.isFinite);
      return own.length ? `${name} ${format(Math.min(...own))} a ${format(Math.max(...own))}` : null;
    })
    .filter(Boolean)
    .join(" · ");
  return (
    <figure className="sparkline" aria-label={`${label}: ${summary}`}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-hidden="true">
        {series.map(([key, , className]) => (
          <polyline key={key} className={className} points={path(key)} fill="none" vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      <figcaption>{summary}</figcaption>
    </figure>
  );
}
