import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// SONAR_API permite apuntar el proxy a otro Django (p. ej. una segunda copia en :8001).
const API = process.env.SONAR_API || "http://127.0.0.1:8000";
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    allowedHosts: ["sonar.setel.online"],
    proxy: {
      "/static": { target: API },
      "/api": { target: API },
      "/admin": { target: API },
    },
  },
  test: { environment: "jsdom", setupFiles: "./src/test-setup.js" },
});
