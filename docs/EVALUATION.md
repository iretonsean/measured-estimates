# Evaluation protocol (pre-registered)

Status: registered in the first documents commit, amended once after the independent review and before any evaluation
run (see "Changes before the run"). After the first run, nothing in this file changes; every difference between this
protocol and what was run goes into `docs/RESULTS.md` under "Deviations".

## 1. Question

Do ranges calibrated from measured past work estimate the token cost of a new task better than the agent's own guess,
better than the guess with its average bias removed, and better than ranges that ignore the task's size? And are the
ranges honest (do they hold the actual cost as often as they claim)?

## 2. Hypotheses

- **H1 (error).** On tasks the method hasn't seen, the calibrated estimate (arm C) has a lower median error than:
  - **H1a** the agent's guess (arm G);
  - **H1b** the guess with its average bias removed (arm R);
  - **H1c** a size-blind range (arm N).
  H1a alone says little: the guesses are known to be too high (section 3), so any method that scales down beats them.
  H1b asks whether size buckets beat a bias-corrected guess. H1c asks whether the size label adds information.
- **H2 (honest ranges).** The calibrated 50% range holds the actual cost about 50% of the time, and the 80% range about
  80% of the time.
- **H3 (learning).** Accuracy improves as a person's own finished tasks replace the starter ranges.

**H3 isn't testable on this data.** The data comes from one person over about three weeks. The starter table is made
from the same person's data, so a "starter, then own data" test would compare the data with itself. H3 stays
**not tested** in v0.1.0. Two things are run instead, and neither counts as proof of H3:
- **H3-proxy (secondary).** The size method fitted on fewer of the same person's past tasks has a higher error than the
  same method fitted on all of them. This shows only that more own data helps, inside one person's data.
- **What a person sees.** `ledger report` (REQ-40) shows each person's own error, coverage and bias per month and per
  10 finished tasks, from estimates stored before the work and actuals measured at `done`. That's how H3 can be seen
  on a person's own data over time.

## 3. Prior knowledge (disclosure)

The protocol isn't blind.

**Known to the authors before writing it.** On the same data, a script that ran on its own 28-day window found actual
use at a median 0.30x the guess (arithmetic) midpoint, with 55 of 82 tasks below the guessed range, 22 inside and 5
above. A leave-one-out backtest on all of the data gave a median |ln error| of about 0.67-0.74 for the size method
against 0.87-0.89 for guess x ratio. Those numbers used the arithmetic midpoint and no small-n widening, so they aren't
comparable with the numbers this protocol produces. The writer of this protocol also saw the counts of eligible tasks
per size and per day, but no new comparison of estimates with actuals.

**Reviewer disclosure (verbatim intent).** To check the split and the measurement validity, the independent reviewer
read the private archive and session ledger and computed: the eligibility counts; the first registered 60/40 split;
the size mix, ship days, distribution of actuals, role shares and effort coverage on each side of that cut; and the
ratio of actual to guess midpoint (arm G only) on each side. The reviewer didn't fit or compute arms C, R or N and
didn't compare arms. The reviewer didn't give the G ratio per side to the builder. The numbers the reviewer reported
are descriptive and contain no task IDs. Of them, these shaped this amendment: 17 of 28 test tasks in the first split
had actuals below 0.05 M tokens, mostly lead share from one session; 20 of 28 test tasks shipped on one day; the
known-effort share differs strongly between the two sides of the cut.

**Rules added after seeing those descriptions** (not after any arm comparison): the measurement-quality rule E1-m
(section 4), the 48-hour snapshot rule, the cluster bootstrap by day, the rolling origin as the primary design, the
geometric midpoint, small-n widening of the ranges, and the arms R and N as registered comparators.

**Selection.** The tasks without a size and a guess are left out. On the reviewer's count these are archive entries
added in one clean-up, mostly features, with a higher median actual than the eligible tasks; the eligible tasks are
mostly bugs and interface work. The results apply to tasks that had a size and a guess when they were planned.

**Hindsight risks that can't be checked.** The archive keeps the size label from ship time, which may have been
changed during the work. The guess may have been edited during the work. Both would make G and C look better than they
are for a person who labels and guesses only once, up front.

## 4. Data

**Source.** The author's private task archive (finished tasks with their guess, size, kind and measured use) and the
private session ledger (per-task first message and last commit times, per-task role and effort split, per-session
totals). The data stays outside the repo. Only aggregate output enters `docs/RESULTS.md`.

