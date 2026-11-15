import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'
import { bootScript } from './src/studio/boot.ts'
import { STORAGE_KEY } from './src/studio/choice.ts'
import { PRESETS } from './src/studio/presets.ts'

// The app API runs on 127.0.0.1:8200 (`uv run ledger-desk api-serve`); the dev server proxies
// /api to it, so the browser talks to one origin and no CORS setup is needed. The browser tests start
// their own API on another port and point LEDGER_DESK_API at it (playwright.config.ts).
const API = process.env.LEDGER_DESK_API || 'http://127.0.0.1:8200'

// The Studio's boot script, inline in index.html so it runs before any bundle: it paints the visitor's background
// and hides the page until it has rendered (src/studio/boot.ts). Made from the presets at build time, so the page
// and the script cannot disagree on a palette.
function studioBoot(): Plugin {
  return {
    name: 'ledger-desk-studio-boot',
    transformIndexHtml(html) {
      if (!html.includes('/*studio-boot*/')) throw new Error('index.html lost its /*studio-boot*/ placeholder')
      return html.replace('/*studio-boot*/', () => bootScript(PRESETS, STORAGE_KEY))
    },
  }
}

export default defineConfig({
  plugins: [react(), studioBoot()],
  server: {
    proxy: {
      '/api': { target: API, rewrite: (path) => path.replace(/^\/api/, '') },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
})
