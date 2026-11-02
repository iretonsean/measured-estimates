# Requirements

Version 0.2 (pre-registration, amended after the independent review, before any code and before any evaluation run).
Each requirement has an ID (REQ-xx), a statement, and one or more acceptance tests (T-xx). The traceability table at
the end maps every requirement to its tests and every test to its requirement. A requirement is met only when all of
its tests pass. IDs are stable: the amendment kept every earlier ID and added new ones (REQ-43, T-114 to T-140).

Words: **must** = required for v0.1.0. **Session** = one Claude Code conversation (its main transcript and its
subagent transcripts). **Task** = a unit of work with an ID that the person chooses (an issue, a ticket, a backlog
item). **Fresh tokens** = output tokens + new input tokens + cache-write tokens. Cache reads are counted apart and
aren't part of fresh tokens. **Store**, **config** and **state** folders: see `docs/DATA.md`. **Midpoint** of a range
`[low, high]` = sqrt(low x high) (the geometric midpoint), everywhere. **Error** of an estimate = |ln(actual /
midpoint)|. **50% range** and **80% range**: the ranges that `estimate` gives (REQ-26). **Small cell**: a value
computed from fewer than 5 tasks.

Test types: **U** unit test (unittest, invented fixtures), **I** integration test (the real scripts on a scratch home
folder), **C** CI check, **X** install test on Linux and macOS, **R** inspection by a reviewer, **E** evaluation on
real data (`docs/EVALUATION.md`).

## 1. Recording

**REQ-01 Hook events.** The plugin must record on `SessionEnd` and on `Stop`. The `SessionEnd` hook process must read
its input, start a detached child process (new session, stdio to `/dev/null`) that does the record, and exit. The
`Stop` hook must be declared `async: true`; it records at most once per session in each `stop_every_min` minutes
(default 15), so a session that's killed is still on record.
- T-01 (I) A `SessionEnd` hook input writes one ledger line for the session (after the child ends).
- T-02 (U) Two `Stop` calls within 15 minutes write once; a call after 15 minutes writes again.
- T-03 (R) `hooks/hooks.json` declares `SessionEnd` (timeout 5 s as a backstop) and `Stop` (`async: true`).

**REQ-02 Never block or slow a session.** The hook process must exit with status 0 on every error, must print nothing
to stdout, and must return within 200 ms (p95 over 20 runs on the CI runner). The child must stop at its own deadline
(30 s); at the deadline it writes nothing, keeps the old line, and writes warning code `deadline` to `status.json`. The
recorder must never wait for a network call. A missing or old Python (below 3.9) must not cause a hook error or any
dialog.
- T-04 (U) Malformed hook input, a missing transcript, a read-only store and an exception inside the parser each give
  exit 0 and no stdout.
- T-05 (U) With the deadline injected as 0.1 s, the child stops, writes nothing new, and keeps the old line.
- T-114 (C) The hook process returns in <= 200 ms (p95 of 20 runs) with a 5,000-message fixture.
- T-116 (U) After a deadline stop, `status.json` holds `deadline` and `report` shows it.
- T-148 (U) The wrapper skips relative `PATH` folders and any `python3` below 3.9 (it tries the next one).
- T-06 (U) The hook wrapper exits 0 when no `python3` is found.
- T-07 (U) Under Python below 3.9 (version check injected) the recorder exits 0 at once.
- T-115 (U) macOS guard: when the system reports Darwin and `xcode-select -p` fails, the wrapper never runs the system
  stub `/usr/bin/python3` (path injectable for the test); it uses another `python3` on `PATH` or the usual install
  folders, else exits 0.

**REQ-03 Token counts.** For each assistant message the recorder must count fresh tokens and cache reads from the
message's usage block. A message key is the message id, else the request id, else the line uuid. Inside one transcript,
the last line for a key wins (streamed parts repeat the usage block). A key counts once per machine across all
transcripts: the recorder keeps an index of truncated SHA-256 hashes of keys with the session that owns each one; a
message whose key belongs to another session is skipped and counted in `duplicate_messages` (forked and resumed
sessions copy history). Synthetic messages (model name in angle brackets) must not count.
- T-08 (U) A golden transcript gives the expected fresh tokens and cache reads, exactly.
- T-09 (U) A message repeated on three lines counts once.
- T-10 (U) A `<synthetic>` message counts zero.
- T-117 (U) Two sessions that share 10 message keys: the second counts them as `duplicate_messages: 10`, and the total
  over both lines counts each key once.
- T-118 (X) A real `--fork-session` in the test home doesn't double the totals.
- T-119 (U) Repeated lines with different `output_tokens`: the last line's value counts.

**REQ-04 Model and effort split.** Every ledger line must split fresh tokens, cache reads and message counts by model
and by effort level. The effort of a message is its `perTurnEffort` field, else its `effort` field, else `unknown`.
Each task share must carry the same model x effort split. A task's **dominant effort** is the known effort with the
most fresh tokens over its sessions (ties go to the alphabetically lower name), when known efforts hold at least half
of its fresh tokens; else `unknown`.
- T-11 (U) A transcript with `high` and `medium` turns on two models gives the four expected cells.
- T-12 (U) A message with no effort field counts under `unknown`.
- T-13 (U) `perTurnEffort` wins over `effort` when both are present and differ.
- T-14 (U) Dominant effort: largest known share wins; a tie goes to the lower name; known share below 0.5 gives
  `unknown`.