**Conversion to the evaluation input** (a JSON object `{"snapshot": <ISO UTC>, "tasks": [...], "weeks": [...]}`;
`scripts/evaluate.py` reads it):

| Field | From |
|---|---|
| `id` | the task ID (used only to join and to break ties; never written to the output) |
| `size` | the task's size label, upper case, on the scale `XS, XS-S, S, S-M, M, M-L, L, L-XL, XL`, else null |
| `kind` | the task's kind label, or null |
| `guess` | the token estimate written before the work, `[low, high]` in tokens: the stored guess field when the task was calibrated before it shipped, else the stored estimate (all estimates before calibration started were guesses) |
| `actual` | measured fresh tokens tied to the task, in tokens (archive value in millions x 1,000,000) |
| `by_role` | the actual split into build, review, fix and lead, in tokens |
| `active_h`, `elapsed_h` | measured work hours (idle cap 30 min) and elapsed hours |
| `start`, `end` | the task's first message and last commit from the ledger, ISO UTC. When the ledger has no `end`, the ship date at 23:59:59Z, except for entries added by an archive clean-up (they have an `archived` field): those have no `end` |
| `by_effort` | the ledger's per-task fresh tokens per effort level, when present |
| `weeks` (top level) | per ISO week: all session fresh tokens, and the part tied to tasks (from the ledger lines of all machines) |

**Eligibility.**
- E-all: `actual` > 0, an `end` time, and `end` more than 48 hours before the snapshot (the newest tasks may still miss
  sessions that weren't recorded yet).
- E1: E-all, plus `size` on the scale, plus `guess` with 0 < low <= high.
- **E1-m (primary population):** E1, plus build + review + fix tokens > 0, plus lead share (lead / actual) <= 0.5.
  A task that fails this rule has an actual that mostly records where the ledger saw only the lead (the build ran in a
  session the ledger didn't see), not its cost. The shipped `done` uses the same rule (REQ-25).
- No outlier removal and no trimming beyond these rules. Tasks that weren't finished (dropped, still open) have no
  actual and aren't eligible (survivorship: they're reported only as a count where known).

`docs/RESULTS.md` reports the count removed by each rule, and the kind mix and median actual of E1, E1-m and the
excluded tasks (small-cell rule applies).

**Snapshot.** The input file is made once. Its SHA-256 and the snapshot's ISO week go into `docs/RESULTS.md` (a hash
reveals nothing about the content) so a second run can show it used the same input.

## 5. Design

**Primary: rolling origin.** Sort E1-m by (`end`, `id`). For each task t, its training set is every E1-m task whose
`end` is before t's `start`. Task t is a test point when its training set has at least 20 tasks. Each test point gets
the estimate of each arm fitted on its own training set. This uses no information from after the task started.

**Secondary: single cut (60/40).** Sort E1-m by (`end`, `id`); n_train = floor(0.6 n); the cut is the `end` of task
number n_train; training = tasks with `end` <= cut, test = tasks with `end` > cut. A test task can start before some
training tasks end (a small leak); that's why this design is secondary.

**Minimum data.** In each design, when there are fewer than 20 test points or the test points fall on fewer than 8
distinct UTC days, every verdict of that design is **inconclusive** (too little data) and only descriptive numbers are
reported. The cut is reported as an ISO week, never as a timestamp.

## 6. Arms

Every arm is fitted on the training set only. Arm C runs the shipped code (`calibrate` and `estimate` from the
package, default config, no starter table, small-n widening on); `evaluate.py` imports it and doesn't re-implement it.

| Arm | Estimate for a test task | Role |
|---|---|---|
| **C** calibrated | the tool's estimate from size and kind, no guess: the size + kind cell when it has n >= 5 in the window, else the size row (window rule, scaling, widening) | tested method |
| **G** guess | the task's own guess range | comparator (H1a) |
| **R** guess x ratio | the guess midpoint x the training ratios actual / guess midpoint, at the same widened 50% and 80% levels, for that size when it has n >= 5 training tasks, else all sizes pooled | comparator (H1b) |
| **N** size-blind | the widened 50% and 80% ranges of all training actuals, sizes pooled | comparator (H1c) |

When C can't give a range for a test task (no measured size to scale from), C uses N for that task, and
`docs/RESULTS.md` reports how often that happened.

