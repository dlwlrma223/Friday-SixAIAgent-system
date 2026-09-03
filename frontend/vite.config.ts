import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    watch: {
      // Docker/colima's virtual filesystem doesn't reliably forward inotify
      // events for bind-mounted volumes, so chokidar needs polling to see
      // host-side file edits.
      usePolling: true,
      interval: 300,
    },
  },
})
