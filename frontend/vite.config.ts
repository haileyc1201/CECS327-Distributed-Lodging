import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Project Pages URL: https://<owner>.github.io/CECS327-Distributed-Lodging/
const repoBase = '/CECS327-Distributed-Lodging/'

export default defineConfig(({ mode }) => {
  // Cloudflare Workers Assets need root base; GitHub Pages needs repo subpath.
  const forCloudflare = process.env.VITE_DEPLOY_TARGET === 'cloudflare'
  return {
    plugins: [react()],
    base: forCloudflare ? '/' : mode === 'production' ? repoBase : '/',
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
