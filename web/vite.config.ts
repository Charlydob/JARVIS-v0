import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig(({ mode }) => {
  const buildEnv = loadEnv(mode, '..', '')
  const vadSilenceSeconds = buildEnv.JARVIS_VAD_SILENCE_SECONDS || '1.5'
  const appVersion = buildEnv.VITE_APP_VERSION || 'unknown'
  return {
  envDir: '..',
  define: {
    'import.meta.env.JARVIS_VAD_SILENCE_SECONDS': JSON.stringify(vadSilenceSeconds),
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
  },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg'],
      manifest: {
        name: 'JARVIS — Asistente personal',
        short_name: 'JARVIS',
        description: 'Interfaz de tu asistente personal',
        lang: 'es',
        theme_color: '#000000',
        background_color: '#000000',
        display: 'standalone',
        orientation: 'any',
        start_url: '/',
        icons: [
          { src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
          { src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'maskable' }
        ]
      },
      workbox: {
        navigateFallback: '/index.html',
        runtimeCaching: [{
          urlPattern: /\/api\//,
          handler: 'NetworkOnly'
        }]
      }
    })
  ],
  server: {
    host: true,
    port: 5173
  }
  }
})
