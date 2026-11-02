# Changelog

Versions follow semantic versioning. Data files carry their own `schema_version` (see `docs/DATA.md`).

## 0.1.0 (unreleased)

- First version: Claude Code plugin with a SessionEnd hook (detached recorder) and an async Stop hook.
- `ledger` commands: `init`, `backfill`, `estimate`, `done`, `report`, `calibrate`, `forget`, all with `--json`.
- Size-bucket calibration with the 28-day window rule, small-n widening, kind cells and a leave-one-out backtest.
- Own accuracy over time in `report` (first estimate before the work against the measured cost).
- Optional sync to your own git remote; per-machine files; no prompts.
- Starter table from one developer's measured work (aggregates only).
- Pre-registered evaluation (`docs/EVALUATION.md`) and its results (`docs/RESULTS.md`).
- Schemas version 1 for the ledger line, task events, config, status, calibration and the starter table.
