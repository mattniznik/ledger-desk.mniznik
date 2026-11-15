# Decision records

Why each part of ledger-desk is built the way it is. Each record states the decision, quotes the provider
documentation it rests on (with the date read), gives the measurement from this repository, and names the options
rejected and what would change the decision. Numbers carry their sample size; anything not measured says so.

| | Decision | Rests on |
|---|---|---|
| [0001](0001-langgraph-workflow-with-an-approval-pause.md) | One bill's run is a LangGraph graph that pauses for the person's decision | LangGraph: interrupts and the restart-the-node rule; the Postgres checkpointer |
| [0002](0002-the-model-reads-and-explains-code-checks.md) | The model reads and explains; code checks and does every sum | Anthropic: citations are incompatible with structured outputs; the eval, measured |
| [0003](0003-signed-approvals-verified-by-the-erp.md) | An approval is an Ed25519 signature that the ERP verifies | cryptography: Ed25519 signing and verification |
| [0004](0004-the-database-enforces-isolation-and-the-audit-log.md) | The database enforces visitor isolation, balanced entries and the audit log | PostgreSQL 17: row security policies |
| [0005](0005-recorded-real-runs-replayed-through-current-code.md) | The demo replays recorded real runs through today's code | Claude Code: environment variables; the recorded runs, measured |
| [0006](0006-quickbooks-sandbox-mirror.md) | Approved bills can be copied to a QuickBooks Online sandbox; the mock ERP stays the system of record | Intuit: QuickBooks Online tokens, Bill, VendorCredit and queries |
| [0007](0007-next-steps-from-a-code-playbook.md) | The suggested next step for a problem bill comes from a playbook in code | This repository's replay rule; a fresh-context review |
| [0008](0008-opus-5-5-at-low-effort.md) | Claude Opus 5.5 at low effort for the recorded runs | Anthropic: effort and pricing; the eval, measured |
| [0009](0009-hosting-on-azure-container-apps.md) | Hosting on Azure: Container Apps, PostgreSQL Flexible Server, Static Web Apps (proposed) | Azure: Container Apps pricing, free services |
| [0010](0010-browser-tests-against-the-real-api.md) | The browser tests run against the real app API in replay mode, not a stand-in | Playwright: webServer; Vite: preview proxy; three bugs it found, measured |

How these are written: [AGENTS.md](../../AGENTS.md), rule 9.
