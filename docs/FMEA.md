# Failure modes and effects (FMEA)

Status: pre-registration, amended after the independent review, before any code. Each row is a way the system can fail, what the person or
their agent sees, how we find out, what prevents or limits it, and the requirement and test that check it.

Scales (1 low, 5 high): **S** severity of the effect, **O** how likely it is, **D** how hard it is to detect (5 =
silent). **RPN** = S x O x D. Rows with RPN >= 30 or S = 5 need a test before v0.1.0; all rows here have one.

## Recording and hooks

| ID | Failure mode | Effect | Cause | S | O | D | RPN | Detection | Mitigation | REQ / tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FM-01 | Hook error or crash | Session shows a hook error; at worst the person's exit is slowed | Bug, bad input, missing file | 4 | 3 | 1 | 12 | Visible in the session | Catch every exception, exit 0, no stdout; wrapper guard for missing `python3` | REQ-02 / T-04, T-06 |
| FM-02 | Hook runs long | Session end feels slow | Very long transcripts, slow disk | 4 | 2 | 2 | 16 | Timing tests | Hook process only starts a detached child (<= 200 ms); child deadline 30 s; Stop is async | REQ-02, REQ-33 / T-114, T-05, T-93 |
| FM-34 | Host kills the SessionEnd hook at its own timeout (1.5 s default) | Long sessions never record at the end; only a stale Stop record | Recording inside the hook process | 4 | 4 | 4 | 64 | Install test with a 5,000-message transcript | Detached child does the work and outlives the hook; `timeout: 5` as a backstop | REQ-01, REQ-02, REQ-31 / T-01, T-114, T-87 |
| FM-03 | Old or missing Python, or the macOS stub | A system dialog ("install developer tools") at each session end, or no records | macOS without developer tools runs the `/usr/bin/python3` stub; Python < 3.9 | 4 | 3 | 3 | 36 | `init` prints the interpreter and version it uses; `report` shows "no records in N days" | Target Python 3.9 (macOS ships 3.9.6); wrapper never runs the stub when `xcode-select -p` fails; exits 0 quietly | REQ-02, REQ-19, REQ-32 / T-06, T-07, T-115 |
| FM-04 | Claude Code changes its transcript format | Zero or wrong counts, silently | Upstream change | 5 | 3 | 4 | 60 | Golden sample test in CI; status warning when a transcript has lines but no usage | Adapter isolates the format; loud warning in `report` and `estimate`; issue template | REQ-12, REQ-30 / T-40, T-41, T-85 |
| FM-05 | Streamed message counted twice | Tokens inflated | One message on several lines | 4 | 4 | 4 | 64 | Golden test | De-duplicate by message id, then request id, then uuid | REQ-03 / T-09 |
| FM-06 | Resumed or forked session recorded twice | Tokens doubled | Resume or Stop + SessionEnd for one session; a fork copies history under a new session id | 4 | 5 | 3 | 60 | Unit and install tests | Replace the line by session id; per-machine index of message keys, a key counts once | REQ-03, REQ-10 / T-35, T-117, T-118 |
| FM-07 | Two sessions end at once | One line lost | Race on the ledger file | 3 | 2 | 4 | 24 | Concurrency test | Exclusive lock; write to temp file and rename | REQ-11 / T-37 |
| FM-35 | Lock held by a hung recorder | Every later record waits or is lost | A recorder that hangs while it holds the lock | 3 | 1 | 3 | 9 | Unit test | `flock` (released when a process dies); non-blocking retry until the deadline, then warning `lock` | REQ-11 / T-124 |
| FM-08 | Disk full or write error mid-write | Ledger file cut short, earlier data lost | Full disk, crash | 5 | 1 | 3 | 15 | Unit test with injected error | Temp file + rename in the same folder; old file stays on error | REQ-11 / T-38 |
| FM-09 | Partial transcript (killed session) | Last line unreadable | Kill during write | 2 | 3 | 2 | 12 | `skipped_lines` count | Skip bad lines; Stop records every 15 min | REQ-12 / T-39 |
| FM-36 | Huge transcript | High memory use in the child | Very long sessions | 2 | 2 | 2 | 8 | Inspection | Read line by line; keep only counts per message key | REQ-12, REQ-33 / T-137, T-93 |
| FM-37 | Transcripts deleted before backfill | Older history can't be backfilled | Claude Code's `cleanupPeriodDays` | 2 | 4 | 2 | 16 | `backfill` prints the date of the oldest transcript it found | README limit; the hooks record from install on | REQ-20 / T-58 |
| FM-38 | Stamp files build up | Many empty files in the state folder | One stamp per session | 1 | 5 | 2 | 10 | Unit test | Delete stamps older than 7 days on each record | REQ-12 / T-136 |
| FM-39 | Child deadline reached | No record for that session end | Very slow disk or huge session | 3 | 1 | 2 | 6 | Warning `deadline` in `report` | Keep the old line; write nothing partial | REQ-02 / T-05, T-116 |
| FM-40 | Windows | Hook error at each session end | No `sh`, no `fcntl` | 3 | 2 | 1 | 6 | Visible | README and `plugin.json` say not supported | REQ-32 / T-138 |
| FM-10 | Clock skew between machines | Wrong times, negative gaps | Local clock off | 2 | 2 | 3 | 12 | Unit test | Use transcript UTC timestamps; negative gap = 0 | REQ-09, REQ-35 / T-33, T-95 |
| FM-11 | Two machines write one file | Merge conflicts, lost lines | Shared store | 4 | 2 | 2 | 16 | Sync test | One file per random machine id; push only own file after rebase | REQ-34 / T-94 |
| FM-12 | Sync remote down or slow | Hook waits on the network | Remote unreachable | 4 | 3 | 2 | 24 | Integration test with delayed push | Sync only in the detached child; 60 s total; local write first | REQ-15 / T-46 |
| FM-41 | Sync shows a password or keychain prompt | A dialog or a hung child | Remote needs credentials | 4 | 3 | 2 | 24 | Integration test checks the environment | `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, SSH batch mode, no askpass | REQ-15 / T-46 |
| FM-42 | Sync fails silently | Machines drift apart; estimates lost | Auth, network, conflict | 3 | 3 | 4 | 36 | Result in `status.json`; `report` shows "last sync failed at ..." | Fixed result codes; retry once | REQ-15 / T-126 |
| FM-43 | Two syncs at once | Corrupt sync clone | Two sessions end together | 3 | 2 | 3 | 18 | Unit test | Non-blocking lock on the sync clone; skip when held | REQ-15 / T-127 |

## Attribution and measurement

| ID | Failure mode | Effect | Cause | S | O | D | RPN | Detection | Mitigation | REQ / tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FM-13 | Untagged work isn't tied to a task | Per-task actuals too low; estimates too low | No `ITEM:` lines, no ID in commits | 4 | 5 | 3 | 60 | `report` shows the tied share and overhead next to every number | Tag rule in the skill; commit and touch rules; overhead factor | REQ-06, REQ-07, REQ-27 / T-17, T-23, T-75 |
| FM-14 | Wrong commit claimed | Tokens go to the wrong task | Another session committed in the same folder | 3 | 3 | 4 | 36 | Unit test | Only commits after the transcript's own `git commit` call, within the window, from this machine's reflog; off until the person confirms the ID pattern | REQ-07 / T-24, T-25 |
| FM-44 | Repo configuration runs code | A folder named by a transcript runs `core.fsmonitor` or a pager | Running `git` in untrusted folders | 5 | 1 | 4 | 20 | Unit test patches `subprocess` | Read reflog files directly; never run `git` there | REQ-07 / T-123 |
| FM-15 | Worktree deleted before the record | Commits missed, tokens in `_other` / `_after` | Cleanup before session end | 2 | 3 | 4 | 24 | Untied share rises | Branch reflogs in the common dir survive the worktree; Stop records every 15 min; tags don't need commits | REQ-01, REQ-06, REQ-07 / T-02, T-123 |
| FM-16 | Idle cap wrong for a workflow | Active hours too high or too low | Long builds, long waits | 2 | 3 | 4 | 24 | Idle-cap sensitivity check (EVALUATION 10) | Configurable `idle_cap_min`; tokens are the primary unit | REQ-09 / T-34 |
| FM-17 | ID pattern matches noise | Tokens tied to fake tasks (`UTF-8`, `SHA-256`, `GPT-4`, PR numbers) | Pattern too broad | 3 | 3 | 3 | 27 | Unit test | Prefix pattern from one example ID; stoplist; `#123` and `K42` off by default; commit matching only after confirmation | REQ-08 / T-28, T-30, T-122 |
| FM-45 | A pattern with catastrophic backtracking | The child hangs on a long line | User-typed pattern | 3 | 1 | 2 | 6 | Unit test | `init` times each pattern on a 10 kB adversarial string; only the first 200 chars of a text are searched | REQ-06, REQ-08 / T-120, T-121 |
| FM-46 | Free text in a process name | Prompt text reaches the ledger and the sync remote | `process:<anything>` | 4 | 2 | 3 | 24 | Unit test | `<name>` must match `[a-z0-9-]{1,32}`; role must be one of four words | REQ-06 / T-120 |
| FM-18 | Effort field missing or renamed | Effort split all `unknown` | Old transcripts; format change | 1 | 3 | 2 | 6 | `unknown` share visible | `unknown` bucket; dominant effort needs a known share >= 0.5; effort ranges need n >= 5 | REQ-04, REQ-23 / T-12, T-14, T-65 |
| FM-47 | Actual records missing attribution, not cost | Ranges far too low; tasks of 0.01 M tokens look real | The build ran in a session the ledger didn't see; only the lead's share is tied | 4 | 4 | 3 | 48 | `measured` rule at `done`; count in `report` | Tasks with lead share > 0.5 or no build/review/fix tokens are left out of calibration | REQ-25, REQ-27 / T-129 |

