# Requirements

Version 0.1 (pre-registration draft). Status: written before any code. REQ-40, REQ-41 and REQ-42 were added after REQ-39
and sit next to the requirements they extend (report, README). Each requirement has an ID (REQ-xx), a
statement, and one or more acceptance tests (T-xx). The traceability table at the end maps every requirement to its
tests and every test to its requirements. A requirement is met only when all of its tests pass.

Words: **must** = required for v0.1.0. **Session** = one Claude Code conversation (its main transcript and its
subagent transcripts). **Task** = a unit of work with an ID that the person chooses (an issue, a ticket, a backlog
item). **Fresh tokens** = output tokens + new input tokens + cache-write tokens. Cache reads are counted apart and
aren't part of fresh tokens. **Store** = the local data folder (see `docs/DATA.md`).

Test types: **U** unit test (unittest, invented fixtures), **I** integration test (the real scripts on a scratch home
folder), **C** CI check, **X** install test on Linux and macOS, **R** inspection by a reviewer, **E** evaluation on
real data (`docs/EVALUATION.md`).

## 1. Recording

**REQ-01 Hook events.** The plugin must run the recorder on `SessionEnd` (records at once) and on `Stop` (async, at most
once per session in each `stop_every_min` minutes, default 15), so a session that's killed is still on record.
- T-01 (I) A `SessionEnd` hook input writes one ledger line for the session.
- T-02 (U) Two `Stop` calls within 15 minutes write once; a call after 15 minutes writes again.
- T-03 (R) `hooks/hooks.json` declares `SessionEnd` and `Stop` (`async: true`) with a timeout.

**REQ-02 Never block a session.** The recorder must exit with status 0 on every error, must not print to stdout, must
finish its own work within its deadline (10 s for `SessionEnd`, 30 s for `Stop`) and must not wait for a network call.
A missing or old Python (below 3.10) must not cause a hook error.
- T-04 (U) Malformed hook input, a missing transcript, a read-only store and an exception inside the parser each give
  exit 0 and no stdout.
- T-05 (U) The recorder stops parsing at its deadline and exits 0 (deadline injected as 0.1 s).
- T-06 (R) The hook command is guarded so that a missing `python3` exits 0.
- T-07 (U) Under Python below 3.10 (version check injected) the recorder exits 0 at once.

**REQ-03 Token counts.** For each assistant message the recorder must count fresh tokens and cache reads from the
message's usage block. A message that appears on several transcript lines (streamed parts) must count once (key:
message id, else request id, else line uuid). Synthetic messages (model name in angle brackets) must not count.
- T-08 (U) A golden transcript gives the expected fresh tokens and cache reads, exactly.
- T-09 (U) A message repeated on three lines counts once.
- T-10 (U) A `<synthetic>` message counts zero.

**REQ-04 Model and effort split.** Every ledger line must split fresh tokens, cache reads and message counts by model
and by effort level. The effort of a message is its `perTurnEffort` field, else its `effort` field, else `unknown`.
Each task share must carry the same model x effort split. A task's **dominant effort** is the effort with the most fresh
tokens over its sessions (ties go to the alphabetically lower name).
- T-11 (U) A transcript with `high` and `medium` turns on two models gives the four expected cells.
- T-12 (U) A message with no effort field counts under `unknown`.
- T-13 (U) `perTurnEffort` wins over `effort` when both are present and differ.
- T-14 (U) Dominant effort: largest share wins; a tie goes to the lower name.

**REQ-05 Subagents.** The record must include the session's subagent transcripts. A subagent without its own tag
takes the tag of its session.
- T-15 (U) A session with two subagent files sums all three transcripts.
- T-16 (U) An untagged subagent of a tagged session counts for the session's task.

**REQ-06 Tag rule.** A line `ITEM: <ids>` in the first prompt of a transcript must tie all of that transcript's fresh
tokens to those IDs, split equally. An `ITEM:` line in a later prompt must apply from that prompt on (it changes the
task of a tagged transcript and tags the rest of an untagged one). `ITEM: process:<name>` must tie tokens to a process
key (recurring work that isn't a task). An optional `ROLE: build|review|fix|lead` line must set the role (default
`build`); a later `ROLE:` line must change it from that prompt on. Only IDs that match the configured ID patterns or
the process pattern count.
- T-17 (U) First-prompt tag with two IDs splits 50/50.
- T-18 (U) A later `ITEM:` line moves the tokens after it to the new ID.
- T-19 (U) A later `ITEM:` line in an untagged transcript tags only the rest of it.
- T-20 (U) `ITEM: process:review` counts under `process:review`, not under a task.
- T-21 (U) `ROLE: review` in the first prompt and `ROLE: fix` in a later prompt split the roles at that time.
- T-22 (U) Text after `ITEM:` that matches no pattern ties nothing.