**Midpoint** of a range `[low, high]` = sqrt(low x high), the same for every arm. For the 80% coverage of C, R and N
the 80% range is used; error and bias use the 50% range's midpoint.

## 7. Metrics and uncertainty

For each test point i with actual a_i and an arm's 50% range with midpoint m_i:
- **Error** e_i = |ln(a_i / m_i)|. Metric: the median of e_i. (0.69 means a typical miss by a factor of 2.)
- **Bias** b_i = ln(a_i / m_i). Metric: the median of b_i. Negative = the arm estimates too high.
- **Coverage**: the share of test points with low <= a_i <= high, for the 50% range and the 80% range. Arm G has no
  stated level; its coverage is a description.
- Next to every result: n, the number of distinct days, and the attribution share (tokens tied to tasks / all
  tokens) of the weeks the test points fall in, because actuals count only tied tokens.

**Uncertainty: cluster bootstrap.** Tasks ship in batches and share sessions, so they aren't independent. Resample the
UTC days of `end` of the test points with replacement, and keep every test point of each drawn day; compute every
metric on the resample. 10,000 resamples, seed 20261102 (Python `random.Random(20261102)`, days drawn in sorted order
of the day list). Comparisons between arms use the same resamples for both arms (paired). Intervals are 90% percentile
intervals. Quantiles use linear interpolation between order statistics.

## 8. Decision rules (registered thresholds)

Each test gives one verdict: **pass**, **fail** or **inconclusive**. Only the primary design decides; the secondary
design and the sensitivity analyses are reported next to it.

**H1 (family of three, Holm, family error 0.10).** For X in G, R, N: D_X = median error of C - median error of X, and
its paired 90% interval. One-sided bootstrap p-value p_X = (1 + number of resamples with D_X* >= 0) / (1 + 10,000).
Holm: sort the three p-values from small to large; the k-th smallest (k = 1, 2, 3) is significant when it and every
smaller one are at most 0.10 / (4 - k).
- Pass: D_X < 0 and p_X is significant under Holm.
- Fail: D_X >= 0. Labelled "C worse" when the lower end of the 90% interval is above 0.
- Inconclusive: any other result.
H1a, H1b and H1c are reported together, always; the README states all three.

**H2 (two levels).** For each level L in 0.50 and 0.80: the coverage of C's L range with its 90% interval.
- Pass at L: the interval contains L and lies inside [L - 0.20, L + 0.20].
- Fail at L: the interval excludes L. Labelled "ranges too narrow" when coverage is below L, "too wide" when above.
- Inconclusive at L: any other result.
- H2 passes when both levels pass, fails when either level fails, else is inconclusive. (This is an
  intersection-union test and needs no correction.)

