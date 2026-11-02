# Data: what it reads, what it stores, what it never stores

Status: pre-registration draft, written before any code. The code must match this file (REQ-13, REQ-14, T-42, T-43).
If they differ, the code is wrong.

## Summary

- It reads Claude Code's own session files on your machine, and the commit list of the git folders a session worked
  in. It keeps only numbers, times, model names, effort levels and the task IDs it finds.
- It never stores what you or the agent wrote: no prompts, replies, code, file contents, paths or commit messages.
- Everything stays on your machine. Nothing is sent anywhere unless you set your own git remote for sync.
- `ledger forget --yes` deletes all of it.

## What it reads

| Source | What it uses | What it ignores |
|---|---|---|
| Claude Code session files (`~/.claude/projects/*/*.jsonl` and each session's `subagents/*.jsonl`) | per assistant message: time, model name, effort level, token counts (input, output, cache write, cache read), message id; per prompt: only the lines that start with `ITEM:` or `ROLE:`; per tool call: whether it's a `git commit`, `git push`, `git merge`, `gh pr` or `gh run` call, an agent prompt, and the task IDs in it; the working folder of each message (to find its git repo) | all other text: prompts, replies, tool inputs and outputs, file contents, thinking |
| Session title file next to the transcript | the title, only when `store.title` is on | otherwise not opened |
| Git, in the repos the session worked in | HEAD reflog entries of type "commit" in the session's time span: commit time and subject, to find task IDs; the branch name and repo folder name only when those options are on | file contents, diffs, authors, remotes |
| Hook input (stdin) | session id, transcript path, working folder, end reason | — |

Commit subjects and command text are read in memory to find task IDs, then dropped. Only the matched IDs are kept.

## Where it stores data

| Folder | Default path | Holds |
|---|---|---|
| Config | `$XDG_CONFIG_HOME/measured-estimates/` (default `~/.config/measured-estimates/`) | `config.json` |
| Store | `$XDG_DATA_HOME/measured-estimates/` (default `~/.local/share/measured-estimates/`) | `ledger/<machine-id>.jsonl`, `tasks.json`, `calibration.json` |
| State | `$XDG_STATE_HOME/measured-estimates/` (default `~/.local/state/measured-estimates/`) | Stop-hook time stamps (one empty file per session id), `lock`, `status.json` (adapter warnings) |

The same paths are used on macOS and Linux.

## Every field stored

### Ledger line (`ledger/<machine-id>.jsonl`, one JSON object per session, `schema_version: 1`)

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int | format version of this line |
| `session_id` | string | Claude Code's random session id (to replace the line when the session goes on) |
| `agent` | string | `claude-code` |
| `adapter_version` | string | version of the adapter that read the transcript |
| `machine` | string | your random machine id (16 hex chars, made at `init`; not your hostname) |
| `reason` | string | `session_end`, `stop`, `backfill` or `manual` |
| `recorded_at` | ISO UTC | when the line was written (local clock) |
| `first`, `last` | ISO UTC | first and last message of the session |
| `messages` | int | assistant messages counted |
| `subagents` | int | subagent transcripts counted |
| `skipped_lines` | int | lines that couldn't be read |
| `fresh_tokens` | int | output + new input + cache-write tokens, all transcripts |
| `cache_read_tokens` | int | cache-read tokens, all transcripts |
| `by_model_effort` | object | `{model: {effort: {fresh, cache_reads, messages}}}` |
| `tasks` | object | per task ID or process key: `{fresh, by_role: {build, review, fix, lead}, by_model_effort: {model: {effort: fresh}}, active_s, start, end}` |
| `untied` | object | `{_other, _after}`: fresh tokens tied to no task |
| `tagged` | object or null | `{ids: [...], role}` from `ITEM:` / `ROLE:` lines (IDs and role word only), and `from` (ISO UTC) when the first tag came after the first prompt |
| `commits` | int | commits this session made with a task ID in the subject (count only) |

Opt-in fields (absent unless turned on in `config.json` → `store`):

| Field | Option | Meaning |
|---|---|---|
| `cwd` | `store.cwd` | working folder, home folder written as `~` |
| `branch` | `store.branch` | git branch at the end of the session |
| `repo` | `store.repo` | repo folder name (not its path or remote) |
| `title` | `store.title` | session title, at most 80 characters |

Effort values are stored only when they match `[a-z0-9-]{1,16}`; anything else is stored as `unknown`. Model names are
stored only when they match `[A-Za-z0-9._:/@-]{1,64}`; anything else is `unknown`. Task IDs are stored only when they
match a configured ID pattern or `process:<name>`.

### `tasks.json` (`schema_version: 1`)

`{"schema_version": 1, "tasks": {"<ID>": {...}}}`. Per task:

| Field | Meaning |
|---|---|
| `size`, `kind` | your labels (size on the configured scale; kind is free text you choose, at most 32 chars) |
| `status` | `open` or `done` |
| `estimates` | list, oldest first, never edited: `{at, size, kind, effort, guess: [low, high] or null, tokens_p25_p75, tokens_p10_p90, active_h, elapsed_h, source: own or starter, n, confidence, calibration_at}` |
| `done_at`, `updated_at` | ISO UTC |
| `actual` | `{fresh, by_role, by_model_effort, dominant_effort, active_h, elapsed_h, sessions, machines}` summed from all ledger files |
| `error_first`, `error_last` | ln(actual / midpoint) against the first and the last stored estimate |

### `calibration.json` (`schema_version: 1`)

Rebuilt by `ledger calibrate` from `tasks.json` and the ledger: per size and per size + kind, `n`, source, confidence,
p10/p25/p50/p75/p90 of fresh tokens, active hours and elapsed hours, ratio to guesses, per-effort counts and medians,
the attribution share and overhead, the backtest summary and the window dates. It holds task counts, not task IDs.

### `config.json` (`schema_version: 1`)

`machine_id`, `id_patterns`, `sizes`, `idle_cap_min` (30), `stop_every_min` (15), `commit_window_min` (20),
`backfill_days` (30), `store: {cwd, branch, repo, title}` (all `false`), `sync: {remote, branch}` (`remote: null`).

### State files

Stamp files are empty; their name is the session id and only their time is used. `lock` is empty. `status.json` holds
`{schema_version, warnings: [{at, code, adapter_version}]}` with a fixed warning code, never transcript text.

## What it never stores

- Prompt text, reply text, thinking, tool inputs, tool outputs, file contents, diffs.
- Commit subjects or messages, command lines, file paths (except `cwd` when you opt in, as `~/...`).
- Hostnames, user names, emails, IP addresses, git remote URLs (except your own sync remote in `config.json`).
- Anything from a prompt line other than the matched task IDs and the role word.

## Opt-ins

| Option | Default | Effect |
|---|---|---|
| `store.cwd`, `store.branch`, `store.repo`, `store.title` | off | adds that field to new ledger lines |
| `sync.remote` | none | after each record, a detached process commits your own ledger file to that git remote (branch `sync.branch`, default `measured-estimates`) and pulls the other machines' files. Use a private repo you control. |

## The starter table (`data/starter.json`, shipped in the repo)

Aggregates from the author's own work only: per size bucket `n` and p10/p25/p50/p75/p90 of fresh tokens, active hours
and elapsed hours; the overall ratio of actual to guess; the backtest summary; one origin line. No task IDs, titles,
project or client names, dates of single tasks, prompts, paths or machine names. Every bucket has at least 5 tasks
(CI checks the keys and the counts, REQ-17).

## Delete

- `python3 <plugin>/scripts/ledger.py forget` lists what it would delete. Add `--yes` to delete the config, store and
  state folders. Your agent can run it for you: ask it to "forget my measured-estimates data".
- It doesn't delete Claude Code's own session files, and it doesn't delete anything in a sync remote; delete that
  repo or branch yourself.
- Uninstalling the plugin stops recording but leaves the data until you run `forget`.

## Sharing

Nothing is shared by this tool. If you want to share your numbers (for example to help improve the starter table), send
the output of `ledger report --json` by hand; it holds counts and ranges per size, not task IDs. A later version may add
an export with only aggregates; it will be opt-in and documented here first.