**REQ-07 Commit attribution (untagged work).** In an untagged transcript, a message must count for the next commit that
the same transcript made itself (a `git commit` tool call followed by a commit in the reflog of a folder the
transcript worked in, within `commit_window_min`, default 20 minutes), when that commit's subject holds a task ID. Only
commits made on this machine count (HEAD reflog entries of type "commit"). Tokens that no commit claims must go to the
tasks the transcript touched at both ends of that stretch (IDs in its own commit subjects, in `git push`, `git merge`,
`gh pr` and `gh run` commands, in branch names of those commands, and on the `ITEM:` lines of prompts it gave to
agents), role `lead`. Tokens with no task anywhere must go to `_other` (a commit without an ID) or `_after` (after the
last commit).
- T-23 (I) A scratch git repo with two commits (`ABC-1: ...`, `ABC-2: ...`) splits the tokens before each commit.
- T-24 (U) A commit made by another transcript doesn't count for this one.
- T-25 (I) A commit pulled from a remote (no "commit" reflog entry) doesn't count.
- T-26 (U) Lead touches: a message between a `git push` naming `ABC-3` and a prompt with `ITEM: ABC-4` splits between
  both, role `lead`.
- T-27 (U) Tokens after the last commit with no touch go to `_after`; before a commit without an ID to `_other`.

**REQ-08 Task ID patterns.** The ID patterns must come from the config. Defaults: `ABC-123` (letters, dash, digits),
`#123` (issue numbers) and `K42` (one capital letter + 2-4 digits, with an optional `.N` step). `ledger init` must let
the person pick or type a pattern and must reject a pattern that doesn't compile or that matches an empty string.
- T-28 (U) Each default form matches; `review-S1`-style words and plain numbers don't.
- T-29 (U) A custom pattern from the config replaces the defaults.
- T-30 (U) An invalid pattern is refused with a message; the config doesn't change.

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
add a second one. Each machine must write only its own file.
- T-35 (U) Recording the same session twice leaves one line with the newer counts.
- T-36 (U) Lines of other sessions in the file stay byte-identical.

**REQ-11 Concurrency and safe writes.** Two recorders that finish at the same time must not lose a line (an exclusive
file lock on the store). Every write must go to a temporary file in the same folder, then rename, so a crash or a
full disk never leaves a half-written ledger.
- T-37 (I) Two recorder processes started together for two sessions leave two lines.
- T-38 (U) A write that fails (injected `OSError` on write) leaves the old file unchanged.

**REQ-12 Partial and changed transcripts.** The adapter must skip lines it can't parse and count them
(`skipped_lines`). When a transcript has lines but no message with a usage block, the recorder must write a warning to
the store's status file; `ledger report` and `ledger estimate` must show it.
- T-39 (U) A transcript with a truncated last line records the rest and `skipped_lines: 1`.
- T-40 (U) A transcript in an unknown format writes the warning and `report` shows it.
- T-41 (U) The golden sample transcript still parses (a format change in Claude Code fails this test first).

## 2. Privacy

**REQ-13 Data minimization.** By default a ledger line must hold only: counts, times, model names, effort levels, task
IDs, process keys, roles, the random machine id, the session id and the fields listed in `docs/DATA.md`. It must never
hold prompt text, reply text, tool inputs or outputs, code, file contents, file paths, commit subjects, hostnames or
user names. From an `ITEM:` or `ROLE:` line it must keep only the matched IDs and the role word.
- T-42 (U) A fixture full of canary strings (a fake secret, a path, a commit subject, a prompt sentence, a hostname)
  gives a ledger line, `tasks.json` and `calibration.json` that contain none of them.
- T-43 (U) The ledger line's keys are exactly the keys allowed by the schema (no extra key).

**REQ-14 Opt-in fields.** The working folder (with the home folder written as `~`), git branch, repo folder name and
session title must be stored only when the person turns each one on in the config. Default: all off.
- T-44 (U) Default config: the four fields are absent. Each one turned on: only that one is present.

