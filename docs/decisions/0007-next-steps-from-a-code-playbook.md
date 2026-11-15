# 0007. The suggested next step for a problem bill comes from a playbook in code

**Status:** accepted, 2026-11-14

## Decision

Each problem bill gets a suggested next step in an accounts-payable desk's terms: hold for a corrected bill,
reject a copy already paid, hold a bank change until the vendor confirms it on the number already on file,
approve an overcharge the vendor has already credited (`src/ledger_desk/playbook.py`). A pure function works it
out from what the checks found, the company's records and the credit memos waiting in the visitor's queue. The
person accepts it with one click, through the same decision endpoint and approval rules as the form.

## Sources

- This repository's replay rule ([0005](0005-recorded-real-runs-replayed-through-current-code.md)): recorded
  calls are matched by order, so a new model call would invalidate all 13 recordings.

## Evidence (this repository)

- `tests/test_playbook.py` (34 tests): the step for each of the 8 problem samples and none for the 5 clean ones;
  amounts, quantities and purchase orders named; a credit that settles an overcharge, a smaller one that does
  not, another open problem keeping it on hold; no phone number invented.
- `tests/test_api_runs.py`: with credit memo CM-PKG-0412 read, bill PKG-20817's step becomes an approval against
  it that a clerk can make; a rejected credit does not count.
- A fresh-context review (2026-11-14) found eight wording or logic problems a finance reader would catch (for
  example, a paid bill's own date shown as a payment date); each was fixed test-first.

## Rejected

- **Asking the model for the next step.** It breaks the recordings, and the step decides money, which stays in
  code ([0002](0002-the-model-reads-and-explains-code-checks.md)).
- **Paying a different amount from the bill** (short-paying to the purchase order price). It means a new signed
  entry and a change to the ERP and QuickBooks paths; holding for a corrected bill uses what exists.

## Trade-off

The playbook knows the problems the checks name; an unknown flag gets a generic "hold and look into it".

## What would change it

Steps a real desk takes that the app cannot do yet (record a delivery, set up a vendor) would become actions of
their own, each through the approval rules.
