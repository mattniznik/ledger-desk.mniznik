# 0005. The demo replays recorded real runs through today's code

**Status:** accepted, 2026-11-14

## Decision

Every model call a run makes is recorded once from a real run of Claude (`replays/`), through Claude Code on a
subscription login (`src/ledger_desk/subscription.py`). The demo and the tests then replay those replies through
the current reading, checks, workflow and API (`runner.py` ReplayModel). A visitor sees real model output for
nothing per visit, and a replay stops with an error the moment today's code asks the model something the
recording does not hold, instead of inventing an answer.

## Sources

- Claude Code, environment variables (read 2026-11-14): a set `ANTHROPIC_API_KEY` "is used instead of your ...
  subscription even if you are logged in" - so the subscription adapter removes it, and `ANTHROPIC_AUTH_TOKEN`,
  from its child process.

## Evidence (this repository)

- The recorded run in `replays/claude-opus-5-5-low-run2/` (2026-11-14, one run): 13 of 13 bills end as expected;
  40 model calls; 207.8 s in all (mean 16.0 s, median 18.8 s a bill); $0.99 at API list prices (mean $0.076,
  median $0.082 a bill), and $0 spent because it ran on a subscription.
- `tests/test_runner.py`: `test_a_replay_reproduces_the_run_without_a_model`,
  `test_a_replay_stops_when_the_code_asks_something_else`, `test_a_replay_that_runs_out_stops_too`.
- `tests/test_api_runs.py`: `test_a_recording_that_no_longer_matches_fails_the_run_and_says_so_in_the_audit`.

## Rejected

- **A scripted fake for the demo.** It would show answers no model gave.
- **A live model for every visitor.** A per-visit cost and a key to protect, for answers the recording already
  shows; a live run is planned only behind limits and a budget.

## Trade-off

Replays match recorded calls by their order, not their wording: a change that adds or reorders model calls needs
a new recording ([0007](0007-next-steps-from-a-code-playbook.md) kept the next steps out of the model for this
reason).

## What would change it

A live mode with its own key, limits and budget; the replays would stay as the default and as the test fixtures.
