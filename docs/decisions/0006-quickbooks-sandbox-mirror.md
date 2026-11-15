# 0006. Approved bills can be copied to a QuickBooks Online sandbox; the mock ERP stays the system of record

**Status:** accepted, 2026-11-14

## Decision

After the mock ERP posts an approved bill, an optional step copies it to an Intuit developer sandbox company as a
QuickBooks Bill (a credit memo as a VendorCredit), finding or creating the vendor (`src/ledger_desk/quickbooks.py`,
the `mirror` node in `workflow.py`). It runs only after a posting, never instead of one; a QuickBooks failure is
recorded on the run and leaves the posting alone. It is off unless the API starts with `--mirror-quickbooks`.

## Sources

Intuit's QuickBooks Online docs (read 2026-11-14):

- tokens: access token 3,600 s, refresh token 8,640,000 s; "Always store the latest refresh_token value from the
  most recent API server response" - so every token response is written to `.env.local` before anything else;
- Bill and VendorCredit need `VendorRef` and `Line`; `DocNumber` takes a "maximum of 21 chars", and a duplicate
  "throws an error";
- queries: "Use backslash (\\) to escape special characters like apostrophes (')".

## Evidence (this repository)

- `tests/test_mirror.py`: `test_an_approved_bill_is_mirrored_after_it_posts`,
  `test_a_mirror_failure_leaves_the_run_posted_with_the_error_kept`, `test_a_rejected_bill_is_never_mirrored`,
  `test_without_a_mirror_the_graph_has_no_mirror_step`.
- `tests/test_quickbooks.py`: the client against a fake QuickBooks on `httpx.MockTransport` that holds the rules
  above.
- Against the real sandbox, 2026-11-14: approving a bill already copied found the existing QuickBooks bill and
  wrote nothing new (n=2 approvals of the same bill).

## Rejected

- **QuickBooks as the system of record.** The demo's checks, signatures and audit log need a ledger it controls;
  a sandbox can be reset or unreachable.
- **Copying before the posting.** A QuickBooks bill for something the ERP then refused would be wrong in the
  books people read.

## Trade-off

Find-then-create is not atomic in QuickBooks, so mirrors run one at a time per API process; a second process
could still write a duplicate.

## What would change it

A real customer's QuickBooks would make it the system of record and this app a pre-approval step in front of it.
