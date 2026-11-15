# 0008. Claude Opus 5.5 at low effort for the recorded runs

**Status:** accepted for the recorded runs, 2026-11-14; open for a live demo

## Decision

The recorded runs and the eval use `claude-opus-5-5` with effort `low` (`src/ledger_desk/subscription.py`,
`runner.py`). Sonnet 5.5 and Haiku 5.5 are priced in `model.py` and will be compared on the same eval before a
live demo picks its model.

## Sources

Anthropic docs (read 2026-11-14 unless noted):

- Effort: "`low` - Most efficient. Significant token savings with some capability reduction", typical use "Simpler
  tasks that need the best speed and lowest costs"; Claude Opus 5.5's default is `medium`; effort is set with
  `output_config.effort`. "Lower effort also means fewer and terser tool calls."
- Pricing (read 2026-11-12), USD per million tokens, input / output: Opus 5.5 $4 / $20, Sonnet 5.5 $2 / $10,
  Haiku 5.5 $0.10 / $0.50 (`model.py` PRICES).

## Evidence (this repository)

- Eval, one run on Opus 5.5 at low effort (2026-11-14), 50 bills: 49 of 50 end results right, 504 of 504 fields,
  21 of 21 accounts, 50 of 50 safe; $3.57 at API list prices ($0.071 a bill), 15.8 s a bill. The hard tier (10
  bills: blur, skew, low resolution, creases, two pages): 10 of 10, 170 of 170 fields, $0.080 and 16.1 s a bill.
- The eval is at its ceiling for this model, so it cannot yet show whether a cheaper model holds; the hard tier
  was added for that and is at its ceiling too (one run each).

## Rejected

- **A higher effort.** Nothing failed at `low` that more effort would fix (the one miss is the phrase check, in
  code); more effort costs more output tokens.
- **Haiku 5.5 untested.** It would be the cheapest; it waits for the comparison run.

## Trade-off

The strongest model at its cheapest setting: a strong reader, at a price a cheaper model might match.

## What would change it

The comparison run: if Sonnet 5.5 or Haiku 5.5 matches these results on both tiers, the live demo uses the cheaper
one.
