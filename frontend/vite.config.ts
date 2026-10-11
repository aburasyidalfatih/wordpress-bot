import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Only backend-only paths are proxied. SPA routes such as /login must be
    // served by Vite, otherwise a full-page load gets Flask's stale dist index.
    // /logout is a real Flask JSON endpoint (fetched by Layout), not an SPA route.
    proxy: {
      '/api': 'http://127.0.0.1:5005',
      '/logout': 'http://127.0.0.1:5005',
      '/download-logs': 'http://127.0.0.1:5005',
      '/save-config': 'http://127.0.0.1:5005',
      '/save-prompts': 'http://127.0.0.1:5005',
      '/manual-post': 'http://127.0.0.1:5005',
      '/manual-research': 'http://127.0.0.1:5005',
      '/sync-engagement': 'http://127.0.0.1:5005',
      '/optimize-categories': 'http://127.0.0.1:5005',
      '/test-telegram': 'http://127.0.0.1:5005',
      '/fetch-categories': 'http://127.0.0.1:5005',
      '/test-generate': 'http://127.0.0.1:5005',
    }
  }
})
