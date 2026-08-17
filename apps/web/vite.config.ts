import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API and the web app are two processes in development, so the browser
// would otherwise be making cross-origin requests to a server that has no CORS
// configuration — deliberately, since it is meant to be reachable only from
// this machine. Proxying instead keeps the API single-origin and unauthenticated
// without opening it to anything.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        // Nothing here disables buffering for Server-Sent Events, because
        // nothing needs to: the proxy streams by default, and the API already
        // sends the `Cache-Control: no-cache` and `X-Accel-Buffering: no`
        // headers that keep it that way. Verified by watching events arrive
        // through this proxy at the interval they were sent, not in one lump.
      },
    },
  },
})