## Estimates and calibration

| ID | Failure mode | Effect | Cause | S | O | D | RPN | Detection | Mitigation | REQ / tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FM-19 | Small n gives a false narrow range | Overconfident plans; sample quantiles of n tasks hold a new task less often than their nominal level | Few finished tasks | 4 | 4 | 3 | 48 | n and confidence shown; coverage in `report` | Small-n widening of the quantile levels, label when clipped; never a point; n >= 5 for own data; starter until then | REQ-21, REQ-22, REQ-26 / T-60, T-63, T-72, T-130 |
| FM-20 | Starter ranges don't fit the person | Early estimates off | Starter is from one workflow | 3 | 4 | 2 | 24 | Label "starter, not your data"; own accuracy in `report` | Own data replaces starter size by size | REQ-22, REQ-40 / T-63, T-106 |
| FM-21 | Hindsight: estimate edited or made after the work started | Accuracy looks better than it is | Re-estimating at the end | 4 | 3 | 4 | 48 | `report` uses the first stored estimate, "before work" only | Append-only events; earliest over all machines; estimates after first message + 10 min shown apart | REQ-24, REQ-40 / T-66, T-105, T-128, T-132 |
| FM-22 | Survivorship: dropped work not counted | Ranges too low | Only finished tasks are measured | 3 | 4 | 4 | 48 | Open list in `report`; untied share | Abandoned use stays in the overhead factor; open tasks listed | REQ-27 / T-79 |
| FM-23 | Size label is a guess | Wrong bucket, wrong range | The person or agent picks the size | 3 | 4 | 4 | 48 | Evaluation arm N (does size add information?) | Documented limit; similar-task matching is a later item | REQ-39, EVALUATION 6 / T-102 |
| FM-24 | Workflow drifts (new models, new habits) | Old data misleads | Change over time | 3 | 4 | 3 | 36 | Drift table; per-month accuracy in `report` | 28-day window rule | REQ-26, REQ-40 / T-72, T-103 |
| FM-25 | Agent anchors its guess on the range | Guess baseline is no longer independent | Range shown first | 2 | 3 | 4 | 24 | Inspection of the skill | Skill: write the guess first, then run `estimate --guess` | REQ-36 / T-96 |