**REQ-15 No network by default.** The recorder and every `ledger` command must make no network connection unless the
person sets a sync remote. With a sync remote, the recorder must push only the ledger folder, to that remote only, in
a detached child process with its own 60 s timeout, so the hook doesn't wait for it.
- T-45 (U) With no remote, recording and every command run with `socket.socket` patched to raise, and pass.
- T-46 (I) With a local bare repo as the remote, a record arrives there; the hook returns before the push ends
  (push delayed by a fake `git` wrapper).
- T-47 (R) No code path reads a remote URL from anywhere but the config file.

**REQ-16 Delete.** `ledger forget --yes` must delete the store, the config, and the state files (stamps, lock, status),
and must print what it deleted. Without `--yes` it must only list what it would delete. It must never touch Claude
Code's own transcripts or a sync remote.
- T-48 (I) After `forget --yes` the three folders are gone; transcripts are unchanged.
- T-49 (U) `forget` without `--yes` deletes nothing.

**REQ-17 Starter table holds only aggregates.** `data/starter.json` must hold only these keys: schema version, origin
line, units, and per size bucket `n` and the p10/p25/p50/p75/p90 of fresh tokens, active hours and elapsed hours; plus
the overall ratio and backtest summary. Every bucket must have n >= 5. No IDs, titles, names, dates of single tasks,
paths or free text other than the origin line.
- T-50 (C) A CI script checks the keys of `starter.json` against an allow list and checks n >= 5 per bucket.
- T-51 (C) The same script fails on a planted extra key and on a bucket with n = 4 (self-test).

**REQ-18 Repo hygiene.** The repo must hold no secrets, emails other than the GitHub noreply address, home paths, IP
addresses, hostnames or real transcript content. CI must scan every push.
- T-52 (C) CI secret/PII scan job (patterns for keys, tokens, emails, home paths, IPs) passes on the repo.
- T-53 (C) The scan fails on a planted test string (self-test in a temporary copy).
- T-54 (R) The reviewer runs the scan list from the build brief on `git log -p` before the first push.

## 3. Commands (CLI contract)

All commands are `python3 scripts/ledger.py <command>`. Each must accept `--json` and then print one JSON object to
stdout. Exit codes: 0 done, 1 bad input, 2 no data. Errors go to stderr.

**REQ-19 init.** `ledger init` must create the config (random machine id from `secrets.token_hex`, ID patterns, sync
off) and the store, ask at most two questions (ID format; sync yes/no, default no), and accept both answers as flags
for agents (`--id-pattern`, `--sync-remote`, `--yes`). A second run must keep the machine id.
- T-55 (I) `init --yes` on a scratch home writes a valid config and store.
- T-56 (U) A second `init` keeps the machine id and other settings unless a flag changes them.
- T-57 (U) The machine id is 16 hex chars and isn't derived from the hostname.

**REQ-20 backfill.** `ledger backfill [--days N]` (default 30) must record every session transcript of the last N days
that Claude Code still keeps, with the same rules as the hook, and must be safe to run again (no duplicate lines).
- T-58 (I) Backfill of three fixture sessions writes three lines; a second run changes nothing.
- T-59 (U) Sessions older than N days are skipped.

**REQ-21 estimate.** `ledger estimate --size <S> [--kind <K>] [--effort <E>] [--guess LO-HI] [--for <ID>]` must print a
range, never a single number: tokens p25-p75 and p10-p90, active hours and elapsed hours p25-p75, `n`, the source
(`own` or `starter`), a confidence word, the share of tokens tied to tasks and the overhead factor. With `--for` it
must store the estimate (with its time, inputs, outputs and the calibration it came from) in `tasks.json`.
- T-60 (U) The output has every field above; no field is a lone point estimate.
- T-61 (U) `--for ABC-1` stores the estimate; `--json` output equals the stored record.
- T-62 (U) An unknown size is refused with the list of sizes (exit 1).

**REQ-22 Own data replaces starter, size by size.** For a size with at least 5 of the person's own finished tasks,
`estimate` must use only own data; with fewer, it must use the starter row and label it `starter, not your data`
with the starter's n.
- T-63 (U) 4 own tasks of size S: source `starter`. 5 own tasks: source `own`.
- T-64 (U) Own data of size S doesn't change the source of size M.

