import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  envDir: '..',
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg'],
      manifest: {
        name: 'JARVIS — Asistente personal',
        short_name: 'JARVIS',
        description: 'Interfaz de tu asistente personal',
        theme_color: '#05090d',
        background_color: '#05090d',
        display: 'standalone',
        orientation: 'any',
        start_url: '/',
        icons: [
          { src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any maskable' }
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
})
