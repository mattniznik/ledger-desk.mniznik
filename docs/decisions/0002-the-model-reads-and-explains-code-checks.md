# 0002. The model reads and explains; code checks and does every sum

**Status:** accepted, 2026-11-14

## Decision

Claude does three jobs: it reads a bill into fields, it suggests an account when there is no purchase order, and
it investigates a problem bill (read-only lookups, an explanation, a draft email). Everything that decides money
is plain code: the arithmetic, the match against the purchase order and the delivery, duplicates, bank details,
unusual amounts (`src/ledger_desk/rules.py`), the account check (`accounts.py`), who may approve (`authority.py`)
and the suggested next step (`playbook.py`, [0007](0007-next-steps-from-a-code-playbook.md)).

Each field Claude reads comes back with the text it read it from, and code checks that the text is in the PDF's
text layer and holds the value (`reading.py`). That check is done in code rather than with the API's citations.

## Sources

- Anthropic, citations (read 2026-11-14): "Citations cannot be used together with structured outputs. If you
  enable citations on any user-provided document ... and also include the `output_config.format` parameter ...
  the API returns a 400 error."

## Evidence (this repository)

- `tests/test_rules.py`: the rules alone, on each sample's ground truth, give exactly the expected flags for all
  13 samples, with no model.
- `tests/test_reading.py`: `test_a_value_that_is_not_in_the_document_fails_its_source_check`,
  `test_a_photo_has_no_text_layer_so_its_sources_are_marked_not_checked`.
- `tests/test_accounts.py`: an account outside the chart, or one that does not fit the vendor, is refused and the
  vendor's usual account proposed instead.
- One eval run on Claude Opus 5.5 at low effort (2026-11-14): 504 of 504 fields read correctly over 50 bills,
  21 of 21 accounts suggested correctly, 49 of 50 bills ended in the right state (the miss is a known limit of the
  phrase check, not a reading error).

## Rejected

- **Asking the model whether a bill is right.** Its answer could not be tested case by case, and a confident
  wrong "approve" would reach the books.
- **Citations for the source check.** A 400 with structured outputs, as quoted above; the fields need the schema.

## Trade-off

The checks only know what they were written to look for. A new kind of problem needs a new rule and its tests;
the model can describe it, not stop it.

## What would change it

A kind of bill problem that needs judgement no rule can encode would become a suggestion for a person, never a
decision.