**REQ-23 Effort ranges.** `estimate --effort <E>` must give an effort-specific range only when the size has at least 5
own finished tasks with that dominant effort; else it must give the size range and a note that says why.
- T-65 (U) 5 tasks at `high`: effort range. 4 tasks: size range + note.

**REQ-24 Estimate is stored once (hindsight guard).** The first stored estimate of a task must never change. A new
`estimate --for` on the same task must append a new estimate; `done` must compare the actual with the first one and
also report the last one.
- T-66 (U) Two estimates for one task: both kept in order; the first is unchanged.
- T-67 (U) `done` reports error against the first and the last estimate.

**REQ-25 done.** `ledger done <ID> [--size S] [--kind K]` must mark the task finished, sum its measured use over every
ledger file in the store (all machines), store it as `actual` (fresh tokens, by role, by model x effort, dominant
effort, active hours, elapsed hours, sessions), compare it with the stored estimate, and run the calibration again.
`done` on a task with no ledger data must say so (exit 2) and not mark it.
- T-68 (U) Two machine files with shares of `ABC-1` sum into one actual.
- T-69 (U) `done` without data exits 2 and leaves `tasks.json` unchanged.
- T-70 (U) `done` twice updates the actual and keeps one `done_at` (the first) plus `updated_at`.

**REQ-26 calibrate.** `ledger calibrate` must turn finished tasks into `calibration.json` with the size-bucket method:
- Sizes on one scale (default `XS, S, M, L, XL`; ranges such as `S-M` are allowed and sit between).
- Window rule: per size, the tasks of the last 28 days before the newest finished task when there are at least 5;
  else all tasks of that size when there are at least 3; else the size is scaled from the nearest measured size by the
  ratio of the median guesses of the two sizes (by 2 per scale step when guesses are missing).
- Per size: n, source, confidence (`good` n >= 10, `low` 5-9, `rough` 3-4 or scaled), p10/p25/p50/p75/p90 of fresh
  tokens, active hours and elapsed hours, and the ratio actual / guess midpoint when guesses exist.
- A size + kind cell with 5 or more tasks in the window is used before the size row.
- Quantiles: linear interpolation between order statistics.
- Attribution: tokens tied to tasks, to processes, `_other` and `_after` over the window's weeks; `items_share` = task
  tokens / all tokens; `overhead` = all tokens / task tokens (1 when no task tokens).
- A leave-one-out backtest of the size method and of "guess x ratio" on tasks with both; the summary holds n, median
  |ln(actual / midpoint)| and p25-p75 coverage of each.
- T-71 (U) Fixture of 12 tasks gives the expected rows (hand-computed quantiles).
- T-72 (U) Window rule: 5 recent tasks use the window; 4 recent + 3 old use all; 2 use scaling.
- T-73 (U) Scaling by guesses, and by 2 per step without guesses.
- T-74 (U) Kind cell used at n = 5, not at n = 4.
- T-75 (U) Attribution and overhead on a fixture with known untied tokens.
- T-76 (U) Backtest numbers on a fixture equal hand-computed values.
- T-77 (U) Quantile function equals known values (n = 1, 2, 5; p = 0, 0.25, 0.5, 0.9, 1).

**REQ-27 report.** `ledger report` must print: the size table (n, ranges, source, confidence), the attribution share
and overhead, any adapter warning, and the open tasks that have a stored estimate and measured use but no `done` (so
abandoned work stays visible).
- T-78 (U) A fixture gives the expected size table, attribution share and overhead.
- T-79 (U) An open task with use shows in the open list.
- T-80 (U) An adapter warning in the status file shows at the top of the report.

**REQ-40 Own accuracy over time (no hindsight).** `ledger report` must show the person's own accuracy over time, so
they can see whether their estimates improve. Rows: per calendar month (by `done` time) and per block of 10 finished
tasks (in `done` order; the last block may be short and says so), plus a total row. Each row: n, median |ln(actual /
midpoint)|, p25-p75 coverage, p10-p90 coverage, median signed ln(actual / midpoint) (bias). Each number must compare
the **first** estimate stored with `estimate --for <ID>` (REQ-24) with the actual measured at `done`; a task finished
without a stored estimate doesn't count and the report says how many were left out. Rows must be split by source
(`own`, `starter`), and, where `--guess` was stored, must show the same numbers for the guesses next to them. The
share of tokens tied to tasks must show next to the numbers. A row with n below 5 must show its numbers marked "n too
small" and must not show a trend word.
- T-103 (U) A fixture of 23 done tasks over three months gives the expected month rows and three blocks (10, 10, 3),
  with hand-computed error, coverage and bias.
