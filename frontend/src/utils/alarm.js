// Aviso sonoro y notificación del sistema cuando un plantel pasa a crítico.

let context = null;

/** Dos tonos cortos descendentes (Web Audio: no requiere archivos de sonido). */
export function playAlarm() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return false;
    context = context || new AudioContext();
    if (context.state === "suspended") context.resume();
    const start = context.currentTime;
    [880, 660, 880, 660].forEach((frequency, index) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const at = start + index * 0.22;
      oscillator.type = "sine";
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.25, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.2);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(at);
      oscillator.stop(at + 0.21);
    });
    return true;
  } catch {
    return false;
  }
}

/** Notificación del sistema operativo si el usuario la permitió. */
export function notify(title, body) {
  try {
    if (!("Notification" in window) || Notification.permission !== "granted") return false;
    new Notification(title, { body, tag: "sonar-critical" });
    return true;
  } catch {
    return false;
  }
}

export function requestNotifications() {
  try {
    if ("Notification" in window && Notification.permission === "default") return Notification.requestPermission();
  } catch {
    // Navegadores sin soporte: sólo queda el aviso en pantalla.
  }
  return Promise.resolve(window.Notification?.permission || "denied");
}
