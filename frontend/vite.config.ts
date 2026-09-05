import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend owns the API; Vite only serves the UI in dev and proxies through.
const API = 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ['/ask', '/ask_spec', '/health', '/export', '/efficiency'].map(p => [p, API]),
    ),
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