- T-104 (U) A task whose estimate was stored after it was finished, or not stored, is left out and counted.
- T-105 (U) A second estimate stored later doesn't change the numbers (the first estimate counts).
- T-106 (U) Guess rows show next to estimate rows when guesses were stored; starter and own rows are apart.
- T-107 (U) The untied share shows next to the accuracy numbers; a row with n = 4 is marked "n too small".

**REQ-28 Stable machine output.** Every command must accept `--json`. The JSON keys of each command must be listed in
`docs/CLI.md` and must not change within a major version.
- T-81 (U) For each command, `--json` output parses and has the documented keys.

## 4. Interfaces and versions

**REQ-29 Versioned schemas.** The ledger line, `tasks.json`, the config, `calibration.json` and `starter.json` must each
carry `schema_version` and have a JSON schema file in `schemas/`. Readers must migrate older versions. A file with a
newer version than the code knows must be read only (no writes) with a warning.
- T-82 (U) Each sample file validates against its schema (a small stdlib validator for the subset used).
- T-83 (U) A version-0 sample migrates to version 1.
- T-84 (U) A version-99 file is not overwritten; the command warns.

**REQ-30 Adapter interface.** Transcript reading must live behind one adapter interface per agent. Input: a session
(main transcript path and its subagent paths). Output: a list of normalized messages (time, model, effort, fresh,
cache reads, message key, transcript id), prompt tag events (time, IDs, role), and tool events (time, kind: commit
call / lead command / agent prompt, IDs found). The core must not import anything agent-specific. v0.1.0 ships the
Claude Code adapter only.
- T-85 (U) The core runs on a fake adapter (invented messages) and gives the same shares as with the real adapter on
  an equal transcript.
- T-86 (R) `scripts/record.py` and `scripts/ledger.py` don't read transcript fields directly.

## 5. Packaging and platform

