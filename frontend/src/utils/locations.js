// Coordenadas de los planteles de la UAEH para el mapa del NOC.
//
// Si el campo "ubicacion" del plantel (administrador de Django) contiene
// "latitud, longitud" se usa ese valor; si no, la tabla de abajo por nombre.
// Las posiciones son aproximadas (cabecera municipal o campus conocido):
// corrígelas desde el administrador sin tocar el código.
const KNOWN = {
  "instituto de artes": [20.1353, -98.7634],
  "instituto de ciencias agropecuarias": [20.0588, -98.3818],
  "instituto de ciencias basicas e ingenieria": [20.0942, -98.7115],
  "instituto de ciencias de la salud": [20.0712, -98.7458],
  "instituto de ciencias economico administrativas": [20.0735, -98.7415],
  "instituto de ciencias sociales y humanidades": [20.1315, -98.7589],
  "escuela superior actopan": [20.2703, -98.9447],
  "escuela superior apan": [19.7108, -98.4522],
  "escuela superior atotonilco de tula": [19.9933, -99.22],
  "escuela superior ciudad sahagun": [19.7719, -98.5783],
  "escuela superior huejutla": [21.1402, -98.4197],
  "escuela superior tepeji del rio": [19.9047, -99.3414],
  "escuela superior tizayuca": [19.8386, -98.9786],
  "escuela superior tlahuelilpan": [20.1311, -99.2314],
  "escuela superior zimapan": [20.7372, -99.3822],
  "escuela preparatoria numero 1": [20.1197, -98.7361],
  "escuela preparatoria numero 2": [20.0833, -98.3667],
  "escuela preparatoria numero 3": [20.1186, -98.7489],
  "escuela preparatoria numero 4": [20.1056, -98.7598],
  "escuela preparatoria numero 5": [20.1412, -99.2253],
  "escuela preparatoria numero 6": [20.1012, -98.7302],
  "escuela preparatoria numero 7": [20.1472, -98.7295],
  "escuela preparatoria numero 8": [19.8492, -98.9736],
  "escuela preparatoria numero 9": [20.0445, -98.7872],
};

// Centro del estado de Hidalgo: posición de reserva para planteles desconocidos.
export const HIDALGO_CENTER = [20.35, -98.85];

const normalize = (text) =>
  String(text || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();

export function parseCoordinates(text) {
  const match = String(text || "").match(/(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)/);
  if (!match) return null;
  const lat = Number(match[1]);
  const lng = Number(match[2]);
  return Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? [lat, lng] : null;
}

/** [lat, lng] del plantel, o null si no se conoce su posición. */
export function siteCoordinates(site) {
  return parseCoordinates(site?.ubicacion) || KNOWN[normalize(site?.nombre)] || null;
}
