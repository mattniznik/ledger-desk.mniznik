// Browser tests for the page (e2e/*.e2e.ts) against the real app API in replay mode: recorded Claude runs go
// back through today's code, so no model is called and nothing is spent. The API gets its own freshly seeded
// database and port, so a developer's running API and data are left alone; it needs the local Postgres
// (`docker compose up -d db`, or the CI service). Desktop and phone sizes. Run: npm run e2e
import { defineConfig } from '@playwright/test'

const WEB = Number(process.env.E2E_WEB_PORT || 5191)
const API = Number(process.env.E2E_API_PORT || 8290)
const DB = 'ledger_desk_e2e'

export default defineConfig({
  testDir: 'e2e',
  testMatch: '*.e2e.ts', // not *.test.ts: Vitest would pick those up as its own tests
  fullyParallel: true,
  // Every test is a new visitor whose 13 bills go through one API process, and Python runs one thread at a time,
  // so past about 8 workers the tests measure that process, not the page. Measured on a 32-thread laptop on
  // battery: 16 workers timed out 47 and 24 of 60 (2.1-2.4 min); 8 passed 60 of 60 twice (47 s). CI keeps
  // Playwright's default (half the runner's cores).
  workers: process.env.CI ? undefined : 8,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${WEB}`,
    reducedMotion: 'reduce', // still frames: no test waits on an animation
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { browserName: 'chromium', viewport: { width: 1280, height: 800 } } },
    { name: 'phone', use: { browserName: 'chromium', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: [
    {
      command: `uv run ledger-desk db-reset --name ${DB} && uv run ledger-desk api-serve --db ${DB} --port ${API}`,
      cwd: '..',
      url: `http://127.0.0.1:${API}/samples`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // the production build, served by vite preview (same /api proxy): what ships, and no dependency
      // optimiser reloading the page on a first start
      command: `npx vite build && npx vite preview --port ${WEB} --strictPort --host 127.0.0.1`,
      env: { LEDGER_DESK_API: `http://127.0.0.1:${API}` },
      url: `http://127.0.0.1:${WEB}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