**REQ-05 Subagents.** The record must include the session's subagent transcripts. A subagent without its own tag
takes the tag of its session.
- T-15 (U) A session with two subagent files sums all three transcripts.
- T-16 (U) An untagged subagent of a tagged session counts for the session's task.

**REQ-06 Tag rule.** A line `ITEM: <ids>` in the first prompt of a transcript must tie all of that transcript's fresh
tokens to those IDs, split equally. An `ITEM:` line in a later prompt must apply from that prompt on (it changes the
task of a tagged transcript and tags the rest of an untagged one). `ITEM: process:<name>` must tie tokens to a process
key; `<name>` must match `[a-z0-9-]{1,32}`. An optional `ROLE:` line must set the role; only `build`, `review`, `fix`
and `lead` count (default `build`); a later `ROLE:` line changes it from that prompt on. Only the first 200 characters
after `ITEM:` are read. Only IDs that match the configured ID patterns or the process pattern count.
- T-17 (U) First-prompt tag with two IDs splits 50/50.
- T-18 (U) A later `ITEM:` line moves the tokens after it to the new ID.
- T-19 (U) A later `ITEM:` line in an untagged transcript tags only the rest of it.
- T-20 (U) `ITEM: process:review` counts under `process:review`, not under a task.
- T-21 (U) `ROLE: review` in the first prompt and `ROLE: fix` in a later prompt split the roles at that time.
- T-22 (U) Text after `ITEM:` that matches no pattern ties nothing.
- T-120 (U) `process:` with a name of 33 chars or with spaces ties nothing; `ROLE: boss` is ignored; an ID after
  character 200 isn't read.

**REQ-07 Commit attribution (untagged work, opt-in).** Commit matching must run only when the person has confirmed
their ID pattern (`commit_ids: true` in the config). Then, in an untagged transcript, a message must count for the next
commit that the same transcript made itself (a `git commit` tool call followed by a commit in the reflog of a folder
the transcript worked in, within `commit_window_min`, default 20 minutes), when the first 200 characters of that
commit's subject hold a task ID. Only commits made on this machine count (reflog entries of type "commit"). The
recorder must read reflog files directly (`<gitdir>/logs/HEAD`, and for worktrees the common dir's
`logs/refs/heads/*`); it must not run `git` in folders named by a transcript. Tokens that no commit claims must go to
the tasks the transcript touched at both ends of that stretch (IDs in its own commit subjects, in `git push`,
`git merge`, `gh pr` and `gh run` commands and the branch names in them, and on the `ITEM:` lines of prompts it gave to
agents), role `lead`. Tokens with no task anywhere must go to `_other` (before a commit without an ID), `_after`
(after the last commit) or, when commit matching is off, `_untagged`. `ITEM:` lines in prompts to agents count as
touches even when commit matching is off.
- T-23 (I) A scratch git repo with two commits (`ABC-1: ...`, `ABC-2: ...`) splits the tokens before each commit.
- T-24 (U) A commit made by another transcript doesn't count for this one.
- T-25 (I) A commit pulled from a remote (no "commit" reflog entry) doesn't count.
- T-26 (U) Lead touches: a message between a `git push` naming `ABC-3` and a prompt with `ITEM: ABC-4` splits between
  both, role `lead`.
- T-27 (U) Tokens after the last commit with no touch go to `_after`; before a commit without an ID to `_other`;
  with `commit_ids: false` untagged tokens go to `_untagged`.
- T-123 (U) The reflog reader parses `logs/HEAD` and the common dir's branch logs of a worktree, and starts no
  subprocess (`subprocess` patched to raise).

**REQ-08 Task ID patterns.** There must be no broad default that ties work by itself. `ledger init` must ask for one
example task ID and build a prefix-anchored pattern from it (`ENG-42` gives `ENG-` + 1 to 6 digits). Presets:
`PREFIX-123`, `#123` (GitHub issues), `K42` (one capital letter + 2 to 4 digits). Without an answer (`init --yes`), the
pattern is any `ABC-123` form (2 to 10 capitals or digits, starting with a capital), minus a stoplist (UTF, SHA, ISO,
RFC, AES, GPT, HTTP, TLS, CVE, UTC, ES, MD, PEP), on `ITEM:` lines only; commit matching stays off until the person
confirms a pattern (`init --confirm-ids` or the question in `init`). `init` must refuse a pattern that doesn't compile,
that matches an empty string, or that takes more than 50 ms on a 10 kB adversarial string.
- T-28 (U) The `init --yes` pattern matches `ENG-42` and `ABC-123`; it doesn't match `UTF-8`, `SHA-256`, `ISO-8601`,
  `GPT-4`, `AES-256` or plain numbers.
- T-29 (U) A custom pattern from the config replaces the default.
- T-30 (U) An invalid or empty-matching pattern is refused with a message; the config doesn't change.
- T-121 (U) A catastrophic-backtracking pattern is refused (time limit injected).
- T-122 (U) `init --example ENG-42` builds the prefix pattern; `--example '#12'` the issue preset; commit matching is
  off until `--confirm-ids`.

**REQ-09 Time.** Active time must be the sum of the gaps between consecutive messages that are at most `idle_cap_min`
(default 30) minutes; a longer gap counts zero. Elapsed time for a task must run from its first message to its last
commit (or last message when tagged), over all of its sessions, waits included. A `lead` share must add to active time
but must not move a task's start or end. All times must come from transcript timestamps (UTC), never the local clock.
A negative gap must count zero.
- T-31 (U) Gaps of 10, 40 and 20 minutes give 30 minutes active.
- T-32 (U) A lead share adds active time but doesn't change start or end.
- T-33 (U) Out-of-order timestamps don't give negative time.
- T-34 (U) `idle_cap_min` from the config changes the result.

