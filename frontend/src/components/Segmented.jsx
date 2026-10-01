/** Control segmentado (estilo iOS) para alternar sub-vistas. */
export default function Segmented({ label, options, value, onChange }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([id, text]) => (
        <button key={id} type="button" className={value === id ? "active" : ""} aria-pressed={value === id} onClick={() => onChange(id)}>
          {text}
        </button>
      ))}
    </div>
  );
}