**Bias label for C (reported with H1, doesn't change a verdict).** Median of b_i with its 90% interval.
- "No material bias": the interval lies inside [-0.25, 0.25].
- "Estimates too high" / "too low": the interval excludes 0 and the point is beyond -0.25 / +0.25.
- "Small bias": the interval excludes 0 and the point is within [-0.25, 0.25].
- "Unclear": any other result.

**Error control.** H1 as a family and H2 are each held to at most 10% false-pass error (one-sided). Secondary results
don't change a primary verdict.

**H3-proxy (secondary, on the 60/40 cut).** From the training set draw 200 random subsamples (seeded as above) of size
k for k = 10, 20, 30 and all; fit C on each; compute the median error on the full test set; average over the draws.
D3 = error(all) - error(k = 10), with a 90% interval from the cluster bootstrap over test days (the draws stay fixed).
- Pass: the upper end of the interval < 0. Fail: D3 >= 0. Else inconclusive.
- Report, per k, the share of test tasks where C fell back to scaling or to N. The subsamples are random, not in time
  order. A pass doesn't prove H3 (section 2).

No other test is added after the run; any extra analysis goes under "Exploratory, not registered".

## 9. Sensitivity and robustness (registered, descriptive)

Each repeats the H1 and H2 numbers (no verdicts) under one change:
1. The 60/40 cut design (section 5).
2. Population E1 instead of E1-m, in both designs.
3. Arithmetic midpoint (low + high) / 2 instead of the geometric midpoint.
4. C's median (p50) as the midpoint of C.
5. **Attribution:** each actual divided by the attribution share of the ISO week of its `end` (an upper bound that
   gives untied tokens back in proportion). If an H1 verdict would change, the README says so. The attribution share
   of the training period and of the test period is reported apart (the tagging habit changed over time).
6. **Calibration curve:** for C, the coverage of the central ranges at nominal 10%, 20%, ..., 80% (widened the same
   way) against the nominal level.
7. **Drift:** median bias of C per ISO week of the test points, for weeks with n >= 5; when fewer than 3 weeks
   qualify, the result says "not enough weeks" and shows no trend.
8. **Hours:** the same error and coverage for C on active hours and on elapsed hours. Description only.

## 10. Effort and idle cap (descriptive only)

No registered test covers effort. Effort is confounded with time in this data: older ledger lines and some machines
lack effort, and `unknown` means "transcript gone before the effort backfill", not "no effort set".
- Dominant effort per task: from `by_effort`, over the known levels only, and only when the known share is >= 0.5;
  else `unknown`. Ties go to the alphabetically lower level.
- Report the known-effort share per side of the 60/40 cut.
- A table per size: count of tasks and median actual per dominant effort. Cells with n below 5 show the count only.
- No claim that effort changes cost or accuracy follows from this table, and no effort range is fitted from it.

Idle cap sensitivity: on the session transcripts still on the author's machine, the recorder runs with idle caps of 15,
30 and 60 minutes. Report the ratio of total active hours at 15 and at 60 against 30, and the median per-session ratio.
When fewer than 10 sessions remain, report "not run" and why.

## 11. Baseline (for the README)

On E1 (equal to E-all with a guess on today's data) and again on E1-m:
- n and the number of days;
- the median ratio actual / guess midpoint (geometric midpoint; the arithmetic one as a sensitivity);
- how many tasks were below the guess's low end, inside it (low <= actual <= high), and above its high end;
- the attribution-independent upper bound: all session tokens in the ISO weeks in which the E1 tasks ended, divided by
  the sum of the guess midpoints of the E1 tasks that ended in those weeks (the total doesn't depend on attribution,
  so it's an upper bound on the true ratio; it also holds work that isn't a task);
- the attribution share of those weeks.

The README's "problem in numbers" uses only these numbers, next to the attribution caveat (REQ-41).

## 12. Output and what the README may say

`scripts/evaluate.py --input <file> --out <folder>` writes `results.json` (all numbers) and `results.md` (the tables
for `docs/RESULTS.md`). The output holds no task IDs or titles, no dates finer than an ISO week, and no value computed
from fewer than 5 tasks (such cells show only their count; p10/p90 only when n >= 10). An output checker fails on any
of these (REQ-17, T-101, T-135). Two runs on the same input give identical output.

`docs/RESULTS.md` holds: the registration commits of this file, the input hash, the snapshot week, counts per
eligibility rule, the designs and their n and days, each verdict with its numbers (point, 90% interval, n, days,
p-value for H1), the bias label, all secondary and descriptive tables, the attribution shares, and "Deviations"
(empty when none).

The README section "How accurate is it?" (REQ-41) may state only numbers that are in `docs/RESULTS.md`, each with n,
days and its 90% interval. It states H1a, H1b and H1c together. Each fail or inconclusive verdict is stated there with
its number. H3 is stated as "not shown yet", with a pointer to `ledger report`.

## 13. What counts as a fail of the evaluation itself

- The protocol was changed after the first run without a "Deviations" entry.
- A number in the README isn't in `docs/RESULTS.md`.
- Task-level data (IDs, titles, single-task dates or values) or a small cell is in the repo.
- The run can't be repeated with the same input and seed to the same output.

Any of these blocks the release until fixed.

## Changes before the run

1. 2026-11-02, after the independent review of the first registration (11 must-fix, 16 should-fix): added E1-m and the
   48-hour snapshot rule; no ship-date fallback for clean-up entries; rolling origin primary, 60/40 cut secondary;
   cluster bootstrap by day and the 8-day minimum; geometric midpoint; small-n widening (shipped in `calibrate`); arms
   R and N as registered comparators with Holm control (H1a-c); three-state H2 with a ±0.20 band; new bias labels;
   H3-proxy fallback report; sensitivity analyses 1-8; effort protocol; baseline defined on E1 and E1-m with the
   attribution-independent upper bound; global small-cell rule; reviewer disclosure in section 3. No evaluation had
   run.