**REQ-10 One line per session.** A resumed or re-recorded session must replace its own line (key: session id), never
add a second one. Each machine must write only its own files.
- T-35 (U) Recording the same session twice leaves one line with the newer counts.
- T-36 (U) Lines of other sessions in the file stay byte-identical.

**REQ-11 Concurrency and safe writes.** Two recorders that finish at the same time must not lose a line. The recorder
takes an exclusive `flock` on the state folder's lock file with non-blocking retries until its deadline (the lock
releases when a process dies); when the deadline passes, it writes nothing and records warning `lock`. Every write must
go to a temporary file in the same folder, then rename, so a crash or a full disk never leaves a half-written file.
- T-37 (I) Two recorder processes started together for two sessions leave two lines.
- T-38 (U) A write that fails (injected `OSError` on write) leaves the old file unchanged.
- T-124 (U) A held lock makes the recorder retry, then stop at the deadline with warning `lock`, exit 0.

**REQ-12 Partial and changed transcripts.** The adapter must read transcripts line by line (never the whole file at
once), skip lines it can't parse and count them (`skipped_lines`). When a transcript has lines but no message with a
usage block, the recorder must write warning code `format` to `status.json`; `ledger report` and `ledger estimate`
must show it. Stamp files older than 7 days must be deleted on each record.
- T-39 (U) A transcript with a truncated last line records the rest and `skipped_lines: 1`.
- T-40 (U) A transcript in an unknown format writes the warning and `report` shows it.
- T-41 (U) The golden sample transcript still parses (a format change in Claude Code fails this test first).
- T-143 (U) A line nested 5,000 levels deep and a usage value of `Infinity` are skipped or counted as 0; the session is
  still recorded. Any other failure in the child writes warning code `error`, and `report` shows it.
- T-136 (U) A stamp file 8 days old is deleted; one 1 day old stays.
- T-137 (R) The adapter iterates over lines; no `read()` of a whole transcript.

## 2. Privacy

**REQ-13 Data minimization.** By default a ledger line must hold only the fields listed in `docs/DATA.md`: counts,
times, model names, effort levels, task IDs, process keys, roles, the random machine id and the session id. It must
never hold prompt text, reply text, tool inputs or outputs, code, file contents, file paths, commit subjects,
hostnames or user names. From an `ITEM:` or `ROLE:` line it must keep only the matched IDs and the role word.
- T-42 (U) A fixture full of canary strings (a fake secret, a path, a commit subject, a prompt sentence, a hostname)
  gives ledger lines, task events and `calibration.json` that contain none of them.
- T-43 (U) The ledger line's keys are exactly the keys allowed by the schema (no extra key).
- T-142 (I) After `init`, a record and a sync, every folder in the config, store and state folders (the sync clone
  too) is user-only (0700) and every file 0600 (final review: the hooks and the CLI set `umask 077`).

**REQ-14 Opt-in fields.** The working folder (with the home folder written as `~`), git branch, repo folder name and
session title must be stored only when the person turns each one on in the config. Default: all off.
- T-44 (U) Default config: the four fields are absent. Each one turned on: only that one is present.

**REQ-43 Ignored folders.** The config must accept `ignore_paths` (glob patterns; `~` allowed). A session whose working
folder matches one of them must not be recorded, by the hooks or by `backfill`.
- T-125 (U) A session in `~/work/client-x` with `ignore_paths: ["~/work/client-*"]` writes nothing; others still do.
- T-146 (U) `init --ignore <glob>` (repeatable) adds to `ignore_paths`; a second `init` keeps them.

**REQ-15 No network by default; safe sync.** The recorder and every `ledger` command must make no network connection
unless the person sets a sync remote. With a sync remote, sync must:
- run in the detached child, never in the hook process; at most once per 15 minutes from `Stop`, always at
  `SessionEnd`;
- use its own clone in the state folder, never the store;
- set `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, `GIT_SSH_COMMAND="ssh -o BatchMode=yes"`,
  `SSH_ASKPASS_REQUIRE=never` and unset `GIT_ASKPASS` and `SSH_ASKPASS`, so no password or keychain prompt can show;
- take a non-blocking lock on the sync clone and skip when another sync holds it;
- stop after 60 s in total;
- add only this machine's two files by path (never `git add -A`); pull with rebase, push, retry once, then stop;
- refuse `http://` remotes;
- write the result (time, ok or fail, a fixed code) to `status.json`; `report` shows "last sync failed at ..." on a
  failure.
- T-45 (U) With no remote, recording and every command run with `socket.socket` patched to raise, and pass.
- T-46 (I) With a local bare repo as the remote, a record arrives there; the hook process returns before the push ends
  (push delayed by a fake `git` wrapper); the sync environment holds the variables above.
- T-47 (R) No code path reads a remote URL from anywhere but the config file.
- T-126 (I) An `http://` remote is refused; a failing push writes a `fail` result and `report` shows it; the commit in
  the sync clone holds only this machine's files.
- T-127 (U) A second sync while the sync lock is held is skipped.
- T-141 (I) A remote whose branch holds links (`ledger/<own id>.jsonl` to a file outside the store, another machine's
  file to a secret file, `ledger/` itself to a folder) can't write or read outside the store: the sync clone checks
  links out as plain files (`core.symlinks false`), the own file is written by replace, linked files and folders are
  skipped, files are opened without following links.
