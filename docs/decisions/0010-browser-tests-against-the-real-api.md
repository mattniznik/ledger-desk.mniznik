# 0010. The browser tests run against the real app API in replay mode, not a stand-in

**Status:** accepted, 2026-11-14

## Decision

The page's browser tests (`web/e2e/`, Playwright, 1280 x 800 and 390 x 844 with reduced motion) start the real
app API on a freshly seeded database of their own (`ledger_desk_e2e`, port 8290) and the production build of the
page through `vite preview` (`web/playwright.config.ts`). In replay mode the API sends no request to a model: the
recorded replies go back through today's code ([0005](0005-recorded-real-runs-replayed-through-current-code.md)).
CI provides Postgres as a service.

## Sources

- Playwright 1.65.1, `TestConfig` type (read 2026-11-14 in the installed `@playwright/test`):
  `webServer?: TestConfigWebServer | TestConfigWebServer[]`, each with its own `cwd`, `env` and readiness `url`.
- Vite, preview options (read 2026-11-14): `preview.proxy`, "Default: `server.proxy`" - so the preview server
  forwards `/api` the way the dev server does (`web/vite.config.ts`).

## Evidence (this repository)

- The first runs found a real bug: two visitors opening the same bill at once re-rendered its PDF while the other
  was reading it, pypdf raised "Cannot read an empty file", and the bill fell out of the queue (2 failing runs
  of 3). A stand-in serving recorded responses could not have shown it. Fixed in `documents.render_case`, which now
  writes a bill only when its bytes change: the stress test in `tests/test_documents.py` failed 3 of 3 runs on the
  old code (573 to 601 empty reads each) and passes since, and two more tests cover the atomic replace of a changed
  bill and the wait while a reader holds it.
- Rehearsing CI on Linux from a clean copy of the published files found two more: `db-reset` used a fixed admin
  address while the app used `LEDGER_DESK_DB_URL`, and several tests needed rendered documents a clean checkout
  does not have. Both fixed test-first.
- The browser tests: 60 of 60 (30 tests at two sizes) on two runs in a row on Windows, 2026-11-14. The first
  version, 6 of 6, also passed on Linux in Playwright's image; the full set has not run on Linux yet.

## Rejected

- **A stand-in server answering `/api` from recordings** (the pattern in this demo's sibling projects, whose
  backends call a model live). Here the backend calls no model in replay mode, so the stand-in would only add code
  that has to imitate the API, and it would hide the API's own bugs.

## Trade-off

The browser tests need Postgres, locally (`docker compose up -d db`) and in CI (a service container), and take
longer to start than a static server.

## What would change it

A live mode that calls a model per visitor: its tests would then need a stand-in for that path.
