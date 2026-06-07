import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The React dev server talks to the FastAPI backend through this proxy,
    // so the frontend just calls /api/* (same-origin, no CORS headaches).
    proxy: {
      '/api': 'http://localhost:8800',
    },
  },
})