- T-144 (I) Records from another machine are checked on read (`store.valid_line`, `store.valid_event`): bad IDs, text
  in number fields and a bad schema version are skipped; no command fails and no foreign text reaches the agent.

**REQ-16 Delete.** `ledger forget --yes` must delete the store, the config and the state folders (ledger files, task
events, calibration, stamps, lock, status, the message-key index and the sync clone), and must print what it deleted.
Without `--yes` it must only list what it would delete. It must never touch Claude Code's own transcripts or a sync
remote.
- T-48 (I) After `forget --yes` the three folders are gone; transcripts are unchanged.
- T-49 (U) `forget` without `--yes` deletes nothing.
- T-145 (U) After `forget --yes`, no hook and no `backfill` records until `init` runs again; only an empty marker file
  stays in the state folder, and the output says so.

**REQ-17 Small cells and the starter table.** Everywhere a number is shown or shipped (`report`, `report --aggregate`,
`estimate`, `starter.json`, `results.json`, `docs/RESULTS.md`, the README), a value computed from fewer than 5 tasks
must show only its count; p10 and p90 must show only when n >= 10. `data/starter.json` must hold only these keys:
schema version, origin line, units, the attribution share and overhead, and per size bucket `n`, the 50% range, the 80%
range (only when n >= 10; the shipped starter uses n >= 20, because the ends of an 80% range from fewer tasks are near
single tasks) and the median of fresh tokens, active hours and elapsed hours. Values are rounded to 2
significant figures. Sizes with fewer than 5 tasks are left out (not merged). No IDs, titles, names, dates of single
tasks, paths or free text other than the origin line.
- T-50 (C) A CI script checks the keys of `starter.json` against an allow list and checks n >= 5 per bucket and
  n >= 10 for any 80% range or p10/p90.
- T-51 (C) The same script fails on a planted extra key and on a bucket with n = 4 (self-test).
- T-135 (C) The same checker reads `results.json` and fails on any value cell with n < 5 (self-test with a planted
  n = 1 row).

**REQ-18 Repo hygiene.** The public repo must hold no secrets, emails other than the GitHub noreply address, home paths,
private IP addresses, hostnames or real transcript content. A generic scan in CI must check every push: key formats
(`sk-ant-`, `sk-`, `ghp_`, `github_pat_`, `gho_`, `AKIA` + 16, `xox[abp]-`, `-----BEGIN`), emails other than
`*@users.noreply.github.com`, `/home/<name>` and `/Users/<name>` paths, private IPv4 ranges, `.local` hostnames, and
`token` followed by `:` or `=` and a quoted 16+ char value. The scan's self-test builds its canary strings at run time
from parts, so no canary is a literal in the repo. Any list of private names (the author's projects, accounts or ID
forms) must never be in the repo; the lead runs that private list from outside the repo before each push.
- T-52 (C) The CI scan passes on the repo.
- T-53 (C) The scan fails on canaries built at run time (self-test in a temporary folder).
- T-54 (R) The lead runs the private list on `git diff --cached` before each commit and on `git log -p` before the
  first push.

## 3. Commands (CLI contract)

All commands are `python3 scripts/ledger.py <command>`. Each must accept `--json` and then print one JSON object to
stdout. Exit codes: 0 done, 1 bad input, 2 no data. Errors go to stderr.

**REQ-19 init.** `ledger init` must create the config (random machine id from `secrets.token_hex(8)`, ID pattern
(REQ-08), sync off) and the folders, ask at most three short questions (one example task ID; may commit subjects be
used, yes/no; sync remote, default none), accept every answer as a flag for agents (`--example`, `--id-pattern`,
`--confirm-ids`, `--sync-remote`, `--yes`), print the Python it found and its version, and explain how to get
Python 3.9+ when none is found. A second run must keep the machine id.
- T-55 (I) `init --yes` on a scratch home writes a valid config and the folders.
- T-56 (U) A second `init` keeps the machine id and other settings unless a flag changes them.
- T-57 (U) The machine id is 16 hex chars and isn't derived from the hostname.

**REQ-20 backfill.** `ledger backfill [--days N]` (default 30) must record, in time order, every session transcript of
the last N days that Claude Code still keeps, with the same rules as the hook (including `ignore_paths` and the
message-key index), and must be safe to run again (no duplicate lines).
- T-58 (I) Backfill of three fixture sessions writes three lines; a second run changes nothing.
- T-59 (U) Sessions older than N days are skipped.

**REQ-21 estimate.** `ledger estimate --size <S> [--kind <K>] [--effort <E>] [--guess LO-HI] [--for <ID>]` must print
ranges, never a single number: the 50% range and the 80% range of tokens (REQ-26), the 50% range of active hours and
of elapsed hours, `n`, the source (`own` or `starter`), a confidence word, the share of tokens tied to tasks, the
overhead factor, and any warning. With `--for` it must append an `estimate` event (time, inputs, outputs, the
calibration time) to this machine's task events.
- T-60 (U) The output has every field above; no field is a lone point estimate.
- T-61 (U) `--for ABC-1` stores the estimate; `--json` output equals the stored event's estimate part.
- T-62 (U) An unknown size is refused with the list of sizes (exit 1).
- T-147 (U) `--effort` accepts only `[a-z0-9-]{1,16}`; other text is refused (exit 1) and nothing is stored.

**REQ-22 Own data replaces starter, size by size.** For a size with at least 5 of the person's own measured finished
tasks, `estimate` must use only own data; with fewer, the starter row labelled `starter, not your data` with the
starter's n; when the starter has no row for the size, a row scaled from the nearest size (label `rough`).
- T-63 (U) 4 own tasks of size S: source `starter`. 5 own tasks: source `own`.
- T-64 (U) Own data of size S doesn't change the source of size M.

