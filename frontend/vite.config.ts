import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend owns the API; Vite only serves the UI in dev and proxies through.
const API = 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Every backend route must be listed here -- a path missing from this list
    // isn't a 404, Vite serves index.html for it with a 200, so the failure
    // surfaces as a component that silently renders nothing (see ScopePicker).
    proxy: Object.fromEntries(
      ['/ask', '/ask_spec', '/health', '/scopes', '/export', '/efficiency', '/boundary'].map(p => [p, API]),
    ),
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
