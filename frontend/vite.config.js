import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The React dev server talks to the FastAPI backend through this proxy,
    // so the frontend just calls /api/* (same-origin, no CORS headaches).
    // `ws: true` proxies WebSocket upgrades too. Hoy no hay ninguno: el único era
    // el streaming de Conductor, que se sacó el 2026-09-09. Se deja puesto porque
    // no cuesta nada y evita el bug de un solo síntoma —"funciona todo menos el
    // tiempo real"— el día que aparezca otro.
    // VITE_PROXY_TARGET permite apuntar a un backend distinto del de siempre
    // (:8800 corre como servicio systemd y es el de producción de esta
    // máquina) — sirve para probar cambios del backend sin reiniciar el
    // servicio real. Sin la variable, todo sigue igual que antes.
    proxy: {
      '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8800', ws: true },
    },
  },
})