**REQ-23 Effort ranges.** `estimate --effort <E>` must give an effort-specific range only when the size has at least 5
own measured finished tasks with that dominant effort; else it must give the size range and a note that says why.
- T-65 (U) 5 tasks at `high`: effort range. 4 tasks: size range + note.

**REQ-24 Estimates are append-only (hindsight guard).** An estimate event is never changed. A new `estimate --for` on
the same task appends a new event. The **first estimate** of a task is the earliest by time over all machines' event
files. `done` must compare the actual with the first estimate and also report the last one.
- T-66 (U) Two estimates for one task: both kept in order; the first is unchanged.
- T-67 (U) `done` reports error against the first and the last estimate.

**REQ-25 done.** `ledger done <ID> [--size S] [--kind K]` must sum the task's measured use over every ledger file in
the store (all machines), and append a `done` event with the actual: fresh tokens, by role, by model x effort, dominant
effort, active hours, elapsed hours, sessions, and `measured`. `measured` is true only when build + review + fix fresh
tokens > 0 and the lead share is at most 0.5 of the task's fresh tokens; else the actual likely records missing
attribution, not cost. It must compare the actual with the stored estimates and run the calibration again. `done` on a
task with no ledger data must say so (exit 2) and append nothing.
- T-68 (U) Two machine files with shares of `ABC-1` sum into one actual.
- T-69 (U) `done` without data exits 2 and appends nothing.
- T-70 (U) `done` twice: the merged view keeps the first `done_at`, the newest actual and `updated_at`.
- T-129 (U) A task whose tokens are 80% lead share gets `measured: false`; `calibrate` leaves it out and counts it;
  `report` shows the count.

**REQ-26 calibrate.** `ledger calibrate` must turn measured finished tasks into `calibration.json` with the size-bucket
method:
- Sizes on one scale (default `XS, S, M, L, XL`; ranges such as `S-M` are allowed and sit between).
- Window rule: per size, the tasks of the last 28 days before the newest finished task when there are at least 5;
  else all tasks of that size when there are at least 3; else the size is scaled from the nearest measured size by the
  ratio of the median guess midpoints of the two sizes (by 2 per scale step when guesses are missing).
- Small-n widening: for a nominal level L (0.5 and 0.8) and n tasks, the range uses the quantile levels
  0.5 - L(n+1)/(2(n-1)) and 0.5 + L(n+1)/(2(n-1)), clipped to [0, 1]. (For a new task from the same distribution, the
  expected coverage of the range between the sample quantiles at levels p_l and p_h is (p_h - p_l)(n-1)/(n+1).) When
  clipped, the range is labelled "may be too narrow (n small)".
- Per size: n, source, confidence (`good` n >= 10, `low` 5-9, `rough` 3-4 or scaled), the 50% and 80% ranges and the
  median of fresh tokens, active hours and elapsed hours, the p10/p25/p50/p75/p90 (small-cell rule for display), the
  ratio actual / guess midpoint when guesses exist, and the count of left-out (`measured: false`) tasks.
- A size + kind cell with 5 or more tasks in the window is used before the size row.
- Quantiles: linear interpolation between order statistics.
- Attribution: tokens tied to tasks, to processes, and untied (`_other`, `_after`, `_untagged`) over the window's
  weeks; `items_share` = task tokens / all tokens; `overhead` = all tokens / task tokens (1 when no task tokens).
- A leave-one-out backtest of the size method and of "guess x ratio" on tasks with both; the summary holds n, median
  error and 50% range coverage of each.
- T-71 (U) Fixture of 12 tasks gives the expected rows (hand-computed quantiles).
- T-72 (U) Window rule: 5 recent tasks use the window; 4 recent + 3 old use all; 2 use scaling.
- T-73 (U) Scaling by guesses, and by 2 per step without guesses.
- T-74 (U) Kind cell used at n = 5, not at n = 4.
- T-75 (U) Attribution and overhead on a fixture with known untied tokens.
- T-76 (U) Backtest numbers on a fixture equal hand-computed values.
- T-77 (U) Quantile function equals known values (n = 1, 2, 5; p = 0, 0.25, 0.5, 0.9, 1).
- T-130 (U) Widened levels: n = 5, L = 0.5 gives [0.125, 0.875]; n = 5, L = 0.8 is clipped and labelled; n = 41,
  L = 0.5 gives [0.2375, 0.7625].
- T-131 (U) Errors use the geometric midpoint: range [1, 4] and actual 2 gives error 0.

**REQ-27 report.** `ledger report` must print: the size table (n, ranges, source, confidence), the attribution share
and overhead, the count of tasks left out as not measured, any warning (`format`, `deadline`, `lock`, last sync
failure), and the open tasks that have a stored estimate and measured use but no `done` (so abandoned work stays
visible). `report --aggregate` must leave out task IDs, the open list and every small cell, so its output can be shared.
- T-78 (U) A fixture gives the expected size table, attribution share and overhead.
- T-79 (U) An open task with use shows in the open list.
- T-80 (U) A warning in the status file shows at the top of the report.
- T-133 (U) `report --aggregate --json` holds no task ID (canary IDs) and no value with n < 5.

