# Evaluation protocol (pre-registered)

Status: written and committed before the evaluation runs and before any code. The commit that adds this file is the
registration. After the independent review of this file, changes are allowed until the first run; each such change is
listed under "Changes before the run" with its reason. After the first run, nothing in this file changes; every
difference between this protocol and what was run goes into `docs/RESULTS.md` under "Deviations".

## 1. Question

Do ranges calibrated from measured past work estimate the token cost of a new task better than the agent's own guess,
and are the ranges honest (do they hold the actual cost as often as they claim)?

## 2. Hypotheses

- **H1 (error).** On tasks finished after the cut, the calibrated estimate has a lower median absolute log error than
  the agent's guess.
- **H2 (honest ranges).** On the same tasks, the calibrated p25-p75 range holds the actual cost about 50% of the time
  and the p10-p90 range about 80% of the time.
- **H3 (learning).** Accuracy improves as a person's own finished tasks replace the starter ranges.

**H3 isn't testable on this data.** The data comes from one person over about three weeks. The starter table is made
from the same person's data, so a "starter, then own data" test would compare the data with itself. H3 stays
**not tested** in v0.1.0. Two things are run instead and neither counts as proof of H3:
- **H3-proxy (learning curve, secondary).** The size method fitted on fewer of the same person's past tasks has a
  higher error than the same method fitted on all of them. This shows only that more own data helps, inside one
  person's data.
- **What a person sees.** `ledger report` (REQ-40) shows each person's own error, coverage and bias per month and per
  10 finished tasks, from estimates stored before the work and actuals measured at `done`. That's how H3 can be seen
  on a person's own data over time.

## 3. Prior knowledge (disclosure)

The protocol isn't blind. Before writing it, the authors knew: on the same data, actual use was a median 0.30x the
guess midpoint (55 of 82 tasks below the low end, 22 inside, 5 above), and a leave-one-out backtest on all of the data
gave a median |ln error| of about 0.67-0.74 for the size method against 0.87-0.89 for guess x ratio. The writer of this
protocol also saw the counts of eligible tasks per size and per day, but no new comparison of estimates with actuals.
The time-ordered holdout below is a new test that wasn't run before. The method (size buckets, window rule) was
designed with knowledge of all of the data, so H1 and H2 here test a method fitted to earlier tasks on later tasks,
not a method designed without the data.

## 4. Data

**Source.** The author's private task archive (finished tasks with their guess, size, kind and measured use) and the
private session ledger (per-task first message and last commit times, per-session totals). The data stays outside the
repo. Only the aggregate output enters `docs/RESULTS.md`.

**Conversion to the evaluation input** (a JSON list; one object per finished task; `scripts/evaluate.py` reads it):

| Field | From |
|---|---|
| `id` | the task ID (used only to join and to break ties; never written to the output) |
| `size` | the task's size label, upper case; must be on the scale `XS, XS-S, S, S-M, M, M-L, L, L-XL, XL` |
| `kind` | the task's kind label, or null |
| `guess` | the token estimate the agent wrote before the work, `[low, high]` in tokens; the stored "guess" field when the task was calibrated before it shipped, else the stored estimate (all estimates before calibration started were guesses) |
| `actual` | measured fresh tokens tied to the task, in tokens (archive value in millions x 1,000,000) |
| `active_h`, `elapsed_h` | measured work hours (idle cap 30 min) and elapsed hours |
| `start`, `end` | the task's first message and last commit (ledger), ISO UTC; `end` falls back to the ship date at 23:59:59Z when the ledger has no end |
| `dominant_effort` | from the ledger's per-task effort split when present, else `unknown` |

