# Failure modes and effects (FMEA)

Status: pre-registration draft, written before any code. Each row is a way the system can fail, what the person or
their agent sees, how we find out, what prevents or limits it, and the requirement and test that check it.

Scales (1 low, 5 high): **S** severity of the effect, **O** how likely it is, **D** how hard it is to detect (5 =
silent). **RPN** = S x O x D. Rows with RPN >= 30 or S = 5 need a test before v0.1.0; all rows here have one.

## Recording and hooks

| ID | Failure mode | Effect | Cause | S | O | D | RPN | Detection | Mitigation | REQ / tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FM-01 | Hook error or crash | Session shows a hook error; at worst the person's exit is slowed | Bug, bad input, missing file | 4 | 3 | 1 | 12 | Visible in the session | Catch every exception, exit 0, no stdout; guard for missing `python3` | REQ-02 / T-04, T-06 |
| FM-02 | Hook runs long | Session end feels slow | Very long transcripts, slow disk | 4 | 2 | 2 | 16 | Timing test | Internal deadline (10 s end, 30 s stop); Stop is async; 2 s budget for 5,000 messages | REQ-02, REQ-33 / T-05, T-93 |
| FM-03 | Old or missing Python | No records at all | macOS without developer tools; Python < 3.10 | 3 | 3 | 4 | 36 | `init` checks the version; `report` shows "no records in N days" | Guarded hook exits 0; README states the need; `init` prints the fix | REQ-02 / T-06, T-07 |
| FM-04 | Claude Code changes its transcript format | Zero or wrong counts, silently | Upstream change | 5 | 3 | 4 | 60 | Golden sample test in CI; status warning when a transcript has lines but no usage | Adapter isolates the format; loud warning in `report` and `estimate`; issue template | REQ-12, REQ-30 / T-40, T-41, T-85 |
| FM-05 | Streamed message counted twice | Tokens inflated | One message on several lines | 4 | 4 | 4 | 64 | Golden test | De-duplicate by message id, then request id, then uuid | REQ-03 / T-09 |
| FM-06 | Resumed session recorded twice | Tokens doubled | Resume or Stop + SessionEnd for one session | 4 | 5 | 3 | 60 | Unit test | Replace the line by session id | REQ-10 / T-35, T-36 |
| FM-07 | Two sessions end at once | One line lost | Race on the ledger file | 3 | 2 | 4 | 24 | Concurrency test | Exclusive lock; write to temp file and rename | REQ-11 / T-37 |
| FM-08 | Disk full or write error mid-write | Ledger file cut short, earlier data lost | Full disk, crash | 5 | 1 | 3 | 15 | Unit test with injected error | Temp file + rename in the same folder; old file stays on error | REQ-11 / T-38 |
| FM-09 | Partial transcript (killed session) | Last line unreadable | Kill during write | 2 | 3 | 2 | 12 | `skipped_lines` count | Skip bad lines; Stop records every 15 min | REQ-12 / T-39 |
| FM-10 | Clock skew between machines | Wrong times, negative gaps | Local clock off | 2 | 2 | 3 | 12 | Unit test | Use transcript UTC timestamps; negative gap = 0 | REQ-09, REQ-35 / T-33, T-95 |
| FM-11 | Two machines write one file | Merge conflicts, lost lines | Shared store | 4 | 2 | 2 | 16 | Sync test | One file per random machine id; push only own file after rebase | REQ-34 / T-94 |
| FM-12 | Sync remote down or slow | Hook waits on the network | Remote unreachable | 4 | 3 | 2 | 24 | Integration test with delayed push | Push in a detached child with its own timeout; local write first | REQ-15 / T-46 |

## Attribution and measurement

| ID | Failure mode | Effect | Cause | S | O | D | RPN | Detection | Mitigation | REQ / tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FM-13 | Untagged work isn't tied to a task | Per-task actuals too low; estimates too low | No `ITEM:` lines, no ID in commits | 4 | 5 | 3 | 60 | `report` shows the tied share and overhead next to every number | Tag rule in the skill; commit and touch rules; overhead factor | REQ-06, REQ-07, REQ-27 / T-17, T-23, T-75 |
| FM-14 | Wrong commit claimed | Tokens go to the wrong task | Another session committed in the same folder | 3 | 3 | 4 | 36 | Unit test | Only commits after the transcript's own `git commit` call, within the window, from this machine's reflog | REQ-07 / T-24, T-25 |
| FM-15 | Worktree deleted before the record | Commits missed, tokens in `_other` / `_after` | Cleanup before session end | 2 | 3 | 4 | 24 | Untied share rises | Stop hook records every 15 min while the worktree exists; tags don't need commits | REQ-01, REQ-06 / T-02 |
| FM-16 | Idle cap wrong for a workflow | Active hours too high or too low | Long builds, long waits | 2 | 3 | 4 | 24 | Idle-cap sensitivity check (EVALUATION 10) | Configurable `idle_cap_min`; tokens are the primary unit | REQ-09 / T-34 |
| FM-17 | ID pattern matches noise | Tokens tied to fake tasks | Pattern too broad | 3 | 2 | 3 | 18 | Unit test | Tested defaults; `init` refuses patterns that match empty text | REQ-08 / T-28, T-30 |
| FM-18 | Effort field missing or renamed | Effort split all `unknown` | Old transcripts; format change | 1 | 3 | 2 | 6 | `unknown` share visible | `unknown` bucket; effort ranges need n >= 5 | REQ-04, REQ-23 / T-12, T-65 |

