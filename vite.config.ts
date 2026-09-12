import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // The API runs in the Workers runtime via `npm run dev:api` on 8788.
      // Proxying keeps the browser single-origin, same as in production.
      '/api': 'http://127.0.0.1:8788',
    },
  },
  build: {
    outDir: 'dist',
  },
})