**REQ-40 Own accuracy over time (no hindsight).** `ledger report` must show the person's own accuracy over time.
Rows: per calendar month (by `done` time) and per block of 10 finished tasks (in `done` order; the last block may be
short and says so), plus a total row. Each row: n, median error, 50% range coverage, 80% range coverage, median
ln(actual / midpoint) (bias). Each number compares the task's **first estimate** (REQ-24) with the actual at `done`.
An estimate counts as "before work" only when its time is at most 10 minutes after the task's first measured message;
tasks whose first estimate came later are shown apart as "during work" and not mixed in; tasks without an estimate are
left out and counted. Only `measured` tasks count. Rows are split by source (`own`, `starter`); where `--guess` was
stored, the same numbers for the guesses show next to them. The share of tokens tied to tasks shows next to the
numbers. A row with n below 5 shows only its count. The report shows numbers only, no trend words.
- T-103 (U) A fixture of 23 done tasks over three months gives the expected month rows and three blocks (10, 10, 3),
  with hand-computed error, coverage and bias.
- T-104 (U) A task without an estimate is left out and counted.
- T-132 (U) A task whose first estimate is 30 minutes after its first message is in "during work", not in the rows.
- T-105 (U) A second estimate stored later doesn't change the numbers (the first estimate counts).
- T-106 (U) Guess rows show next to estimate rows when guesses were stored; starter and own rows are apart.
- T-107 (U) The untied share shows next to the accuracy numbers; a row with n = 4 shows only its count.

**REQ-28 Stable machine output.** Every command must accept `--json`. The JSON keys of each command must be listed in
`docs/CLI.md` and must not change within a major version.
- T-81 (U) For each command, `--json` output parses and has the documented keys.

## 4. Interfaces and versions

**REQ-29 Versioned schemas.** The ledger line, the task event, the config, `calibration.json`, `status.json` and
`starter.json` must each carry `schema_version` and have a JSON schema file in `schemas/`. Readers must migrate older
versions. A file with a newer version than the code knows must be read only (no writes) with a warning.
- T-82 (U) Each sample file validates against its schema (a small standard-library validator for the subset used).
- T-83 (U) A version-0 sample migrates to version 1.
- T-84 (U) A version-99 file is not overwritten; the command warns.

**REQ-30 Adapter interface.** Transcript reading must live behind one adapter interface per agent. Input: a session
(main transcript path and its subagent paths). Output: normalized messages (time, model, effort, fresh, cache reads,
message key, transcript id), prompt tag events (time, IDs, role), and tool events (time, kind: commit call / lead
command / agent prompt, the first 200 characters of the text to search for IDs), plus the working folders. The core
must not import anything agent-specific. v0.1.0 ships the Claude Code adapter only.
- T-85 (U) The core runs on a fake adapter (invented messages) and gives the same shares as with the real adapter on
  an equal transcript.
- T-86 (R) `scripts/record.py` and `scripts/ledger.py` don't read transcript fields directly.

## 5. Packaging and platform

