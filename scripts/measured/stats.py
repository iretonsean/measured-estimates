"""Statistics shared by `calibrate`, `report` and `evaluate.py` (one implementation, REQ-39)."""
from __future__ import annotations

import math
import random

SMALL = 5  # a value from fewer tasks shows only its count (REQ-17)
TAILS = 10  # p10 / p90 / 80% ranges need this many


def quantile(xs, p: float):
    """Linear interpolation between order statistics; None for an empty list."""
    s = sorted(x for x in xs if x is not None and math.isfinite(x))
    if not s:
        return None
    i = (len(s) - 1) * p
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def median(xs):
    return quantile(xs, 0.5)


def widened_levels(n: int, level: float):
    """(low_level, high_level, clipped) so that the range between those sample quantiles of n values holds a new value
    from the same distribution with probability `level` (expected coverage (h - l)(n - 1)/(n + 1)), REQ-26."""
    if n < 2:
        return 0.0, 1.0, True
    half = level * (n + 1) / (2 * (n - 1))
    lo, hi = 0.5 - half, 0.5 + half
    clipped = lo < 0 or hi > 1
    return max(0.0, lo), min(1.0, hi), clipped


def wrange(xs, level: float):
    """([low, high], clipped) for a nominal level with small-n widening; (None, True) without values."""
    v = [x for x in xs if x is not None and math.isfinite(x)]
    if not v:
        return None, True
    lo, hi, clipped = widened_levels(len(v), level)
    return [quantile(v, lo), quantile(v, hi)], clipped


def geomid(rng) -> float | None:
    """The midpoint of a range on the log scale: sqrt(low x high)."""
    if not rng or rng[0] is None or rng[1] is None:
        return None
    lo, hi = max(float(rng[0]), 1e-9), max(float(rng[1]), 1e-9)
    return math.sqrt(lo * hi)


def armid(rng) -> float | None:
    if not rng or rng[0] is None or rng[1] is None:
        return None
    return (float(rng[0]) + float(rng[1])) / 2


def log_ratio(actual: float, mid: float) -> float:
    return math.log(max(actual, 1e-9) / max(mid, 1e-9))


def inside(actual: float, rng) -> bool:
    return rng is not None and rng[0] <= actual <= rng[1]


def sig(v, digits: int = 2):
    """Round to significant digits (display and the starter table)."""
    if v is None:
        return None
    if v == 0 or not math.isfinite(v):
        return v
    return round(v, -int(math.floor(math.log10(abs(v)))) + (digits - 1))


def pct(xs, ps=(0.1, 0.25, 0.5, 0.75, 0.9)):
    v = [x for x in xs if x is not None]
    out = {'n': len(v)}
    for p in ps:
        out['p%d' % round(p * 100)] = quantile(v, p)
    return out


def accuracy(rows):
    """rows = [(actual, range50, range80 or None)] -> {n, error, coverage50, coverage80, bias} (raw values)."""
    rows = [r for r in rows if r[1] is not None]
    if not rows:
        return {'n': 0}
    errs = [abs(log_ratio(a, geomid(r50))) for a, r50, _ in rows]
    bias = [log_ratio(a, geomid(r50)) for a, r50, _ in rows]
    c50 = sum(1 for a, r50, _ in rows if inside(a, r50)) / len(rows)
    r80s = [(a, r80) for a, _, r80 in rows if r80 is not None]
    out = {'n': len(rows), 'error': median(errs), 'coverage50': c50, 'bias': median(bias)}
    if r80s:
        out['coverage80'] = sum(1 for a, r in r80s if inside(a, r)) / len(r80s)
    return out


def cluster_bootstrap(clusters: list, stat, n_boot: int = 10000, seed: int = 20261102):
    """Resample clusters (lists of items) with replacement; return [stat(items)] per resample. Deterministic: the
    clusters are used in the order given (the caller sorts them)."""
    rng = random.Random(seed)
    k = len(clusters)
    out = []
    for _ in range(n_boot):
        items = []
        for _ in range(k):
            items.extend(clusters[rng.randrange(k)])
        out.append(stat(items))
    return out


def interval(values, level: float = 0.90):
    v = [x for x in values if x is not None and math.isfinite(x)]
    if not v:
        return None
    a = (1 - level) / 2
    return [quantile(v, a), quantile(v, 1 - a)]