**REQ-31 Plugin.** The repo must be a Claude Code plugin and a one-plugin marketplace: `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, `hooks/hooks.json`, `skills/measured-estimates/SKILL.md`. Install must be
`/plugin marketplace add <owner>/measured-estimates` then `/plugin install measured-estimates`. The plugin hooks must
add to the person's hooks and never edit their settings files.
- T-87 (X) Install in a scratch home on Linux and on macOS; a session end writes a ledger line.
- T-88 (X) The person's existing `settings.json` is byte-identical after install and after uninstall.
- T-89 (C) A CI job checks that `plugin.json`, `marketplace.json` and `hooks.json` parse and name existing files.

**REQ-32 Runtime.** Python 3.10 or newer, standard library only. macOS and Linux. No services, timers, sudo, shell
profile edits, package installs or background daemons.
- T-90 (C) Tests pass on Python 3.10 and on the newest Python, on Linux and macOS runners.
- T-91 (C) A check fails on any import outside the standard library.
- T-92 (R) No file writes outside the store, config and state folders (and the scratch test home).

**REQ-33 Hook cost.** The `SessionEnd` record must take at most 2 s for a session of 5,000 messages with 3 subagents
on the CI runner (median of 3 runs).
- T-93 (C) A timing test on a generated 5,000-message fixture.

**REQ-34 Several machines.** Each machine must write `<machine-id>.jsonl` only. `done`, `calibrate` and `report` must
read every `*.jsonl` in the store (files from other machines arrive through the person's own sync). Sync must never
need a merge (each machine pushes only its own file after rebasing on the remote).
- T-94 (I) Two scratch homes with two machine ids sync through one bare repo without a conflict; `done` sums both.

**REQ-35 Clock.** Records must use transcript timestamps in UTC. `recorded_at` is the only local-clock field.
- T-95 (U) A fixture with timestamps in a non-UTC offset gives UTC fields.

## 6. Skill and documents

**REQ-36 Skill.** `SKILL.md` must tell the agent: use it for any time or token estimate, plan or agent brief; write
its own guess first, then run `estimate --guess` (so the guess isn't anchored by the range); store estimates with
`--for`; the tag rule (`ITEM:` / `ROLE:` lines at the top of every agent prompt; `ITEM: process:<name>` for
non-task work); run `done` when a task ships; report ranges with n and source, never a point; run `init` on first use.
- T-96 (R) Checklist review of `SKILL.md` against this list.
- T-97 (X) In the install test, the skill shows in the skill list.

**REQ-37 README.** The README must cover, in this order: an "ELI5" section first (REQ-42), a section "How accurate is
it?" (REQ-41), 3-step install, the tag rule, a worked example, what's stored, how to delete, limits, and the origin of
the starter numbers in one line. Language rules: REQ-42.
- T-98 (R) Checklist review of the README against this list and its order.

**REQ-42 README language: ASD-STE100 and ELI5 first.** The whole README must use ASD-STE100 Simplified Technical
English: one instruction per sentence; procedure sentences at most 20 words; description sentences at most 25 words;
active voice; approved simple words; the same term for the same thing every time (a term list at the end of the README
fixes the terms: session, task, task ID, tokens, fresh tokens, range, estimate, ledger, store); numbered steps for
procedures. Contractions are allowed. No comparisons to other products ("like X"), no sparkle icons, no hype words, no
kicker endings.
The first section, "ELI5", must be a plain summary for a person with no coding background, in short sentences: what the
plugin is; who it's for (people who use coding agents and want to know what work will really cost in time and tokens);
what it does (records the cost of each session on your own computer, learns from finished tasks, gives your agent
honest ranges before it estimates); what it doesn't do (doesn't read or send your prompts or code; nothing leaves your
computer unless you set up sync); why it helps (estimates come closer to the real cost over time). At most one
comparison, and only one that explains (for example a fuel log that shows a car's real fuel use); no decorative
metaphors.
- T-111 (C) A sentence-length lint for `README.md` in CI: sentences inside numbered or bulleted procedure lists have at
  most 20 words; other prose sentences at most 25 words. Code blocks, tables, headings and link-only lines are skipped.
  The lint has a self-test (a 26-word sentence fails).
- T-112 (C) The lint fails on a passive-voice marker list ("is done by", "was made by", "are sent by") and on banned
  words (a short list: "seamless", "powerful", "magic", "effortless", "revolutionary", "supercharge") and sparkle
  characters.
- T-113 (R) Review checklist: "ELI5" is the first section and covers the five points; one instruction per sentence;
  the term list is used the same way everywhere; at most one explanatory comparison.

**REQ-41 Evidence, not claims.** The README section "How accurate is it?" must:
1. State the problem in numbers from the author's data before calibration (actual use was a median 0.30x the estimate
   midpoint; of 82 tasks, 55 were below the low end of the estimate, 22 inside, 5 above).
2. State what calibration changed using only numbers from `docs/RESULTS.md` (error against guesses, interval coverage,
   bias), each with its n and 90% CI. Until the evaluation runs, the section must say that the numbers come from
   `docs/RESULTS.md` and show none.
3. State each hypothesis that failed or was inconclusive, with its number. Make no claim that `docs/RESULTS.md`
   doesn't support.
4. Say plainly what isn't shown yet: H3 (accuracy improves as a person's own finished tasks replace the starter ranges)
   can't be proven from one person's three weeks of data; say how a person sees it on their own data (`ledger report`,
   REQ-40).
5. Show effort only as a description (a table of counts and medians), unless a registered test covers it.

The skill (`SKILL.md`) must say in one or two lines how it improves estimates and point to the same evidence; it must
not state a number that isn't in `docs/RESULTS.md`.
- T-108 (R) Every number in "How accurate is it?" and in `SKILL.md` appears in `docs/RESULTS.md` or in item 1 above.
- T-109 (C) A CI check: each number in the README section between the markers `<!-- results:start -->` and
  `<!-- results:end -->` appears in `docs/RESULTS.md`.
- T-110 (R) Each fail or inconclusive verdict in `docs/RESULTS.md` is stated in the README with its number.

**REQ-38 Project files.** LICENSE (MIT, "Copyright (c) 2026 Sean Ireton"), CONTRIBUTING (how to add an adapter for
another agent), issue templates "Add support for <agent>" and "Calibration looks wrong", CHANGELOG, version 0.1.0 in
`plugin.json` and the CHANGELOG.
- T-99 (R) Files present; versions agree (a CI check compares the two versions).

**REQ-39 Reproducible evaluation.** `scripts/evaluate.py` must run the protocol in `docs/EVALUATION.md` on an input
file outside the repo with a fixed seed, and write only aggregate results. Two runs on the same input must give
byte-identical output.
- T-100 (U) Two runs on an invented input give identical output.
- T-101 (U) The output holds no task ID from the input (canary IDs).
- T-102 (E) The run on the author's data writes `docs/RESULTS.md` as registered.

## Traceability

### Requirement to tests

| REQ | Tests |
|---|---|
| REQ-01 | T-01, T-02, T-03 |
| REQ-02 | T-04, T-05, T-06, T-07 |
| REQ-03 | T-08, T-09, T-10 |
| REQ-04 | T-11, T-12, T-13, T-14 |
| REQ-05 | T-15, T-16 |
| REQ-06 | T-17, T-18, T-19, T-20, T-21, T-22 |
| REQ-07 | T-23, T-24, T-25, T-26, T-27 |
| REQ-08 | T-28, T-29, T-30 |
| REQ-09 | T-31, T-32, T-33, T-34 |
| REQ-10 | T-35, T-36 |
| REQ-11 | T-37, T-38 |
| REQ-12 | T-39, T-40, T-41 |
| REQ-13 | T-42, T-43 |
| REQ-14 | T-44 |
| REQ-15 | T-45, T-46, T-47 |
| REQ-16 | T-48, T-49 |
| REQ-17 | T-50, T-51 |
| REQ-18 | T-52, T-53, T-54 |
| REQ-19 | T-55, T-56, T-57 |
| REQ-20 | T-58, T-59 |
| REQ-21 | T-60, T-61, T-62 |
| REQ-22 | T-63, T-64 |
| REQ-23 | T-65 |
| REQ-24 | T-66, T-67 |
| REQ-25 | T-68, T-69, T-70 |
| REQ-26 | T-71, T-72, T-73, T-74, T-75, T-76, T-77 |
| REQ-27 | T-78, T-79, T-80 |
| REQ-28 | T-81 |
| REQ-29 | T-82, T-83, T-84 |
| REQ-30 | T-85, T-86 |
| REQ-31 | T-87, T-88, T-89 |
| REQ-32 | T-90, T-91, T-92 |
| REQ-33 | T-93 |
| REQ-34 | T-94 |
| REQ-35 | T-95 |
| REQ-36 | T-96, T-97 |
| REQ-37 | T-98 |
| REQ-38 | T-99 |
| REQ-39 | T-100, T-101, T-102 |
| REQ-40 | T-103, T-104, T-105, T-106, T-107 |
| REQ-41 | T-108, T-109, T-110 |
| REQ-42 | T-111, T-112, T-113 |

### Test to requirement

Every test serves exactly one requirement, in the order above: T-01..T-03 REQ-01; T-04..T-07 REQ-02; T-08..T-10 REQ-03;
T-11..T-14 REQ-04; T-15..T-16 REQ-05; T-17..T-22 REQ-06; T-23..T-27 REQ-07; T-28..T-30 REQ-08; T-31..T-34 REQ-09;
T-35..T-36 REQ-10; T-37..T-38 REQ-11; T-39..T-41 REQ-12; T-42..T-43 REQ-13; T-44 REQ-14; T-45..T-47 REQ-15;
T-48..T-49 REQ-16; T-50..T-51 REQ-17; T-52..T-54 REQ-18; T-55..T-57 REQ-19; T-58..T-59 REQ-20; T-60..T-62 REQ-21;
T-63..T-64 REQ-22; T-65 REQ-23; T-66..T-67 REQ-24; T-68..T-70 REQ-25; T-71..T-77 REQ-26; T-78..T-80 REQ-27; T-81 REQ-28;
T-82..T-84 REQ-29; T-85..T-86 REQ-30; T-87..T-89 REQ-31; T-90..T-92 REQ-32; T-93 REQ-33; T-94 REQ-34; T-95 REQ-35;
T-96..T-97 REQ-36; T-98 REQ-37; T-99 REQ-38; T-100..T-102 REQ-39; T-103..T-107 REQ-40; T-108..T-110 REQ-41; T-111..T-113 REQ-42.

In the code, each unit or integration test names its T-ID in its docstring, and `tests/test_traceability.py` checks
that every T-ID of type U and I in this file has a test and every T-ID of type C has a CI step that names it, and
that no test names an unknown T-ID.

## FMEA links

Each failure mode in `docs/FMEA.md` names the requirements and tests that cover it.
