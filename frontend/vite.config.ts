import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Project Pages URL: https://<owner>.github.io/CECS327-Distributed-Lodging/
const repoBase = '/CECS327-Distributed-Lodging/'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === 'production' ? repoBase : '/',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
