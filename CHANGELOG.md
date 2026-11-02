# Changelog

Versions follow semantic versioning. Data files carry their own `schema_version` (see `docs/DATA.md`).

## 0.1.0 (2026-11-02)

- First version: Claude Code plugin with a SessionEnd hook (detached recorder) and an async Stop hook.
- `ledger` commands: `init`, `backfill`, `estimate`, `done`, `report`, `calibrate`, `forget`, all with `--json`.
- Size-bucket calibration with the 28-day window rule, small-n widening, kind cells and a leave-one-out backtest.
- Own accuracy over time in `report` (first estimate before the work against the measured cost).
- Optional sync to your own git remote; per-machine files; no prompts.
- Starter table from one developer's measured work (aggregates only).
- Pre-registered evaluation (`docs/EVALUATION.md`) and its results (`docs/RESULTS.md`).
- Schemas version 1 for the ledger line, task events, config, status, calibration and the starter table.

### Known limits

- The pre-registered evaluation is inconclusive: the test tasks ended on 5 days, and the registered minimum is 8.
- The calibrated ranges held the measured cost more often than they claim on this data (50% range 67%, 80% range
  93%). The small-n widening of the ranges stays as it is for now. v0.2 will pre-register widened and unwidened ranges
  as two arms, with coverage per n band, and decide with at least 8 new days of test tasks.
- The starter table comes from one developer's workflow and has no 80% ranges (they need 20 tasks per size).
- Claude Code only; macOS and Linux only.
