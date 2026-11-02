# Data: what it reads, what it stores, what it never stores

Status: pre-registration, amended after the independent review, before any code. The code must match this file
(REQ-13, REQ-14, T-42, T-43). If they differ, the code is wrong.

## Summary

- It reads Claude Code's own session files on your machine, and the commit log files of the git folders a session
  worked in. It keeps only numbers, times, model names, effort levels and the task IDs it finds.
- It never stores what you or the agent wrote: no prompts, replies, code, file contents, paths or commit messages.
- Everything stays on your machine. Nothing is sent anywhere unless you set your own git remote for sync.
- You can exclude folders (`ignore_paths`).
- `ledger forget --yes` deletes all of it.

## What it reads

| Source | What it uses | What it ignores |
|---|---|---|
| Claude Code session files (`~/.claude/projects/*/*.jsonl` and each session's `subagents/*.jsonl`; `$CLAUDE_CONFIG_DIR` when set) | per assistant message: time, model name, effort level, token counts (input, output, cache write, cache read), message id; per prompt: only the lines that start with `ITEM:` or `ROLE:`; the working folder of each message (to find its git folder and to apply `ignore_paths`) | prompts, replies, thinking, tool outputs, file contents |
| Tool calls in those files | the command text of Bash tool calls and the prompt text of agent calls, read in memory: whether it's a `git commit`, `git push`, `git merge`, `gh pr` or `gh run` call, and the task IDs in the first 200 characters (and on `ITEM:` lines of agent prompts); only the IDs are kept | everything else in them |
| Session title file next to the transcript | the title, only when `store.title` is on | otherwise not opened |
| Git log files, in the git folders the session worked in (`<gitdir>/logs/HEAD`, and for worktrees the common folder's `logs/refs/heads/*`), only when commit matching is on | reflog entries of type "commit" in the session's time span: time and the first 200 characters of the subject, to find task IDs; the branch name and repo folder name only when those options are on | file contents, diffs, authors, remotes; `git` is never run in these folders |
| Hook input (stdin) | session id, transcript path, working folder, end reason | — |

Commit subjects and command text are read in memory to find task IDs, then dropped.

## Where it stores data

| Folder | Default path | Holds |
|---|---|---|
| Config | `$XDG_CONFIG_HOME/measured-estimates/` (default `~/.config/measured-estimates/`) | `config.json` |
| Store | `$XDG_DATA_HOME/measured-estimates/` (default `~/.local/share/measured-estimates/`) | `ledger/<machine-id>.jsonl` (sessions), `tasks/<machine-id>.jsonl` (task events), `calibration.json` |
| State | `$XDG_STATE_HOME/measured-estimates/` (default `~/.local/state/measured-estimates/`) | Stop-hook stamps (one empty file per session id, deleted after 7 days), `lock`, `status.json`, `seen.idx` (message-key index), `sync/` (the sync clone, only with sync on) |

The same paths are used on macOS and Linux. Files from other machines (through your sync) sit next to your own in
`ledger/` and `tasks/`.

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
| `duplicate_messages` | int | messages skipped because another session already counted them (fork, resume) |
| `subagents` | int | subagent transcripts counted |
| `skipped_lines` | int | lines that couldn't be read |
| `fresh_tokens` | int | output + new input + cache-write tokens, all transcripts |
| `cache_read_tokens` | int | cache-read tokens, all transcripts |
| `by_model_effort` | object | `{model: {effort: {fresh, cache_reads, messages}}}` |
| `tasks` | object | per task ID or process key: `{fresh, by_role: {build, review, fix, lead}, by_model_effort: {model: {effort: fresh}}, active_s, start, end}` |
| `untied` | object | fresh tokens tied to no task: `{_other, _after, _untagged}` |
| `tagged` | object or null | `{ids: [...], role}` from `ITEM:` / `ROLE:` lines (IDs and role word only), and `from` (ISO UTC) when the first tag came after the first prompt |
| `commits` | int | commits this session made with a task ID in the subject (count only) |

Opt-in fields (absent unless turned on in `config.json` → `store`):

| Field | Option | Meaning |
|---|---|---|
| `cwd` | `store.cwd` | working folder, home folder written as `~` |
| `branch` | `store.branch` | git branch at the end of the session (read from `HEAD`, not by running `git`) |
| `repo` | `store.repo` | repo folder name (not its path or remote) |
| `title` | `store.title` | session title, at most 80 characters |

Effort values are stored only when they match `[a-z0-9-]{1,16}`; anything else is `unknown`. Model names are stored
only when they match `[A-Za-z0-9._:/@-]{1,64}`; anything else is `unknown`. Task IDs are stored only when they match a
configured ID pattern, or `process:` + `[a-z0-9-]{1,32}`. Roles are one of `build`, `review`, `fix`, `lead`.

### Task events (`tasks/<machine-id>.jsonl`, append-only, `schema_version: 1`)

One JSON object per event. Events are never edited. The merged view of a task is built on read from the events of all
machines.

| Event | Fields |
|---|---|
| `estimate` | `schema_version, type, id, at, machine, size, kind, effort, guess ([low, high] or null), range50 {tokens, active_h, elapsed_h}, range80 {tokens}, n, source (own or starter), confidence, narrow (bool), calibration_at` |
| `done` | `schema_version, type, id, at, machine, size, kind, actual {fresh, by_role, by_model_effort, dominant_effort, active_h, elapsed_h, start, end, sessions, machines, measured}` |

`kind` is a label you choose (at most 32 chars of `[A-Za-z0-9 _-]`). Merged view: the first estimate is the earliest
`estimate` by `at`; `done_at` is the earliest `done`; the actual is the newest `done`'s; `error_first` and `error_last`
are computed on read.

### `calibration.json` (`schema_version: 1`, rebuilt by `ledger calibrate`, never synced)

Per size and per size + kind: `n`, source, confidence, the 50% and 80% ranges and the median of fresh tokens, active
hours and elapsed hours, p10/p25/p50/p75/p90, ratio to guesses, per-effort counts and medians, the count of tasks left
out as not measured; plus the attribution share and overhead, the backtest summary and the window dates. It holds task
counts, not task IDs.

### `config.json` (`schema_version: 1`)

`machine_id`, `id_patterns` (list of regular expressions), `commit_ids` (false until you confirm), `sizes`,
`idle_cap_min` (30), `stop_every_min` (15), `commit_window_min` (20), `backfill_days` (30), `ignore_paths` (empty),
`store: {cwd, branch, repo, title}` (all `false`), `sync: {remote, branch}` (`remote: null`, branch
`measured-estimates`).

### State files

- Stamp files are empty; their name is the session id and only their time is used. `lock` is empty.
- `status.json`: `{schema_version, warnings: [{at, code}], sync: {at, result, code}}`. Codes are fixed words
  (`format`, `deadline`, `lock`, `sync-auth`, `sync-network`, `sync-conflict`, `sync-timeout`, `sync-refused`), never
  transcript text or git output.
- `seen.idx`: one line per counted message: the first 16 hex chars of the SHA-256 of the message key, and the session
  id that owns it. It holds no message content.
- `sync/`: a git clone of your sync remote, holding the files listed under "Sync".

## What it never stores

- Prompt text, reply text, thinking, tool inputs, tool outputs, file contents, diffs.
- Commit subjects or messages, command lines, file paths (except `cwd` when you opt in, as `~/...`).
- Hostnames, user names, emails, IP addresses, git remote URLs (except your own sync remote in `config.json`).
- Anything from a prompt line other than the matched task IDs and the role word.

## Opt-ins

| Option | Default | Effect |
|---|---|---|
| `store.cwd`, `store.branch`, `store.repo`, `store.title` | off | adds that field to new ledger lines |
| `commit_ids` | off | uses commit subjects and git commands to tie untagged work to tasks |
| `ignore_paths` | empty | sessions in matching folders aren't recorded |
| `sync.remote` | none | turns on sync (below). Use a private repo you control. `http://` remotes are refused |

## Sync (only when you set `sync.remote`)

What goes to the remote: your `ledger/<machine-id>.jsonl` and `tasks/<machine-id>.jsonl`, whole. That means every
field above, including session ids, first and last message times and any opt-in fields you turned on. The times show
when you worked. Nothing else goes there: not the config, not `calibration.json`, not the state files.

How: in the detached child, after a record; at most once per 15 minutes from `Stop`; always at `SessionEnd`. It adds
only your two files by path, pulls with rebase, pushes, retries once, and stops after 60 s. It never asks for a
password (prompts are turned off), and a failure shows in `ledger report`. It then copies the other machines' files
from the sync clone into your store.

## The starter table (`data/starter.json`, shipped in the repo)

Aggregates from the author's own work only: per size bucket with at least 5 tasks, `n`, the 50% range and median of
fresh tokens, active hours and elapsed hours, and the 80% range only when n >= 10; the attribution share and overhead;
one origin line. Values are rounded to 2 significant figures. No task IDs, titles, project or client names, dates of
single tasks, prompts, paths or machine names. CI checks the keys and the counts (REQ-17). Later releases add tasks in
steps of at least 5 per bucket, so a diff of two releases can't show one task's cost.

## Delete

- `python3 <plugin>/scripts/ledger.py forget` lists what it would delete. Add `--yes` to delete the config, store and
  state folders (the message-key index and the sync clone too). Your agent can run it for you: ask it to "forget my
  measured-estimates data".
- It doesn't delete Claude Code's own session files, and it doesn't delete anything in a sync remote; delete that
  repo or branch yourself.
- Uninstalling the plugin stops recording but leaves the data until you run `forget`.

## Sharing

Nothing is shared by this tool. `ledger report --aggregate --json` prints a version of your report without task IDs,
without the open-task list and without any value from fewer than 5 tasks. You can send that by hand if you want to help
improve the starter table. A later version may add an export; it will be opt-in and documented here first.
