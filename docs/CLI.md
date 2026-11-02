# Command contract

Run each command as `python3 <plugin folder>/scripts/ledger.py <command>`. The skill shows how to find the plugin
folder. Every command takes `--json` and then prints one JSON object on stdout.

Exit codes: 0 done, 1 bad input, 2 no data. Errors go to stderr; with `--json`, stdout also gets
`{"error": "...", "code": N}`.

The keys below are stable within version 0.x (REQ-28). New keys can be added. A key is never removed or renamed
without a major version.

| Command | Keys |
|---|---|
| `init` | `config`, `store`, `state`, `machine_id`, `id_patterns`, `commit_ids`, `sync`, `existed`, `python`, `python_version`, `version` |
| `backfill` | `sessions_found`, `recorded`, `skipped`, `failed`, `oldest`, `days` |
| `estimate` | `size`, `kind`, `effort`, `source`, `label`, `n`, `confidence`, `from`, `range50`, `range80`, `narrow`, `items_share`, `overhead`, `guess`, `warnings`, `notes` |
| `done` | `id`, `actual`, `error_first`, `error_last`, `size`, `kind` |
| `report` | `initialized`, `warnings`, `sync`, `sizes`, `attribution`, `left_out_not_measured`, `accuracy`, `sessions`, `open` |
| `calibrate` | `sizes`, `attribution`, `data`, `backtest`, `written` |
| `forget` | `would_delete`, `kept` |

`forget --yes` prints `deleted` in place of `would_delete`. `report --aggregate` leaves out `open` and `sync`.

## Arguments

| Command | Arguments |
|---|---|
| `init` | `--example ID`, `--id-pattern REGEX`, `--confirm-ids`, `--no-commit-ids`, `--sync-remote URL` (`""` turns sync off), `--yes` |
| `backfill` | `--days N` (default 30) |
| `estimate` | `--size S` (required), `--kind K`, `--effort E`, `--guess LO-HI` (for example `400k-1.2M`), `--for ID` |
| `done` | `ID`, `--size S`, `--kind K` |
| `report` | `--aggregate` |
| `calibrate` | none |
| `forget` | `--yes` |

## Units

- Tokens are fresh tokens: output + new input + cache writes. Cache reads aren't included.
- `range50` holds `tokens`, `active_h` and `elapsed_h`, each `[low, high]`. `range80` holds `tokens` only, and it is
  `null` with fewer than 10 tasks.
- `active_h` counts the time between messages that are at most 30 minutes apart. `elapsed_h` runs from the first
  message to the last commit, waits included.
- `error_first` and `error_last` are ln(actual / midpoint), with the midpoint sqrt(low x high) of the 50% token range.
