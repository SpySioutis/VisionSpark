import basicSsl from '@vitejs/plugin-basic-ssl'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // Self-signed HTTPS is on by default (opt out with VITE_HTTPS=0) so
    // the phone camera and microphone work over the LAN with no extra
    // flags. Each browser shows a certificate warning once; accept it.
    ...(process.env.VITE_HTTPS === '0' ? [] : [basicSsl()]),
  ],
  server: {
    // Listen on all interfaces so a phone on the same Wi-Fi can open the
    // app with no extra flags (HTTPS by default, so the camera works).
    host: true,
    port: 5173,
    strictPort: true,
    // Extra hosts allowed through an HTTPS tunnel, comma-separated
    // (for example VITE_ALLOWED_HOSTS=.trycloudflare.com).
    allowedHosts: (process.env.VITE_ALLOWED_HOSTS ?? '')
      .split(',')
      .map((host) => host.trim())
      .filter(Boolean),
    // Non-localhost browsers call the same origin (see src/lib/api.js),
    // so the dev server proxies API calls to the localhost backend.
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
