# 0004. The database enforces visitor isolation, balanced entries and the audit log

**Status:** accepted, 2026-11-14

## Decision

What must never happen is refused by Postgres itself, not only by the API's code (`migrations/`):

- each visitor's rows are kept apart by row-level security: every request runs as a restricted role with the
  visitor's session set for that transaction only;
- an unbalanced journal entry is rejected at commit;
- the audit log is insert-only for every role and hash-chained, so an edited row is found;
- the agent's role cannot write an approval ([0003](0003-signed-approvals-verified-by-the-erp.md)).

## Sources

- PostgreSQL 17, row security policies (read 2026-11-14): "If no policy exists for the table, a default-deny
  policy is used, meaning that no rows are visible or can be modified." "Superusers and roles with the
  `BYPASSRLS` attribute always bypass the row security system", and "Table owners normally bypass row security as
  well" - which is why the API switches to its restricted role before anything else runs.

## Evidence (this repository)

- `tests/test_db.py`: `test_one_session_cannot_read_or_write_anothers_invoices`,
  `test_an_unbalanced_journal_entry_is_rejected_at_commit`, `test_the_audit_log_cannot_be_updated_or_deleted`,
  `test_verify_finds_a_row_edited_behind_the_apps_back`, `test_the_agent_role_cannot_insert_an_approval`.
- `tests/test_api.py`: `test_one_visitor_never_sees_anothers_audit_rows`,
  `test_the_api_runs_as_ledger_app_with_the_session_set_only_inside_its_transaction`.

## Rejected

- **Filtering by session in every query.** One forgotten `WHERE` would show another visitor's bills; with
  row-level security the database refuses even then.
- **A log file for the audit trail.** It can be edited without a trace; a hash chain shows the first changed row.

## Trade-off

Every connection must switch role and set the session first, and the superuser would bypass all of it, so the
API never runs as the superuser.

## What would change it

Real accounts with logins would replace the session id with a user id; the policies would stay.