**Eligibility.**
- E-all: `actual` > 0 and an `end` time.
- E1 (H1, H2, H3-proxy): E-all, plus `size` on the scale, plus `guess` with 0 < low <= high.
- No outlier removal and no trimming. Tasks that weren't finished (dropped, still open) have no actual and aren't
  eligible (survivorship: they're reported only as a count).

`docs/RESULTS.md` reports the count of tasks removed by each rule.

**Snapshot.** The input file is made once. Its SHA-256 goes into `docs/RESULTS.md` (a hash reveals nothing about the
content) so a second run can show it used the same input.

## 5. Split (time-ordered holdout)

1. Sort E1 by (`end`, `id`).
2. n = size of E1. n_train = floor(0.6 x n). The **cut** is the `end` of task number n_train in that order.
3. Training set: every E1 task with `end` <= cut (ties at the cut go to training). Test set: every E1 task with
   `end` > cut.
4. If the test set has fewer than 20 tasks, every hypothesis is **inconclusive** (too little data), and only
   descriptive numbers are reported.
5. `docs/RESULTS.md` gives the cut as an ISO week (for example `2026-W43`), not as a timestamp, plus n_train and
   n_test.

Known small leak: a test task can start before some training task ends. The rolling-origin check (section 9) has no such
leak and shows if it matters.

## 6. Arms (estimates for each test task)

All arms are fitted on the training set only, with the same code that ships (`ledger calibrate` and `ledger estimate`,
default config, no starter table).

| Arm | Estimate for a test task | Role |
|---|---|---|
| **C** calibrated | the tool's estimate from size and kind, no guess: the size + kind cell when it has n >= 5 in the window, else the size row (window rule, scaling) | primary |
| **G** guess | the task's own guess range | primary baseline |
| **R** guess x ratio | the guess midpoint x [p25, p75] of the training ratio actual / guess midpoint for that size (all sizes pooled when the size has fewer than 5) | secondary |
| **N** size-blind | [p25, p75] (and p10, p90) of all training actuals, sizes pooled | secondary (does size add information?) |

The window rule's 28 days end at the newest training task. If C can't give a range for a test task (no measured size
to scale from), C uses N for that task, and `docs/RESULTS.md` reports how often that happened.

**Midpoint** of a range `[low, high]` = (low + high) / 2, the same for every arm.

## 7. Metrics

For each test task i with actual a_i and an arm's range with midpoint m_i:
- **Error** e_i = |ln(a_i / m_i)|. Metric: median of e_i. (0.69 means a typical miss by a factor of 2.)
- **Bias** b_i = ln(a_i / m_i). Metric: median of b_i. Negative = the arm estimates too high.
- **Coverage** of p25-p75: share of tasks with low <= a_i <= high. For arm C and N also p10-p90. Arm G has no
  stated coverage level; its range coverage is reported as a description.
- Next to every result: n, and the share of all session tokens in the data window that the ledger tied to tasks
  (attribution share), because per-task actuals count only tied tokens.

**Uncertainty.** Bootstrap over test tasks: 10,000 resamples with replacement, percentile 90% interval, random seed
20261102 (Python `random.Random(20261102)`). Differences between two arms use paired resamples (the same tasks for
both arms in each resample). Quantiles use linear interpolation between order statistics.

## 8. Decision rules (registered thresholds)

Each primary test gives one verdict: **pass**, **fail** or **inconclusive**.

**H1.** D = median error of C - median error of G, with its paired 90% interval.
- Pass: the upper end of the interval < 0.
- Fail: D >= 0.
- Inconclusive: D < 0 but the interval reaches 0 or above.

**H2.** Coverage of C's p25-p75 range and of its p10-p90 range, each with its 90% interval.
- Pass: the p25-p75 interval contains 0.50 **and** the p10-p90 interval contains 0.80.
- Fail: either interval excludes its level. The result says the direction ("ranges too narrow" when coverage is
  below the level, "too wide" when above).
- (No inconclusive state: the intervals decide.)

**Bias (part of H1's report, own threshold).** Median signed log error of C with its 90% interval.
- "No material bias": the interval contains 0, or lies wholly inside [-0.25, 0.25] (a factor of about 1.28).
- "Estimates too high": the whole interval is below 0 and its lower end is below -0.25.
- "Estimates too low": the whole interval is above 0 and its upper end is above 0.25.
- The bias label doesn't change H1's verdict.

**H3-proxy (secondary).** From the training set draw 200 random subsamples (seeded as above) of size k for
k = 10, 20, 30 and all; fit C on each; compute the median error on the full test set; average over the draws.
D3 = error(all) - error(k = 10), with a 90% interval from bootstrapping the test tasks (the draws stay fixed).
- Pass: the upper end of the interval < 0. Fail: D3 >= 0. Else inconclusive.
- A pass doesn't prove H3 (section 2).

Only H1 and H2 are primary. Secondary results (R, N, H3-proxy, sections 9-10) are reported with their numbers and
don't change a primary verdict. No other test is added after the run; any extra analysis goes under "Exploratory,
not registered".

## 9. Robustness and drift (descriptive, registered)

- **Rolling origin.** In time order, for each E1 task after the first 20: fit C on the tasks whose `end` is before
  this task's `start`; record its error and coverage. Report median error and coverage overall and by bins of
  training n (20-39, 40-59, 60+). This has no leak and shows if the single cut was lucky.
- **Drift.** For the test set, median signed log error of C per ISO week (weeks with n >= 5 only).
- **Hours.** The same error and coverage for C on `active_h` and on `elapsed_h`, and for G on elapsed hours against the
  guessed wall-clock hours. Description only.

## 10. Effort and idle cap (descriptive only)

No registered test covers effort. `docs/RESULTS.md` shows effort only as a description:
- A table per size: count of tasks and median actual per dominant effort (`low`, `medium`, `high`, `xhigh`, `max`,
  `unknown`). Cells with n below 5 show the count only.
- No claim that effort changes cost or accuracy follows from this table.

Idle cap sensitivity: on the session transcripts still on the author's machine, the recorder runs with idle caps of 15,
30 and 60 minutes. Report the ratio of total active hours at 15 and at 60 against 30, and the median per-task ratio.
When too few transcripts remain (fewer than 10 tasks), report "not run" and why.

## 11. Baseline description (for the README)

On E-all tasks that have a guess, report: n, the median ratio actual / guess midpoint, and how many tasks were below the
guess's low end, inside it, and above its high end. The README's "problem in numbers" uses these counts. When they
differ from the numbers known before (0.30x; 55 / 22 / 5 of 82), the README uses the `docs/RESULTS.md` numbers.

## 12. Output and what the README may say

`scripts/evaluate.py --input <file> --out <folder>` writes `results.json` (all numbers) and the tables for
`docs/RESULTS.md`. The output holds no task IDs, titles, kinds with fewer than 5 tasks, or dates finer than an ISO
week. Two runs on the same input give identical output.

`docs/RESULTS.md` holds: the registration commit of this file, the input hash, counts per eligibility rule, the split,
each verdict with its numbers (point value, 90% interval, n), all secondary and descriptive tables, the attribution
share, and "Deviations" (empty when none).

The README section "How accurate is it?" (REQ-41) may state only numbers that are in `docs/RESULTS.md`, each with n and
its 90% interval. Each fail or inconclusive verdict is stated there with its number. H3 is stated as "not shown yet",
with a pointer to `ledger report`.

## 13. What counts as a fail of the evaluation itself

- The protocol was changed after the first run without a "Deviations" entry.
- A number in the README isn't in `docs/RESULTS.md`.
- Task-level data (IDs, titles, single-task dates or values) is in the repo.
- The run can't be repeated with the same input and seed to the same output.

Any of these blocks the release until fixed.

## Changes before the run

(none yet)
