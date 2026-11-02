# Results

Aggregate output of the pre-registered evaluation (`docs/EVALUATION.md`), run on the author's own data. The data stays
outside this repo. This file holds no task IDs, titles, single-task values or dates finer than an ISO week, and no
value from fewer than 5 tasks. `docs/results.json` holds the same numbers.

- Protocol registered in commit `cd59996`, amended once before any run in commit `d6b6962`.
- Code: commit `d41e8e3`, plus one fix before the final run (see "Deviations").
- Input: one snapshot; SHA-256 below. Seed 20261102.

## Summary

| Test | Verdict | Numbers (n 30 test points on 5 days) |
|---|---|---|
| H1a calibrated vs guess | inconclusive (too little data) | D = -0.22 [-0.50, 0.12] |
| H1b calibrated vs guess x ratio | inconclusive (too little data) | D = -0.08 [-0.29, 0.10] |
| H1c calibrated vs size-blind | inconclusive (too little data) | D = -0.21 [-0.45, 0.16] |
| H2 honest ranges | inconclusive (too little data) | 50% range held 67% [31%, 81%]; 80% range held 93% [86%, 100%] |
| H3 learning | not tested (one person's data) | see `ledger report` on your own data |
| H3-proxy (secondary) | inconclusive (too little data) | see below |

**Why inconclusive.** The registered minimum is 20 test points on at least 8 distinct days. The primary design has 30
test points, but they fall on 5 days, because the tasks shipped in batches. So no verdict is a pass or a fail. The
point values favour the calibrated ranges (median error 0.34 against 0.56 for the guesses; an error of 0.69
means a miss by a factor of 2), but the 90% intervals
reach above 0, and the sample is too small to tell.

**What this means for a reader.** The data doesn't yet show that calibration beats guesses. It shows a problem with
the guesses (Baseline below). The calibrated 50% and 80% ranges held the actual cost 67% and 93% of the time, but the
intervals are wide. More days of finished tasks are needed. The same protocol runs again when the data has them.

## Full output
Input SHA-256: `7c22a846955b33b1ff1137353a0f711e6deb3549ac732195cdad60c6d5533661`. Snapshot: 2026-W45. Seed 20261102, 10000 cluster-bootstrap resamples (by day).

### Data

Input tasks: 144. Removed: 0 without an actual, 0 without an end time, 1 within 48 h of the snapshot. E-all: 143. Without size or guess: 61. E1: 82. Not measured (lead share > 0.5 or no build/review/fix tokens): 27. **E1-m: 55.**

- E1: n 82; kinds bug 35, dev 7, feature 21, ux 13; other kinds 6; median actual 0.39 M
- E1m: n 55; kinds bug 18, dev 7, feature 18, ux 7; other kinds 5; median actual 0.56 M
- excluded_no_size_or_guess: n 61; kinds dev 13, feature 40, research 5; other kinds 3; median actual 0.64 M

### Baseline (guesses before calibration)

| Population | n | days | median actual / guess midpoint | arithmetic midpoint | below / inside / above | upper bound (all tokens / guesses) | tokens tied to tasks |
|---|---|---|---|---|---|---|---|
| E1 | 82 | 8 | 0.44 | 0.39 | 51 / 25 / 6 | 1.93 | 69% |
| E1m | 55 | 8 | 0.55 | 0.47 | 30 / 20 / 5 | 2.36 | 69% |

### Primary: rolling origin on E1-m

Test points: 30 on 5 days (minimum 20 points and 8 days: NOT met). C fell back to scaling or N for 4 points (to N: 0).

| Arm | n | days | median error (90% CI) | bias (90% CI) | 50% range held (90% CI) | 80% range held (90% CI) |
|---|---|---|---|---|---|---|
| C calibrated | 30 | 5 | 0.34 [0.30, 0.60] | 0.00 [-0.24, 0.60] | 67% [31%, 81%] | 93% [86%, 100%] |
| G guess | 30 | 5 | 0.56 [0.37, 0.80] | -0.46 [-0.80, 0.10] | 40% [13%, 67%] | - - |
| R guess x ratio | 30 | 5 | 0.42 [0.24, 0.95] | 0.26 [-0.11, 0.95] | 67% [33%, 81%] | 93% [86%, 100%] |
| N size-blind | 30 | 5 | 0.55 [0.33, 0.75] | 0.34 [0.12, 0.60] | 67% [54%, 85%] | 93% [92%, 100%] |

| Hypothesis | D = error(C) - error(X) (90% CI) | p (one-sided) | Holm threshold | verdict |
|---|---|---|---|---|
| H1a C vs G | -0.22 [-0.50, 0.12] | 0.18 | 0.0333 | **inconclusive (too little data)** |
| H1b C vs R | -0.08 [-0.29, 0.10] | 0.32 | 0.1 | **inconclusive (too little data)** |
| H1c C vs N | -0.21 [-0.45, 0.16] | 0.22 | 0.05 | **inconclusive (too little data)** |

| H2 level | coverage of C (90% CI) | verdict |
|---|---|---|
| 50% | 67% [31%, 81%] | inconclusive (too little data) |
| 80% | 93% [86%, 100%] | inconclusive (too little data) |

**H2: inconclusive.** Bias label for C: **unclear**.

### Secondary: 60/40 cut on E1-m

Training 33, test 22 on 4 days, cut in 2026-W42.

| Arm | n | days | median error (90% CI) | bias (90% CI) | 50% range held (90% CI) | 80% range held (90% CI) |
|---|---|---|---|---|---|---|
| C calibrated | 22 | 4 | 0.65 [0.25, 0.68] | 0.37 [-0.06, 0.65] | 59% [40%, 75%] | 95% [88%, 100%] |
| G guess | 22 | 4 | 0.39 [0.33, 0.50] | -0.34 [-0.44, -0.24] | 59% [40%, 75%] | - - |
| R guess x ratio | 22 | 4 | 0.65 [0.34, 0.72] | 0.54 [0.23, 0.63] | 59% [40%, 75%] | 100% [100%, 100%] |
| N size-blind | 22 | 4 | 0.44 [0.43, 0.46] | 0.25 [0.08, 0.45] | 73% [62%, 79%] | 95% [93%, 100%] |

| Hypothesis | D (90% CI) | p | verdict (secondary, not deciding) |
|---|---|---|---|
| H1a | 0.26 [-0.14, 0.35] | 0.79 | inconclusive (too little data) |
| H1b | 0.00 [-0.18, 0.01] | 0.63 | inconclusive (too little data) |
| H1c | 0.20 [-0.20, 0.25] | 0.74 | inconclusive (too little data) |

H2 (secondary): inconclusive; bias label unclear.

### Sensitivity (numbers only, no verdicts)

**E1_rolling** (n 47, days 5)

| Arm | n | days | median error (90% CI) | bias (90% CI) | 50% range held (90% CI) | 80% range held (90% CI) |
|---|---|---|---|---|---|---|
| C calibrated | 47 | 5 | 0.53 [0.34, 0.87] | -0.16 [-0.30, 0.15] | 53% [40%, 74%] | 70% [55%, 95%] |
| G guess | 47 | 5 | 0.71 [0.51, 0.75] | -0.62 [-0.75, -0.18] | 34% [24%, 45%] | - - |
| R guess x ratio | 47 | 5 | 0.54 [0.27, 0.88] | 0.10 [-0.07, 0.54] | 53% [32%, 76%] | 79% [66%, 100%] |
| N size-blind | 47 | 5 | 0.70 [0.63, 1.03] | 0.13 [-0.54, 0.66] | 57% [47%, 76%] | 70% [56%, 100%] |

**E1_cut** (n 27, days 2)

| Arm | n | days | median error (90% CI) | bias (90% CI) | 50% range held (90% CI) | 80% range held (90% CI) |
|---|---|---|---|---|---|---|
| C calibrated | 27 | 2 | 2.63 [0.43, 2.67] | -2.63 [-2.67, 0.27] | 22% [20%, 50%] | 30% [24%, 100%] |
| G guess | 27 | 2 | 2.67 [0.22, 2.67] | -2.67 [-2.67, 0.04] | 30% [24%, 100%] | - - |
| R guess x ratio | 27 | 2 | 2.11 [0.82, 2.11] | -2.11 [-2.11, 0.82] | 22% [0%, 24%] | 37% [32%, 100%] |
| N size-blind | 27 | 2 | 3.71 [0.33, 3.71] | -3.71 [-3.71, 0.33] | 33% [28%, 100%] | 37% [32%, 100%] |

**arithmetic_midpoint** (n 30, days 5)

| Arm | n | days | median error (90% CI) | bias (90% CI) | 50% range held (90% CI) | 80% range held (90% CI) |
|---|---|---|---|---|---|---|
| C calibrated | 30 | 5 | 0.42 [0.27, 0.57] | -0.16 [-0.43, 0.44] | 67% [31%, 81%] | 93% [86%, 100%] |
| G guess | 30 | 5 | 0.59 [0.39, 0.91] | -0.59 [-0.91, -0.02] | 40% [13%, 67%] | - - |
| R guess x ratio | 30 | 5 | 0.43 [0.32, 0.67] | -0.04 [-0.31, 0.59] | 67% [33%, 81%] | 93% [86%, 100%] |
| N size-blind | 30 | 5 | 0.35 [0.26, 0.46] | 0.10 [-0.12, 0.31] | 67% [54%, 85%] | 93% [92%, 100%] |

**C_p50_midpoint** (n 30, days 5)

| Arm | n | days | median error (90% CI) | bias (90% CI) | 50% range held (90% CI) | 80% range held (90% CI) |
|---|---|---|---|---|---|---|
| C (median as midpoint) | 30 | 5 | 0.39 [0.14, 0.75] | 0.12 [-0.00, 0.74] | 67% [31%, 81%] | 93% [86%, 100%] |
| G guess | 30 | 5 | 0.56 [0.37, 0.80] | -0.46 [-0.80, 0.10] | 40% [13%, 67%] | - - |
| R guess x ratio | 30 | 5 | 0.42 [0.24, 0.95] | 0.26 [-0.11, 0.95] | 67% [33%, 81%] | 93% [86%, 100%] |
| N size-blind | 30 | 5 | 0.55 [0.33, 0.75] | 0.34 [0.12, 0.60] | 67% [54%, 85%] | 93% [92%, 100%] |

**attribution_scaled** (n 30, days 5)

| Arm | n | days | median error (90% CI) | bias (90% CI) | 50% range held (90% CI) | 80% range held (90% CI) |
|---|---|---|---|---|---|---|
| C calibrated | 30 | 5 | 0.46 [0.35, 0.82] | 0.35 [0.32, 0.82] | 63% [45%, 74%] | 93% [86%, 100%] |
| G guess | 30 | 5 | 0.30 [0.22, 0.59] | -0.10 [-0.23, 0.33] | 70% [31%, 82%] | - - |
| R guess x ratio | 30 | 5 | 0.75 [0.57, 1.17] | 0.65 [0.46, 1.17] | 53% [31%, 65%] | 93% [92%, 100%] |
| N size-blind | 30 | 5 | 0.89 [0.49, 1.32] | 0.76 [0.35, 1.12] | 37% [7%, 62%] | 90% [85%, 100%] |

Tokens tied to tasks: training weeks 56%, test weeks 69%, primary test weeks 69%.

Calibration curve of C (nominal vs observed coverage):

| nominal | n | observed |
|---|---|---|
| 10% | 30 | 17% |
| 20% | 30 | 33% |
| 30% | 30 | 47% |
| 40% | 30 | 60% |
| 50% | 30 | 67% |
| 60% | 30 | 80% |
| 70% | 30 | 90% |
| 80% | 30 | 93% |

Drift (median bias of C per week, n >= 5): not enough weeks

- 2026-W42: n 12, -0.24
- 2026-W43: n 18, 0.32

Hours (C): active_h: n 30, median error 0.44, 50% range held 57%; elapsed_h: n 30, median error 0.72, 50% range held 43%

### H3-proxy (secondary, 60/40 cut; not a test of H3)

| k | draws | mean median error | fallback share |
|---|---|---|---|
| 10 | 200 | 0.75 | 56% |
| 20 | 200 | 0.70 | 24% |
| 30 | 200 | 0.65 | 23% |
| all | 1 | 0.65 | 23% |

D3 = error(all) - error(k = 10) = -0.10 [-0.27, -0.08], n 22, 4 days: **inconclusive (too little data)** (random subsamples, not in time order; a pass does not prove H3).

### Effort (description only)

Known-effort share of tokens: training side 66%, test side 64%.

| size | dominant effort | n | median actual |
|---|---|---|---|
| XS | high | 3 | n too small |
| XS | medium | 2 | n too small |
| XS | unknown | 2 | n too small |
| XS-S | medium | 1 | n too small |
| S | high | 4 | n too small |
| S | medium | 3 | n too small |
| S | unknown | 12 | 0.31 M |
| S-M | high | 5 | 0.59 M |
| S-M | medium | 3 | n too small |
| S-M | unknown | 2 | n too small |
| M | high | 5 | 1.08 M |
| M | medium | 2 | n too small |
| M | unknown | 7 | 0.92 M |
| M-L | high | 2 | n too small |
| M-L | medium | 1 | n too small |
| L | unknown | 1 | n too small |

### Idle-cap sensitivity (description only)

Sessions on the author's main machine from the last 30 days: 219. Total active hours with a 15-minute cap are
0.76x those with the 30-minute cap; with a 60-minute cap 1.78x. The median session
doesn't change (ratios 1.00 and 1.00). So the hours depend on the cap for long sessions; tokens don't.
The author's other machines weren't read.

## Deviations

1. The first run printed the H3-proxy verdict as "pass". Section 5 makes every verdict of the 60/40 design
   inconclusive with fewer than 8 days (it has 4). The code didn't apply that rule to the H3-proxy. The code was fixed
   to apply it, and the run was repeated with the same input and seed. All numbers were identical; only that verdict
   changed, to "inconclusive (too little data)".
2. The baseline counts (82 tasks; 51 below, 25 inside, 6 above; median ratio 0.44) differ from the numbers known before
   (0.30x; 55 / 22 / 5 of 82). Section 11 expected this: those numbers used the arithmetic midpoint and another window.
   The README uses the numbers in this file.

No other deviations.
