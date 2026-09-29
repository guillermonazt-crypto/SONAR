import { useEffect, useRef } from "react";
import { Chart, CategoryScale, LinearScale, LineElement, PointElement, LineController, Tooltip, Legend } from "chart.js";
import { cssVar, useTheme } from "../utils/theme";

Chart.register(CategoryScale, LinearScale, LineElement, PointElement, LineController, Tooltip, Legend);

export const hourLabel = (time) =>
  new Date(time).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", hour12: false });

function lineOptions(format, max) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    elements: { point: { radius: 0, hoverRadius: 4 }, line: { borderWidth: 2, tension: 0.25 } },
    plugins: {
      legend: { position: "bottom", labels: { color: cssVar("text-2"), boxWidth: 10, boxHeight: 2 } },
      tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${format(context.raw)}` } },
    },
    scales: {
      y: {
        beginAtZero: true,
        max,
        ticks: { color: cssVar("muted"), maxTicksLimit: 4, callback: (value) => format(value) },
        grid: { color: cssVar("grid-line") },
      },
      x: { ticks: { color: cssVar("muted-2"), maxTicksLimit: 5, maxRotation: 0, autoSkipPadding: 12 }, grid: { display: false } },
    },
  };
}

const seriesValues = (points, key) => points.map((point) => (Number.isFinite(point[key]) ? point[key] : null));

/**
 * Gráfica de líneas con los colores del tema. `series`: [[clave, nombre, color]];
 * `xKey` y `xLabel` eligen el eje X (por defecto la hora de `time`).
 */
export default function LineChart({ points, series, format, max, label, xKey = "time", xLabel = hourLabel }) {
  const canvas = useRef(null);
  const chart = useRef(null);
  const axis = useRef(xLabel);
  axis.current = xLabel;
  const theme = useTheme();
  const labels = () => points.map((point) => axis.current(point[xKey]));
  useEffect(() => {
    if (!canvas.current) return undefined;
    chart.current = new Chart(canvas.current, {
      type: "line",
      data: {
        labels: labels(),
        datasets: series.map(([key, name, color]) => ({
          label: name,
          data: seriesValues(points, key),
          borderColor: cssVar(color),
          backgroundColor: cssVar(color),
          spanGaps: true,
        })),
      },
      options: lineOptions(format, max),
    });
    return () => {
      chart.current.destroy();
      chart.current = null;
    };
  }, [series, format, max, theme]);
  // El refresco automático sólo cambia los datos: se actualiza la gráfica en sitio, sin recrearla.
  useEffect(() => {
    if (!chart.current?.canvas) return;
    chart.current.data.labels = labels();
    chart.current.data.datasets.forEach((dataset, index) => {
      dataset.data = seriesValues(points, series[index][0]);
    });
    chart.current.update("none");
  }, [points]);
  return <div className="device-chart"><canvas ref={canvas} role="img" aria-label={label} /></div>;
}