## Estimates and calibration

| ID | Failure mode | Effect | Cause | S | O | D | RPN | Detection | Mitigation | REQ / tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FM-19 | Small n gives a false narrow range | Overconfident plans | Few finished tasks | 4 | 4 | 3 | 48 | n and confidence shown; coverage in `report` | Never a point; n >= 5 for own data; starter until then; rough label for scaled rows | REQ-21, REQ-22, REQ-26 / T-60, T-63, T-72 |
| FM-20 | Starter ranges don't fit the person | Early estimates off | Starter is from one workflow | 3 | 4 | 2 | 24 | Label "starter, not your data"; own accuracy in `report` | Own data replaces starter size by size | REQ-22, REQ-40 / T-63, T-106 |
| FM-21 | Hindsight: estimate edited after the work | Accuracy looks better than it is | Re-estimating at the end | 4 | 3 | 4 | 48 | `report` uses the first stored estimate | First estimate immutable; later ones appended | REQ-24, REQ-40 / T-66, T-105 |
| FM-22 | Survivorship: dropped work not counted | Ranges too low | Only finished tasks are measured | 3 | 4 | 4 | 48 | Open list in `report`; untied share | Abandoned use stays in the overhead factor; open tasks listed | REQ-27 / T-79 |
| FM-23 | Size label is a guess | Wrong bucket, wrong range | The person or agent picks the size | 3 | 4 | 4 | 48 | Evaluation arm N (does size add information?) | Documented limit; similar-task matching is a later item | REQ-39, EVALUATION 6 / T-102 |
| FM-24 | Workflow drifts (new models, new habits) | Old data misleads | Change over time | 3 | 4 | 3 | 36 | Drift table; per-month accuracy in `report` | 28-day window rule | REQ-26, REQ-40 / T-72, T-103 |
| FM-25 | Agent anchors its guess on the range | Guess baseline is no longer independent | Range shown first | 2 | 3 | 4 | 24 | Inspection of the skill | Skill: write the guess first, then run `estimate --guess` | REQ-36 / T-96 |

## Privacy and release

| ID | Failure mode | Effect | Cause | S | O | D | RPN | Detection | Mitigation | REQ / tests |
|---|---|---|---|---|---|---|---|---|---|---|
| FM-26 | Prompt text or code stored | Private content in the ledger (and in a sync remote) | A parser keeps raw text | 5 | 2 | 4 | 40 | Canary test; schema allow list | Store only counts, times, IDs; strict key allow list | REQ-13 / T-42, T-43 |
| FM-27 | Data leaves the machine | Private data sent out | Default remote, telemetry | 5 | 1 | 3 | 15 | Socket-blocking test | No network code except the opt-in sync | REQ-15 / T-45, T-47 |
| FM-28 | Private data in the repo | Author's tasks, paths or keys published | Copied files, fixtures from real transcripts | 5 | 2 | 3 | 30 | CI scan; reviewer scan of `git log -p` | Clean-folder build; invented fixtures; scan self-test | REQ-18 / T-52, T-53, T-54 |
| FM-29 | Starter table reveals one task | A single task's cost can be read | Bucket with n = 1 | 4 | 2 | 2 | 16 | CI aggregate check | Allow list of keys; n >= 5 per bucket | REQ-17 / T-50, T-51 |
| FM-30 | `forget` misses data or deletes too much | Data left behind, or transcripts lost | Wrong paths | 5 | 1 | 2 | 10 | Integration test | Delete only the three known folders; list first; never transcripts | REQ-16 / T-48, T-49 |
| FM-31 | Plugin edits the person's settings | The person's own hooks lost | Install script writes settings | 5 | 1 | 2 | 10 | Install test compares `settings.json` | Hooks only through the plugin's `hooks.json` | REQ-31 / T-88 |
| FM-32 | README claims more than the data shows | People trust wrong numbers | Marketing drift | 4 | 3 | 3 | 36 | CI number check; reviewer | Numbers only from `docs/RESULTS.md`; fails stated | REQ-41 / T-108, T-109, T-110 |
| FM-33 | Newer schema file overwritten by old code | Data loss after a downgrade | Two plugin versions on two machines | 4 | 2 | 3 | 24 | Unit test | Read-only with a warning for unknown newer versions | REQ-29 / T-84 |
