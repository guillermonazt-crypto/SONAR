/** Plantel › Switch › Puerto: dónde está el usuario y cómo subir un nivel. */
export default function Breadcrumb({ items }) {
  return (
    <nav className="breadcrumb" aria-label="Ubicación">
      <ol>
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <li key={`${index}-${item.label}`}>
              {last || !item.onClick ? (
                <span aria-current={last ? "location" : undefined}>{item.label}</span>
              ) : (
                <button type="button" className="text-button" onClick={item.onClick}>{item.label}</button>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
