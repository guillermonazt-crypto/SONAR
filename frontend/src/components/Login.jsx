import { useState } from "react";
import { api } from "../api/client";
export default function Login({ onLogin }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = Object.fromEntries(new FormData(event.target));
      onLogin((await api.login(data)).user);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card login">
      <span className="eyebrow">CENTRO DE OPERACIONES</span>
      <h2>Bienvenido a SONAR</h2>
      <p>Inicia sesión para consultar tu red.</p>
      <form onSubmit={submit}>
        <label>
          Usuario
          <input name="username" autoComplete="username" required />
        </label>
        <label>
          Contraseña
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <button className="primary" disabled={busy}>
          {busy ? "Conectando…" : "Entrar"}
        </button>
      </form>
    </section>
  );
}