**REQ-31 Plugin.** The repo must be a Claude Code plugin and a one-plugin marketplace: `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, `hooks/hooks.json`, `skills/measured-estimates/SKILL.md`. Install must be
`/plugin marketplace add <owner>/measured-estimates` then `/plugin install measured-estimates`. The plugin hooks must
add to the person's hooks and never edit their settings files.
- T-87 (X) Install in a scratch home on Linux and on macOS; a session end writes a ledger line, also for a
  generated 5,000-message transcript (the child outlives the host process).
- T-88 (X) The person's own `hooks` in `settings.json` keep the same JSON value after install and after uninstall.
  Only the keys that Claude Code itself writes for plugins (`enabledPlugins`, `extraKnownMarketplaces`) change.
  (Amended during verification: Claude Code rewrites and reformats `settings.json` on install, so the first
  wording, "byte-identical", can't hold for any plugin.)
- T-89 (C) A CI job checks that `plugin.json`, `marketplace.json` and `hooks.json` parse and name existing files.

**REQ-32 Runtime.** Python 3.9 or newer, standard library only (no `match`, no runtime `X | Y` types, no
`zip(strict=)`). macOS and Linux. Windows isn't supported in v0.1.0: the README and `plugin.json` description say so.
No services, timers, sudo, shell profile edits, package installs or background daemons (the detached child ends when
its record ends).
- T-90 (C) Tests pass on Python 3.9 and on the newest Python, on Linux and macOS runners.
- T-91 (C) A check fails on any import outside the standard library.
- T-92 (R) No file writes outside the store, config and state folders (and the scratch test home).
- T-138 (R) The README and `plugin.json` say Windows isn't supported.

**REQ-33 Recording cost.** The detached child must record a session of 5,000 messages with 3 subagents, with an
existing ledger of 20,000 lines, in at most 2 s on the Linux CI runner and 4 s on the macOS runner (median of 5
runs). The felt cost is the hook process (REQ-02, 200 ms).
- T-93 (C) A timing test on a generated fixture of that size.

**REQ-34 Several machines.** Each machine must write `ledger/<machine-id>.jsonl` and `tasks/<machine-id>.jsonl`
(append-only task events) only. `estimate`, `done`, `calibrate` and `report` must read every file in both folders
(files from other machines arrive through the person's own sync) and build the merged task view on read. Sync must
never need a merge (each machine pushes only its own files after rebasing on the remote).
- T-94 (I) Two scratch homes with two machine ids sync through one bare repo without a conflict; `done` sums both.
- T-128 (I) An estimate stored on machine B and `done` run on machine A: the first estimate is B's.

**REQ-35 Clock.** Records must use transcript timestamps in UTC. `recorded_at` and event `at` fields are the only
local-clock fields.
- T-95 (U) A fixture with timestamps in a non-UTC offset gives UTC fields.

## 6. Skill and documents

**REQ-36 Skill.** `SKILL.md` must tell the agent: use it for any time or token estimate, plan or agent brief; write its
own guess first, then run `estimate --guess` (so the guess isn't anchored by the range); store estimates with `--for`;
the tag rule (`ITEM:` / `ROLE:` lines at the top of every agent prompt; `ITEM: process:<name>` for non-task work); run
`done` when a task ships; report ranges with n and source, never a point; run `init` on first use. It must say how the
agent finds `ledger.py`: the path `${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py` when the host expands it, else a
documented lookup command.
- T-96 (R) Checklist review of `SKILL.md` against this list.
- T-97 (X) In the install test, the skill shows in the skill list.
- T-134 (X) In the install test, an agent runs `estimate` from the skill text alone; after uninstall, a session end
  writes nothing and the data is unchanged.

**REQ-37 README.** The README must cover, in this order: an "ELI5" section first (REQ-42), a section "How accurate is
it?" (REQ-41), 3-step install, the tag rule, a worked example, what's stored, how to delete, limits (Windows not
supported among them), and the origin of the starter numbers in one line. Language rules: REQ-42.
- T-98 (R) Checklist review of the README against this list and its order.

**REQ-42 README language: ASD-STE100 and ELI5 first.** The whole README must use ASD-STE100 Simplified Technical
English: one instruction per sentence; procedure sentences at most 20 words; description sentences at most 25 words;
active voice; approved simple words; the same term for the same thing every time (a term list at the end of the README
fixes the terms: session, task, task ID, tokens, fresh tokens, range, estimate, ledger, store); numbered steps for
procedures. Contractions are allowed. No comparisons to other products ("like X"), no sparkle icons, no hype words, no
kicker endings. The first section, "ELI5", must be a plain summary for a person with no coding background, in short
sentences: what the plugin is; who it's for (people who use coding agents and want to know what work will really cost
in time and tokens); what it does (records the cost of each session on your own computer, learns from finished tasks,
gives your agent honest ranges before it estimates); what it doesn't do (doesn't read or send your prompts or code;
nothing leaves your computer unless you set up sync); why it helps (estimates come closer to the real cost over time).
At most one comparison, and only one that explains (for example a fuel log that shows a car's real fuel use); no
decorative metaphors.
- T-111 (C) A sentence-length lint for `README.md` in CI: sentences inside numbered or bulleted lists under a heading
  that starts with a verb or "How to" (procedures) have at most 20 words; other prose sentences at most 25 words. Code
  blocks, tables, headings and link-only lines are skipped. The lint has a self-test (a 26-word sentence fails).
- T-112 (C) The lint fails on passive markers ("is done by", "was made by", "are sent by"), on banned words
  ("seamless", "powerful", "magic", "effortless", "revolutionary", "supercharge") and on sparkle characters.
- T-113 (R) Review checklist: "ELI5" is the first section and covers the five points; one instruction per sentence;
  the term list is used the same way everywhere; at most one explanatory comparison.

**REQ-41 Evidence, not claims.** The README section "How accurate is it?" must:
1. State the problem in numbers from `docs/RESULTS.md` §Baseline (the guesses before calibration against the measured
   cost: median ratio, and how many tasks were below, inside and above the guessed range, with n), next to the
   attribution caveat: actual = tokens tied to the task, about X% of all tokens (X from `docs/RESULTS.md`), so part of
   the gap is undercount, not over-estimation.
2. State what calibration changed using only numbers from `docs/RESULTS.md`: the three H1 verdicts together (against
   guesses, against bias-corrected guesses, against size-blind ranges), interval coverage and bias, each with its n,
   the number of days, and its 90% interval. Until the evaluation runs, the section says that the numbers come from
   `docs/RESULTS.md` and shows none.
3. State each hypothesis that failed or was inconclusive, with its number. Make no claim that `docs/RESULTS.md`
   doesn't support.
4. Say plainly what isn't shown yet: H3 (accuracy improves as a person's own finished tasks replace the starter
   ranges) can't be shown from one person's three weeks of data; say how a person sees it on their own data
   (`ledger report`, REQ-40).
5. Show effort only as a description, unless a registered test covers it.
The skill (`SKILL.md`) must say in one or two lines how it improves estimates and point to the same evidence; it must
not state a number that isn't in `docs/RESULTS.md`.
- T-108 (R) Every number in "How accurate is it?" and in `SKILL.md` appears in `docs/RESULTS.md`.
- T-109 (C) A CI check: each number in the README between the markers `<!-- results:start -->` and
  `<!-- results:end -->` (the whole section, baseline included) appears in `docs/RESULTS.md`. Normalization: a number
  is a maximal run of digits with an optional decimal part and optional leading minus; `0.30x` gives 0.30; "55 of 82"
  gives 55 and 82; `41%` gives 41; numbers compare as decimals after removing trailing zeros.
- T-110 (R) Each primary fail or inconclusive verdict in `docs/RESULTS.md` is stated in the README with its number,
  and results that point against calibration are stated as plainly as results that point for it.

**REQ-38 Project files.** LICENSE (MIT, "Copyright (c) 2026 Sean Ireton"), CONTRIBUTING (how to add an adapter for
another agent; starter updates add at least 5 tasks per bucket at a time), issue templates "Add support for <agent>"
and "Calibration looks wrong", CHANGELOG, version 0.1.0 in `plugin.json` and the CHANGELOG.
- T-99 (R) Files present; versions agree (a CI check compares the two versions).

**REQ-39 Reproducible evaluation.** `scripts/evaluate.py` must run the protocol in `docs/EVALUATION.md` on an input file
outside the repo with a fixed seed, import the calibration and statistics functions from the shipped code (no second
implementation), and write only aggregate results under the small-cell rule (REQ-17). Two runs on the same input must
give byte-identical output.
- T-100 (U) Two runs on an invented input give identical output.
- T-101 (U) The output holds no task ID from the input (canary IDs) and no value cell with n < 5.
- T-102 (E) The run on the author's data writes `docs/RESULTS.md` as registered.
- T-140 (R) `evaluate.py` imports `calibrate` and the statistics from the shipped package.

## Traceability

### Requirement to tests

| REQ | Tests |
|---|---|
| REQ-01 | T-01, T-02, T-03 |
| REQ-02 | T-04, T-05, T-06, T-07, T-114, T-115, T-116, T-148 |
| REQ-03 | T-08, T-09, T-10, T-117, T-118, T-119 |
| REQ-04 | T-11, T-12, T-13, T-14 |
| REQ-05 | T-15, T-16 |
| REQ-06 | T-17, T-18, T-19, T-20, T-21, T-22, T-120 |
| REQ-07 | T-23, T-24, T-25, T-26, T-27, T-123 |
| REQ-08 | T-28, T-29, T-30, T-121, T-122 |
| REQ-09 | T-31, T-32, T-33, T-34 |
| REQ-10 | T-35, T-36 |
| REQ-11 | T-37, T-38, T-124 |
| REQ-12 | T-39, T-40, T-41, T-136, T-137, T-143 |
| REQ-13 | T-42, T-43, T-142 |
| REQ-14 | T-44 |
| REQ-15 | T-45, T-46, T-47, T-126, T-127, T-141, T-144 |
| REQ-16 | T-48, T-49, T-145 |
| REQ-17 | T-50, T-51, T-135 |
| REQ-18 | T-52, T-53, T-54 |
| REQ-19 | T-55, T-56, T-57 |
| REQ-20 | T-58, T-59 |
| REQ-21 | T-60, T-61, T-62, T-147 |
| REQ-22 | T-63, T-64 |
| REQ-23 | T-65 |
| REQ-24 | T-66, T-67 |
| REQ-25 | T-68, T-69, T-70, T-129 |
| REQ-26 | T-71, T-72, T-73, T-74, T-75, T-76, T-77, T-130, T-131 |
| REQ-27 | T-78, T-79, T-80, T-133 |
| REQ-28 | T-81 |
| REQ-29 | T-82, T-83, T-84 |
| REQ-30 | T-85, T-86 |
| REQ-31 | T-87, T-88, T-89 |
| REQ-32 | T-90, T-91, T-92, T-138 |
| REQ-33 | T-93 |
| REQ-34 | T-94, T-128 |
| REQ-35 | T-95 |
| REQ-36 | T-96, T-97, T-134 |
| REQ-37 | T-98 |
| REQ-38 | T-99 |
| REQ-39 | T-100, T-101, T-102, T-140 |
| REQ-40 | T-103, T-104, T-105, T-106, T-107, T-132 |
| REQ-41 | T-108, T-109, T-110 |
| REQ-42 | T-111, T-112, T-113 |
| REQ-43 | T-125, T-146 |

### Test to requirement

Every test serves exactly one requirement: T-01..T-03 REQ-01; T-04..T-07, T-114..T-116 REQ-02; T-08..T-10,
T-117..T-119 REQ-03; T-11..T-14 REQ-04; T-15..T-16 REQ-05; T-17..T-22, T-120 REQ-06; T-23..T-27, T-123 REQ-07;
T-28..T-30, T-121, T-122 REQ-08; T-31..T-34 REQ-09; T-35..T-36 REQ-10; T-37, T-38, T-124 REQ-11; T-39..T-41, T-136,
T-137 REQ-12; T-42..T-43 REQ-13; T-44 REQ-14; T-45..T-47, T-126, T-127 REQ-15; T-48..T-49 REQ-16; T-50, T-51, T-135
REQ-17; T-52..T-54 REQ-18; T-55..T-57 REQ-19; T-58..T-59 REQ-20; T-60..T-62 REQ-21; T-63..T-64 REQ-22; T-65 REQ-23;
T-66..T-67 REQ-24; T-68..T-70, T-129 REQ-25; T-71..T-77, T-130, T-131 REQ-26; T-78..T-80, T-133 REQ-27; T-81 REQ-28;
T-82..T-84 REQ-29; T-85..T-86 REQ-30; T-87..T-89 REQ-31; T-90..T-92, T-138 REQ-32; T-93 REQ-33; T-94, T-128 REQ-34;
T-95 REQ-35; T-96, T-97, T-134 REQ-36; T-98 REQ-37; T-99 REQ-38; T-100..T-102, T-140 REQ-39; T-103..T-107, T-132
REQ-40; T-108..T-110 REQ-41; T-111..T-113 REQ-42; T-125 REQ-43. Added in the final-review fix round: T-141, T-144 REQ-15; T-142 REQ-13; T-143 REQ-12; T-145 REQ-16;
T-146 REQ-43; T-147 REQ-21; T-148 REQ-02. T-139 isn't used.

In the code, each unit or integration test names its T-ID in its docstring, and `tests/test_traceability.py` checks
that every T-ID of type U and I in this file has a test and every T-ID of type C has a CI step that names it, and
that no test names an unknown T-ID.

## FMEA links

Each failure mode in `docs/FMEA.md` names the requirements and tests that cover it.