## Privacy and release

| ID | Failure mode | Effect | Cause | S | O | D | RPN | Detection | Mitigation | REQ / tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FM-26 | Prompt text or code stored | Private content in the ledger (and in a sync remote) | A parser keeps raw text | 5 | 2 | 4 | 40 | Canary test; schema allow list | Store only counts, times, IDs; strict key allow list | REQ-13 / T-42, T-43 |
| FM-27 | Data leaves the machine | Private data sent out | Default remote, telemetry | 5 | 1 | 3 | 15 | Socket-blocking test | No network code except the opt-in sync | REQ-15 / T-45, T-47 |
| FM-28 | Private data in the repo | Author's tasks, paths or keys published | Copied files, fixtures from real transcripts; a private name list put in a scan script | 5 | 2 | 3 | 30 | Generic CI scan; the lead's private list run from outside the repo | Clean-folder build; invented fixtures; canaries built at run time; no private list in the repo | REQ-18 / T-52, T-53, T-54 |
| FM-29 | A shipped or shown number reveals one task | A single task's cost can be read | Bucket or table cell with n < 5 | 4 | 2 | 2 | 16 | CI checker on `starter.json` and `results.json`; `report --aggregate` test | Small cells show only their count everywhere; p10/p90 only at n >= 10; 2 significant figures; starter updates in steps of 5+ tasks | REQ-17, REQ-27 / T-50, T-51, T-133, T-135 |
| FM-48 | Sessions from client work recorded | Data about work the person wants kept apart | Hooks record every folder | 3 | 3 | 2 | 18 | Unit test | `ignore_paths` in the config | REQ-43 / T-125 |
| FM-30 | `forget` misses data or deletes too much | Data left behind, or transcripts lost | Wrong paths | 5 | 1 | 2 | 10 | Integration test | Delete only the three known folders; list first; never transcripts | REQ-16 / T-48, T-49 |
| FM-31 | Plugin edits the person's settings | The person's own hooks lost | Install script writes settings | 5 | 1 | 2 | 10 | Install test compares `settings.json` | Hooks only through the plugin's `hooks.json` | REQ-31 / T-88 |
| FM-32 | README claims more than the data shows | People trust wrong numbers | Marketing drift; a hard-coded baseline | 4 | 3 | 3 | 36 | CI number check over the whole section; reviewer | Numbers only from `docs/RESULTS.md`, baseline included; H1a-c stated together; fails stated; attribution caveat | REQ-41 / T-108, T-109, T-110 |
| FM-33 | Newer schema file overwritten by old code | Data loss after a downgrade | Two plugin versions on two machines | 4 | 2 | 3 | 24 | Unit test | Read-only with a warning for unknown newer versions | REQ-29 / T-84 |
