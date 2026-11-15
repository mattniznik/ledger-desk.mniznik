# 0001. One bill's run is a LangGraph graph that pauses for the person's decision

**Status:** accepted, 2026-11-14

## Decision

Each bill runs through a LangGraph graph (`src/ledger_desk/workflow.py`): read, check, suggest an account (bills
with no purchase order), investigate (problem bills only), propose the entry, wait for approval, post, and copy to
QuickBooks when that is switched on. The wait is LangGraph's `interrupt()`; the person's decision resumes it with
`Command(resume=decision)` on the same thread. State is kept by LangGraph's Postgres checkpointer, so a bill can
wait for hours, across restarts of the API.

## Sources

- LangGraph, interrupts (read 2026-11-14): when a run resumes, "the runtime restarts the entire node from the
  beginning", and side effects belong after the interrupt or in a separate node.

## Evidence (this repository)

- `tests/test_workflow.py`: `test_a_run_paused_for_approval_survives_a_restart_with_postgres_checkpoints`,
  `test_resuming_after_approval_posts_once_even_if_the_step_re_runs`, `test_a_rejection_posts_nothing`,
  `test_a_refusal_sends_the_invoice_to_manual_entry_and_never_pauses`.
- `tests/test_api_runs.py`: `test_run_status_survives_a_restart_of_the_api`.
- Because a node restarts from its beginning, posting is its own node, and its idempotency key is built from the
  invoice and the approval signature: a re-run returns the entry the ERP already has instead of writing a second
  one.

## Rejected

- **A hand-written loop with no checkpointer.** Fine for a request that ends in seconds; a bill that waits for a
  controller overnight needs its state stored and resumed, which the checkpointer already does.
- **A queue and a status column of its own.** It would re-build pause, resume and replay by hand, with more code
  to test.

## Trade-off

A framework dependency, and its restart-the-node rule shapes the graph: anything with a side effect sits after the
pause, in its own node.

## What would change it

Many bills in flight at once, or steps that run on different machines, would call for a durable job system; one
bill at a time per visitor does not.
