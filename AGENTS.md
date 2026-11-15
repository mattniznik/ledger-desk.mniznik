# AGENTS.md

How work is done in this repository, for coding agents and for people. Claude Code reads this file because the
repository has no `CLAUDE.md`: "By default, Claude reads `AGENTS.md` only when you have no `CLAUDE.md` in your
working directory or above it" ([Claude Code memory docs](https://code.claude.com/docs/en/memory), read
2026-11-14). It stays short because it is loaded into every session.

## Map

- `src/ledger_desk/company.py` - the fictional roastery: vendors, chart of accounts, purchase orders, deliveries
  and paid bills, generated from a fixed seed.
- `src/ledger_desk/invoices.py`, `documents.py` - the sample invoices (`invoices/*.yaml`, each with the result the
  checks must produce) and their rendering to PDFs and a phone photo.
- `src/ledger_desk/reading.py` - Claude reads a bill into fields with a source quote each; code checks every quote
  against the PDF's text layer.
- `src/ledger_desk/rules.py` - the checks: arithmetic, vendor, purchase order price and quantity, duplicates, bank
  details, unusual amounts, text aimed at an AI. The core of the product.
- `src/ledger_desk/accounts.py` - Claude suggests an account for a bill with no purchase order; code accepts it only
  if it is in the chart and fits the vendor.
- `src/ledger_desk/agent.py` - the investigating agent: read-only lookups, an explanation, a draft email.
- `src/ledger_desk/playbook.py` - the suggested next step for each problem, worked out by code.
- `src/ledger_desk/authority.py`, `approval.py` - who may decide what, and the Ed25519-signed approval.
- `src/ledger_desk/workflow.py` - one bill's run as a LangGraph graph, paused for the person's decision.
- `src/ledger_desk/erp/` - the mock ERP (its own tables, role and key) and its client.
- `src/ledger_desk/quickbooks.py` - the optional copy of approved bills to a QuickBooks Online sandbox.
- `src/ledger_desk/api.py` - the app API: visitor sessions, runs, decisions, the audit log.
- `src/ledger_desk/model.py`, `subscription.py`, `anthropic_api.py`, `runner.py` - the model port, its two adapters
  (a Claude Code subscription login for development and recordings, an API key for a deployed demo) and the
  replay of recorded runs.
- `src/ledger_desk/evals.py` - the eval harness and its graders.
- `migrations/` - the database: the ERP schema and role, the app tables, row-level security per visitor, the
  insert-only, hash-chained audit log.
- `evals/` - the eval variants and the hard tier; `evals/results/` - one results file per run.
- `replays/` - recorded real runs, replayed through today's code.
- `web/` - the page (React, Vite): the bill queue, the bill page, the walkthrough, the audit trail, How it works;
  `web/src/site-data.json` - every number the page shows about results and the build, written by
  `scripts/export_site.py`.
- `tests/` - pytest, one file per unit, on a local Postgres and recordings.
- `docs/decisions/` - why things are the way they are, each with its sources and measurements.
- `docs/DEPLOY.md` - how it runs on Microsoft Azure (Container Apps, PostgreSQL Flexible Server, Key Vault, Static Web
  Apps); the Terraform is kept privately.

## Checks (none calls a model)

```bash
docker compose up -d db                 # Postgres 17 on 127.0.0.1:55432, for the tests
uv run pytest -p no:warnings            # the Python suite
cd web && npm ci && npx vitest run      # the page's tests
npm run lint && npm run build           # the page
npx playwright install --only-shell chromium && npm run e2e   # browser tests, against the real API in replay mode
```

After a change to the tests, the eval results, the recorded runs, the decision records or the approval limits,
refresh the page's numbers. The export writes `web/src/site-data.json`, runs both suites against it, and puts the
old file back if any test fails; the current counts are in that file:

```bash
uv run python scripts/export_site.py
```

## Rules

1. **Test first, and watch it fail.** Write the test, run it, and see it fail on the old code for the reason you
   expect before writing the fix. A test that passes on the old code proves nothing about the change.
2. **The code checks are the product.** `rules.py`, `authority.py`, `playbook.py` and the database constraints in
   `migrations/` decide what reaches the books; the model reads and explains. Never delete or loosen a check or
   its assertion to make a run pass, never paste a computed value in as the expected one.
3. **Tests use recordings, never the network.** The model is a scripted fake or a recorded run
   (`runner.py` ReplayModel), QuickBooks a fake on `httpx.MockTransport`, the ERP an in-process app. Recording a
   new run is a change of its own, because a moved result has to mean the code changed.
4. **The eval answer key is frozen.** The expected results in `invoices/` and `evals/` change only with a written
   reason; a prompt change runs the full eval before it ships.
5. **Never `ANTHROPIC_API_KEY`.** A deployed demo's key lives in a git-ignored `.env.local` as
   `LEDGER_DESK_ANTHROPIC_KEY` and is handed to the client explicitly; the standard name would also switch a Claude
   Code subscription login on the same machine to paid per-token billing. The subscription adapter removes
   `ANTHROPIC_API_KEY` from its child process (`subscription.py`). The QuickBooks keys and token stay in
   `.env.local` too.
6. **Ask a person before anything that spends money, deploys or cannot be undone:** a real model run (it uses a
   plan's limits or a key's budget), a write to the QuickBooks sandbox outside the tests, a deploy, a change to the
   approval limits, a force-push.
7. **No real business's name, anywhere.** The company, vendors, banks and products are generic, and tax ids start
   with 00 ([NOTICE](NOTICE)).
8. **Say whether a number was measured or inferred.** Every number carries its n or its derivation.
9. **Ground a decision in the provider's documentation, then measure it.** Quote the line, with the date read, in
   [docs/decisions/](docs/decisions/).
10. **Plain words.** Hyphens with spaces (" - "), never em dashes; no exclamation marks; third person in the docs.
11. **Smallest change that solves it.** Extend what exists before adding a layer or a dependency.
12. **Check what a push publishes.** Before every push, scan the added lines for key-shaped strings, personal data
    and infrastructure details. `tests/test_public_hygiene.py` fails on planning notes and private names in any
    published file; the infrastructure code stays in a private repository ([docs/DEPLOY.md](docs/DEPLOY.md)).
13. **Commit messages carry the reasoning:** the symptom, the root cause (file and line), why this fix over the
    obvious alternative, the evidence (numbers before and after), and what is still unverified. The product
    reason, never the conversation that led to it.
