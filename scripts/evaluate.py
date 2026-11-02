#!/usr/bin/env python3
"""Runs the pre-registered evaluation (docs/EVALUATION.md) on an input file outside the repo (REQ-39).

  evaluate.py run --input <file> --out <folder>      results.json + results.md (aggregates only)
  evaluate.py idle-cap --out <folder> [--days N]     idle-cap sensitivity on the transcripts on this machine

It imports the shipped calibration and statistics (no second implementation). Output holds no task IDs, no dates
finer than an ISO week, and no value from fewer than 5 tasks (small-cell rule, REQ-17).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from measured import calibrate as C  # noqa: E402
from measured.stats import (SMALL, armid, cluster_bootstrap, geomid, inside, log_ratio, median,  # noqa: E402
                            wrange)
from measured.stats import interval as _interval  # noqa: E402
from measured.tasks import dominant_effort  # noqa: E402

SEED = 20261102
B = 10000
MIN_TRAIN = 20
MIN_TEST = 20
MIN_DAYS = 8
ALPHA = 0.10
SNAPSHOT_GAP_S = 48 * 3600
SIZES = ['XS', 'XS-S', 'S', 'S-M', 'M', 'M-L', 'L', 'L-XL', 'XL']


def ts(at):
    return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp() if at else None


def iso_week(at) -> str:
    d = datetime.fromisoformat(str(at).replace('Z', '+00:00')).date() if isinstance(at, str) else \
        datetime.fromtimestamp(at, timezone.utc).date()
    y, w, _ = d.isocalendar()
    return f'{y}-W{w:02d}'


def day(at) -> str:
    return str(at)[:10]


def r4(v):
    if v is None:
        return None
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return round(v, 4)
    return v


def rr(v):
    return [r4(x) for x in v] if v else None


# ---- data -------------------------------------------------------------------------------------------------------------

def load(path):
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    d = json.loads(raw)
    return d, hashlib.sha256(raw.encode('utf-8')).hexdigest()


def eligibility(d):
    snap = ts(d['snapshot'])
    tasks = d['tasks']
    counts = {'input': len(tasks)}
    e_all, removed = [], {'no_actual': 0, 'no_end': 0, 'within_48h': 0}
    for t in tasks:
        if not t.get('actual') or t['actual'] <= 0:
            removed['no_actual'] += 1
        elif not t.get('end'):
            removed['no_end'] += 1
        elif ts(t['end']) > snap - SNAPSHOT_GAP_S:
            removed['within_48h'] += 1
        else:
            e_all.append(t)
    e1 = [t for t in e_all if t.get('size') in SIZES and isinstance(t.get('guess'), list) and len(t['guess']) == 2
          and 0 < t['guess'][0] <= t['guess'][1]]
    e1m = [t for t in e1 if measured(t)]
    counts.update({'removed': removed, 'e_all': len(e_all), 'e1': len(e1), 'e1m': len(e1m),
                   'removed_no_size_or_guess': len(e_all) - len(e1), 'removed_not_measured': len(e1) - len(e1m)})
    return e_all, e1, e1m, counts


def measured(t) -> bool:
    br = t.get('by_role') or {}
    work = sum(br.get(r, 0) or 0 for r in ('build', 'review', 'fix'))
    return work > 0 and (br.get('lead', 0) or 0) <= 0.5 * t['actual']


def dom_effort(t):
    be = t.get('by_effort') or {}
    return dominant_effort(be) if be else 'unknown'


def rec(t):
    """The calibration record of a task (the shipped calibrate's input)."""
    return {'id': t['id'], 'size': t['size'], 'kind': t.get('kind'), 'date': day(t['end']), 'fresh': t['actual'],
            'active_h': t.get('active_h'), 'elapsed_h': t.get('elapsed_h'), 'guess': t.get('guess'),
            'dominant_effort': dom_effort(t)}


# ---- arms -------------------------------------------------------------------------------------------------------------

def arm_c(train_recs, t, levels=(0.5, 0.8)):
    """Arm C: the shipped calibrate + estimate_for. Returns (ranges by level, p50, fell_back, row tasks x scale)."""
    cal = C.calibrate(train_recs, [], with_backtest=False)
    row = C.estimate_for(cal, t['size'], t.get('kind'))
    fell = row is None or bool(row.get('scaled_from'))
    if row is None:
        vals = [x['fresh'] for x in train_recs]
    else:
        vals = [x['fresh'] * (row.get('scale') or 1.0) for x in row['_tasks']]
    out = {L: wrange(vals, L)[0] for L in levels}
    return out, median(vals), fell, row is None, vals, row


def arm_r(train_recs, t, levels=(0.5, 0.8)):
    same = [x for x in train_recs if x['size'] == t['size'] and x.get('guess')]
    pool = same if len(same) >= 5 else [x for x in train_recs if x.get('guess')]
    ratios = [x['fresh'] / geomid(x['guess']) for x in pool]
    g = geomid(t['guess'])
    out = {}
    for L in levels:
        r, _ = wrange(ratios, L)
        out[L] = [g * r[0], g * r[1]] if r else None
    return out


def arm_n(train_recs, levels=(0.5, 0.8)):
    vals = [x['fresh'] for x in train_recs]
    return {L: wrange(vals, L)[0] for L in levels}


def point(train, t, extra_levels=()):
    tr = [rec(x) for x in train]
    levels = tuple(sorted({0.5, 0.8, *extra_levels}))
    c, c_p50, fell, to_n, c_vals, row = arm_c(tr, t, levels)
    p = {'actual': t['actual'], 'day': day(t['end']), 'week': iso_week(t['end']),
         'C50': c[0.5], 'C80': c[0.8], 'Cp50': c_p50, 'C_fell': fell, 'C_to_N': to_n,
         'Ccurve': {L: c[L] for L in levels},
         'G50': list(t['guess']), 'G80': None,
         'R50': None, 'R80': None, 'N50': None, 'N80': None,
         'active_h': t.get('active_h'), 'elapsed_h': t.get('elapsed_h')}
    r = arm_r(tr, t)
    n = arm_n(tr)
    p['R50'], p['R80'], p['N50'], p['N80'] = r[0.5], r[0.8], n[0.5], n[0.8]
    if row is not None:
        p['Cact50'] = row['estimate']['range50']['active_h']
        p['Cela50'] = row['estimate']['range50']['elapsed_h']
    return p


# ---- designs ----------------------------------------------------------------------------------------------------------

def order(tasks):
    return sorted(tasks, key=lambda t: (t['end'], t['id']))


def rolling(pop, extra_levels=()):
    pts, no_start = [], 0
    pop = order(pop)
    for t in pop:
        if not t.get('start'):
            no_start += 1
            continue
        s = ts(t['start'])
        train = [x for x in pop if ts(x['end']) < s]
        if len(train) >= MIN_TRAIN:
            pts.append(point(train, t, extra_levels))
    return pts, {'no_start': no_start}


def cut(pop, extra_levels=()):
    pop = order(pop)
    n = len(pop)
    n_train = int(math.floor(0.6 * n))
    if n_train == 0:
        return [], {'n_train': 0, 'n_test': 0, 'cut_week': None}, [], []
    cut_end = pop[n_train - 1]['end']
    train = [t for t in pop if t['end'] <= cut_end]
    test = [t for t in pop if t['end'] > cut_end]
    pts = [point(train, t, extra_levels) for t in test]
    return pts, {'n_train': len(train), 'n_test': len(test), 'cut_week': iso_week(cut_end)}, train, test


# ---- metrics ----------------------------------------------------------------------------------------------------------

def mid_fn(kind):
    return armid if kind == 'arith' else geomid


def arm_stats(pts, arm, mid='geo', actual_key='actual'):
    """(errors, biases, in50, in80) per point for an arm."""
    m = mid_fn(mid)
    e, b, i50, i80 = [], [], [], []
    for p in pts:
        a = p[actual_key]
        r = p.get(f'{arm}50')
        if arm == 'Cp50':
            r = p['C50']
            mm = p['Cp50']
        else:
            mm = m(r) if r else None
        if mm is None or a is None:
            e.append(None), b.append(None), i50.append(None), i80.append(None)
            continue
        lr = log_ratio(a, mm)
        e.append(abs(lr))
        b.append(lr)
        i50.append(1.0 if inside(a, r) else 0.0)
        r80 = p.get(f'{arm}80') if arm != 'Cp50' else p['C80']
        i80.append((1.0 if inside(a, r80) else 0.0) if r80 else None)
    return e, b, i50, i80


def _mean(xs):
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


def clusters_of(pts):
    by = {}
    for i, p in enumerate(pts):
        by.setdefault(p['day'], []).append(i)
    return [by[d] for d in sorted(by)]


def analyse(pts, arms=('C', 'G', 'R', 'N'), mid='geo', actual_key='actual', n_boot=B, seed=SEED):
    """All primary metrics of one design with cluster-bootstrap intervals, H1 (Holm) and H2 verdicts."""
    n = len(pts)
    cl = clusters_of(pts)
    days = len(cl)
    st = {a: arm_stats(pts, a, mid, actual_key) for a in arms}
    enough = n >= MIN_TEST and days >= MIN_DAYS

    def metrics(idx):
        out = {}
        for a in arms:
            e, b, i50, i80 = st[a]
            out[a] = (median([e[i] for i in idx]), median([b[i] for i in idx]), _mean([i50[i] for i in idx]),
                      _mean([i80[i] for i in idx]))
        return out
    full = metrics(list(range(n)))
    share = []
    boots = cluster_bootstrap(cl, metrics, n_boot, seed, share) if n else []
    # Small-cell rule for intervals: when more than 5% of the resamples hold fewer than 5 distinct tasks, the interval
    # ends are values from fewer than 5 tasks, so no interval is shown (final review, SHOULD-10; RESULTS Deviation 3).
    hide = (share[0] if share else 1.0) > 0.05

    def interval(values):
        return None if hide else _interval(values)
    res = {'n': n, 'days': days, 'enough_data': enough, 'arms': {}, 'small_resample_share': r4(share[0] if share else None),
           'intervals_hidden': hide}
    for a in arms:
        res['arms'][a] = {
            'n': n, 'days': days,
            'median_error': r4(full[a][0]), 'median_error_ci90': rr(interval([x[a][0] for x in boots])),
            'bias': r4(full[a][1]), 'bias_ci90': rr(interval([x[a][1] for x in boots])),
            'coverage50': r4(full[a][2]), 'coverage50_ci90': rr(interval([x[a][2] for x in boots])),
            'coverage80': r4(full[a][3]), 'coverage80_ci90': rr(interval([x[a][3] for x in boots])),
        }
    if 'C' in arms:
        h1 = {}
        for x in [a for a in arms if a != 'C']:
            dpt = full['C'][0] - full[x][0] if full['C'][0] is not None and full[x][0] is not None else None
            ds = [b['C'][0] - b[x][0] for b in boots if b['C'][0] is not None and b[x][0] is not None]
            p = (1 + sum(1 for v in ds if v >= 0)) / (1 + len(ds)) if ds else 1.0
            h1[x] = {'n': n, 'days': days, 'D': r4(dpt), 'D_ci90': rr(interval(ds)), 'p': r4(p)}
        # Holm step-down at family error ALPHA
        names = sorted(h1, key=lambda k: h1[k]['p'])
        m = len(names)
        sig_ok = True
        for k, name in enumerate(names, start=1):
            thr = ALPHA / (m - k + 1)
            sig_ok = sig_ok and h1[name]['p'] <= thr
            h1[name]['holm_threshold'] = r4(thr)
            h1[name]['significant'] = sig_ok
        for name, v in h1.items():
            if not enough:
                v['verdict'] = 'inconclusive (too little data)'
            elif v['D'] is not None and v['D'] >= 0:
                lo = (v['D_ci90'] or [None])[0]
                v['verdict'] = 'fail (C worse)' if lo is not None and lo > 0 else 'fail'
            elif v['D'] is not None and v['D'] < 0 and v['significant']:
                v['verdict'] = 'pass'
            else:
                v['verdict'] = 'inconclusive'
        res['H1'] = {'a_vs_G': h1.get('G'), 'b_vs_R': h1.get('R'), 'c_vs_N': h1.get('N')}
        h2 = {}
        for L, key in ((0.5, 'coverage50'), (0.8, 'coverage80')):
            c = res['arms']['C'][key]
            ci = res['arms']['C'][key + '_ci90']
            if not enough or ci is None:
                v = 'inconclusive (too little data)'
            elif ci[0] <= L <= ci[1]:
                v = 'pass' if ci[0] >= L - 0.20 and ci[1] <= L + 0.20 else 'inconclusive'
            else:
                v = 'fail (ranges too narrow)' if c < L else 'fail (ranges too wide)'
            h2[str(L)] = {'n': n, 'days': days, 'coverage': c, 'ci90': ci, 'verdict': v}
        vs = [h2[k]['verdict'] for k in h2]
        overall = 'fail' if any(v.startswith('fail') for v in vs) else 'pass' if all(v == 'pass' for v in vs) \
            else 'inconclusive'
        res['H2'] = {'levels': h2, 'verdict': overall}
        b, bci = res['arms']['C']['bias'], res['arms']['C']['bias_ci90']
        if bci is None:
            label = 'unclear'
        elif -0.25 <= bci[0] and bci[1] <= 0.25:
            label = 'no material bias'
        elif bci[1] < 0 and b < -0.25:
            label = 'estimates too high'
        elif bci[0] > 0 and b > 0.25:
            label = 'estimates too low'
        elif (bci[1] < 0 or bci[0] > 0) and -0.25 <= b <= 0.25:
            label = 'small bias'
        else:
            label = 'unclear'
        res['bias_label_C'] = label
    return res


def calibration_curve(pts, levels):
    out = []
    for L in levels:
        ins = [1.0 if inside(p['actual'], p['Ccurve'].get(L)) else 0.0 for p in pts if p['Ccurve'].get(L)]
        out.append({'nominal': L, 'n': len(ins), 'observed': r4(_mean(ins)) if len(ins) >= SMALL else None})
    return out


def drift(pts):
    by = {}
    for p in pts:
        if p['C50']:
            by.setdefault(p['week'], []).append(log_ratio(p['actual'], geomid(p['C50'])))
    rows = [{'week': w, 'n': len(v), **({'median_bias': r4(median(v))} if len(v) >= SMALL else {'note': 'n too small'})}
            for w, v in sorted(by.items())]
    ok = [r for r in rows if r['n'] >= SMALL]
    return {'weeks': rows, 'note': 'not enough weeks' if len(ok) < 3 else None}


def hours(pts):
    out = {}
    for key, rk in (('active_h', 'Cact50'), ('elapsed_h', 'Cela50')):
        e, i = [], []
        for p in pts:
            a, r = p.get(key), p.get(rk)
            if a and r and a > 0:
                e.append(abs(log_ratio(a, geomid(r))))
                i.append(1.0 if inside(a, r) else 0.0)
        out[key] = {'n': len(e), **({'median_error': r4(median(e)), 'coverage50': r4(_mean(i))}
                                    if len(e) >= SMALL else {'note': 'n too small'})}
    return out


def h3_proxy(train, test, n_draws=200, n_boot=B, seed=SEED):
    rng = random.Random(seed)
    tr = [rec(x) for x in train]
    res = {}
    errs_by_k = {}
    for k in (10, 20, 30, 'all'):
        if k != 'all' and k > len(tr):
            res[str(k)] = {'n_test': len(test), 'note': 'training set smaller than k'}
            continue
        draws = [tr] if k == 'all' else [rng.sample(tr, k) for _ in range(n_draws)]
        mat, fell = [], 0
        for sub in draws:
            cal = C.calibrate(sub, [], with_backtest=False)
            row_e = []
            for t in test:
                row = C.estimate_for(cal, t['size'], t.get('kind'))
                if row is None or row.get('scaled_from'):
                    fell += 1
                vals = [x['fresh'] * (row.get('scale') or 1.0) for x in row['_tasks']] if row else [x['fresh'] for x in sub]
                r, _ = wrange(vals, 0.5)
                row_e.append(abs(log_ratio(t['actual'], geomid(r))))
            mat.append(row_e)
        errs_by_k[k] = mat
        res[str(k)] = {'n': len(test), 'n_test': len(test), 'draws': len(draws),
                       'mean_median_error': r4(_mean([median(m) for m in mat])),
                       'fallback_share': r4(fell / (len(draws) * len(test))) if test else None}
    if 10 in errs_by_k and 'all' in errs_by_k and test:
        cl = clusters_of([{'day': day(t['end'])} for t in test])

        def stat(idx):
            a = median([errs_by_k['all'][0][i] for i in idx])
            b = _mean([median([m[i] for i in idx]) for m in errs_by_k[10]])
            return a - b
        d3 = stat(list(range(len(test))))
        share = []
        boots = cluster_bootstrap(cl, stat, n_boot, seed, share)
        ci = None if share[0] > 0.05 else _interval(boots)
        if len(test) < MIN_TEST or len(cl) < MIN_DAYS:  # section 5: the minimum-data rule holds for this design too
            v = 'inconclusive (too little data)'
        else:
            v = 'pass' if ci and ci[1] < 0 else 'fail' if d3 >= 0 else 'inconclusive'
        res['D3'] = {'n': len(test), 'days': len(cl), 'D3': r4(d3), 'ci90': rr(ci), 'verdict': v,
                     'small_resample_share': r4(share[0]),
                     'note': 'random subsamples, not in time order; a pass does not prove H3'}
    return res


def baseline(pop, weeks_in):
    if not pop:
        return {'n': 0}
    ratios = [t['actual'] / geomid(t['guess']) for t in pop]
    ratios_a = [t['actual'] / armid(t['guess']) for t in pop]
    below = sum(1 for t in pop if t['actual'] < t['guess'][0])
    above = sum(1 for t in pop if t['actual'] > t['guess'][1])
    weeks = {iso_week(t['end']) for t in pop}
    wk = {w['week']: w for w in weeks_in or []}
    tot = sum((wk.get(w) or {}).get('total', 0) for w in weeks)
    tied = sum((wk.get(w) or {}).get('tied', 0) for w in weeks)
    gsum = sum(geomid(t['guess']) for t in pop)
    gsum_a = sum(armid(t['guess']) for t in pop)
    return {'n': len(pop), 'days': len({day(t['end']) for t in pop}),
            'median_ratio': r4(median(ratios)), 'median_ratio_arith': r4(median(ratios_a)),
            'below': below, 'inside': len(pop) - below - above, 'above': above,
            'weeks': len(weeks), 'upper_bound_ratio': r4(tot / gsum) if gsum and tot else None,
            'upper_bound_ratio_arith': r4(tot / gsum_a) if gsum_a and tot else None,
            'attribution_share': r4(tied / tot) if tot else None}


def share_by_week(weeks_in):
    return {w['week']: (w['tied'] / w['total']) for w in weeks_in or [] if w.get('total')}


def attribution_scaled(pts, pop_by_end, weeks_in):
    sh = share_by_week(weeks_in)
    out = []
    for p in pts:
        s = sh.get(p['week'])
        q = dict(p)
        q['actual_scaled'] = p['actual'] / s if s else None
        out.append(q)
    return out


def describe_pop(pop):
    kinds = {}
    for t in pop:
        kinds[t.get('kind') or 'none'] = kinds.get(t.get('kind') or 'none', 0) + 1
    big = {k: v for k, v in kinds.items() if v >= SMALL}
    other = sum(v for k, v in kinds.items() if v < SMALL)
    out = {'n': len(pop), 'kinds': dict(sorted(big.items())), 'kinds_other': other}
    if len(pop) >= SMALL:
        out['median_actual'] = r4(median([t['actual'] for t in pop]))
    return out


def effort_table(pop, train_cut=None):
    by = {}
    for t in pop:
        by.setdefault(t['size'], {}).setdefault(dom_effort(t), []).append(t['actual'])
    rows = []
    for s in sorted(by, key=lambda x: SIZES.index(x)):
        for e, v in sorted(by[s].items()):
            rows.append({'size': s, 'effort': e, 'n': len(v),
                         **({'median_actual': r4(median(v))} if len(v) >= SMALL else {'note': 'n too small'})})
    return rows


def known_share(pop):
    tot = known = 0
    for t in pop:
        for e, v in (t.get('by_effort') or {}).items():
            tot += v or 0
            if e != 'unknown':
                known += v or 0
    return {'n': len(pop), **({'known_share': r4(known / tot) if tot else None} if len(pop) >= SMALL else {})}


def summary_only(res):
    """H1/H2 numbers without verdicts (sensitivity analyses)."""
    out = {'n': res['n'], 'days': res['days'], 'arms': res['arms'], 'intervals_hidden': res.get('intervals_hidden'),
           'small_resample_share': res.get('small_resample_share')}
    if 'H1' in res:
        out['H1_D'] = {k: {kk: v[kk] for kk in ('n', 'D', 'D_ci90', 'p')} if v else None for k, v in res['H1'].items()}
    return out


def run(inp, outdir, n_boot=B):
    d, sha = load(inp)
    e_all, e1, e1m, counts = eligibility(d)
    weeks_in = d.get('weeks') or []
    curve_levels = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
    prim_pts, prim_info = rolling(e1m, curve_levels)
    prim = analyse(prim_pts, n_boot=n_boot)
    prim['fallback'] = {'n': len(prim_pts), 'to_scaled_or_N': sum(1 for p in prim_pts if p['C_fell']),
                        'to_N': sum(1 for p in prim_pts if p['C_to_N'])}
    prim['excluded'] = prim_info
    sec_pts, sec_info, train, test = cut(e1m)
    sec = analyse(sec_pts, n_boot=n_boot)
    sec.update(sec_info)
    sens = {
        'cut_60_40': summary_only(sec),
        'E1_rolling': summary_only(analyse(rolling(e1)[0], n_boot=n_boot)),
        'E1_cut': summary_only(analyse(cut(e1)[0], n_boot=n_boot)),
        'arithmetic_midpoint': summary_only(analyse(prim_pts, mid='arith', n_boot=n_boot)),
        'C_p50_midpoint': summary_only(analyse(prim_pts, arms=('Cp50', 'G', 'R', 'N'), n_boot=n_boot)),
    }
    scaled = [p for p in attribution_scaled(prim_pts, None, weeks_in) if p.get('actual_scaled')]
    sens['attribution_scaled'] = summary_only(analyse(scaled, actual_key='actual_scaled', n_boot=n_boot))
    sh = share_by_week(weeks_in)
    tr_w = {iso_week(t['end']) for t in train}
    te_w = {iso_week(t['end']) for t in test}
    wk = {w['week']: w for w in weeks_in}

    def share(ws):
        tot = sum((wk.get(w) or {}).get('total', 0) for w in ws)
        return r4(sum((wk.get(w) or {}).get('tied', 0) for w in ws) / tot) if tot else None
    sens['attribution_share'] = {'training_weeks': share(tr_w), 'test_weeks': share(te_w),
                                 'primary_test_weeks': share({p['week'] for p in prim_pts})}
    sens['calibration_curve'] = calibration_curve(prim_pts, curve_levels)
    sens['drift'] = drift(prim_pts)
    sens['hours'] = hours(prim_pts)
    h3 = h3_proxy(train, test, n_boot=n_boot) if train and test else {'note': 'no cut'}
    results = {
        'protocol': 'docs/EVALUATION.md', 'seed': SEED, 'bootstrap_resamples': n_boot,
        'input_sha256': sha, 'snapshot_week': iso_week(d['snapshot']),
        'counts': counts,
        'selection': {'E1': describe_pop(e1), 'E1m': describe_pop(e1m),
                      'excluded_no_size_or_guess': describe_pop([t for t in e_all if t not in e1])},
        'baseline': {'E1': baseline(e1, weeks_in), 'E1m': baseline(e1m, weeks_in)},
        'primary_rolling_origin': prim,
        'secondary_cut_60_40': sec,
        'sensitivity': sens,
        'H3_proxy': h3,
        'effort': {'table_E1m': effort_table(e1m), 'known_share_training': known_share(train),
                   'known_share_test': known_share(test)},
    }
    os.makedirs(outdir, exist_ok=True)
    text = json.dumps(results, indent=1, sort_keys=True, default=str)
    with open(os.path.join(outdir, 'results.json'), 'w', encoding='utf-8') as f:
        f.write(text + '\n')
    with open(os.path.join(outdir, 'results.md'), 'w', encoding='utf-8') as f:
        f.write(markdown(results))
    return results


# ---- markdown ---------------------------------------------------------------------------------------------------------

def f(v, pct=False):
    if v is None:
        return '-'
    if pct:
        return f'{v * 100:.0f}%'
    return f'{v:.2f}'


def ci(v, pct=False):
    return f'[{f(v[0], pct)}, {f(v[1], pct)}]' if v else '-'


def arms_table(res):
    lines = ['| Arm | n | days | median error (90% CI) | bias (90% CI) | 50% range held (90% CI) | 80% range held (90% CI) |',
             '|---|---|---|---|---|---|---|']
    names = {'C': 'C calibrated', 'Cp50': 'C (median as midpoint)', 'G': 'G guess', 'R': 'R guess x ratio',
             'N': 'N size-blind'}
    for a, v in res['arms'].items():
        if v['n'] < SMALL:
            lines.append(f"| {names.get(a, a)} | {v['n']} | {v['days']} | n too small | | | |")
            continue
        lines.append(f"| {names.get(a, a)} | {v['n']} | {v['days']} | {f(v['median_error'])} {ci(v['median_error_ci90'])} | "
                     f"{f(v['bias'])} {ci(v['bias_ci90'])} | {f(v['coverage50'], True)} {ci(v['coverage50_ci90'], True)} | "
                     f"{f(v['coverage80'], True)} {ci(v['coverage80_ci90'], True)} |")
    return '\n'.join(lines)


def hidden_note(res):
    if not res.get('intervals_hidden'):
        return ''
    return (f" Intervals hidden: {res['small_resample_share'] * 100:.0f}% of the resamples held fewer than 5 distinct "
            f"tasks (small-cell rule).")


def markdown(r):
    p = r['primary_rolling_origin']
    out = ['<!-- generated by scripts/evaluate.py; numbers only, no task-level data -->', '']
    out.append(f"Input SHA-256: `{r['input_sha256']}`. Snapshot: {r['snapshot_week']}. Seed {r['seed']}, "
               f"{r['bootstrap_resamples']} cluster-bootstrap resamples (by day).")
    c = r['counts']
    out += ['', '### Data', '',
            f"Input tasks: {c['input']}. Removed: {c['removed']['no_actual']} without an actual, {c['removed']['no_end']} "
            f"without an end time, {c['removed']['within_48h']} within 48 h of the snapshot. E-all: {c['e_all']}. "
            f"Without size or guess: {c['removed_no_size_or_guess']}. E1: {c['e1']}. Not measured (lead share > 0.5 or "
            f"no build/review/fix tokens): {c['removed_not_measured']}. **E1-m: {c['e1m']}.**", '']
    for name, s in r['selection'].items():
        kinds = ', '.join(f'{k} {v}' for k, v in s['kinds'].items())
        out.append(f"- {name}: n {s['n']}; kinds {kinds or '-'}; other kinds {s['kinds_other']}; "
                   f"median actual {f((s.get('median_actual') or 0) / 1e6) + ' M' if s.get('median_actual') else 'n too small'}")
    out += ['', '### Baseline (guesses before calibration)', '',
            '| Population | n | days | median actual / guess midpoint | arithmetic midpoint | below / inside / above | upper bound (all tokens / guesses) | tokens tied to tasks |',
            '|---|---|---|---|---|---|---|---|']
    for name, b in r['baseline'].items():
        if b['n'] < SMALL:
            out.append(f"| {name} | {b['n']} | n too small | | | | | |")
            continue
        out.append(f"| {name} | {b['n']} | {b['days']} | {f(b['median_ratio'])} | {f(b['median_ratio_arith'])} | "
                   f"{b['below']} / {b['inside']} / {b['above']} | {f(b['upper_bound_ratio'])} | {f(b['attribution_share'], True)} |")
    out += ['', '### Primary: rolling origin on E1-m', '',
            f"Test points: {p['n']} on {p['days']} days (minimum {MIN_TEST} points and {MIN_DAYS} days: "
            f"{'met' if p['enough_data'] else 'NOT met'}). C fell back to scaling or N for {p['fallback']['to_scaled_or_N']} "
            f"points (to N: {p['fallback']['to_N']}).{hidden_note(p)}", '', arms_table(p), '']
    out += ['| Hypothesis | D = error(C) - error(X) (90% CI) | p (one-sided) | Holm threshold | verdict |', '|---|---|---|---|---|']
    for k, label in (('a_vs_G', 'H1a C vs G'), ('b_vs_R', 'H1b C vs R'), ('c_vs_N', 'H1c C vs N')):
        v = p['H1'][k]
        out.append(f"| {label} | {f(v['D'])} {ci(v['D_ci90'])} | {f(v['p'])} | {v['holm_threshold']} | **{v['verdict']}** |")
    out += ['', '| H2 level | coverage of C (90% CI) | verdict |', '|---|---|---|']
    for L, v in p['H2']['levels'].items():
        out.append(f"| {float(L) * 100:.0f}% | {f(v['coverage'], True)} {ci(v['ci90'], True)} | {v['verdict']} |")
    out += ['', f"**H2: {p['H2']['verdict']}.** Bias label for C: **{p['bias_label_C']}**.", '']
    s = r['secondary_cut_60_40']
    out += ['### Secondary: 60/40 cut on E1-m', '',
            f"Training {s['n_train']}, test {s['n_test']} on {s['days']} days, cut in {s['cut_week']}.{hidden_note(s)}", '',
            arms_table(s), '',
            '| Hypothesis | D (90% CI) | p | verdict (secondary, not deciding) |', '|---|---|---|---|']
    for k, label in (('a_vs_G', 'H1a'), ('b_vs_R', 'H1b'), ('c_vs_N', 'H1c')):
        v = s['H1'][k]
        out.append(f"| {label} | {f(v['D'])} {ci(v['D_ci90'])} | {f(v['p'])} | {v['verdict']} |")
    out.append(f"\nH2 (secondary): {s['H2']['verdict']}; bias label {s['bias_label_C']}.\n")
    out += ['### Sensitivity (numbers only, no verdicts)', '']
    for name in ('E1_rolling', 'E1_cut', 'arithmetic_midpoint', 'C_p50_midpoint', 'attribution_scaled'):
        v = r['sensitivity'][name]
        out += [f'**{name}** (n {v["n"]}, days {v["days"]}).{hidden_note(v)}', '', arms_table(v), '']
    a = r['sensitivity']['attribution_share']
    out.append(f"Tokens tied to tasks: training weeks {f(a['training_weeks'], True)}, test weeks {f(a['test_weeks'], True)}, "
               f"primary test weeks {f(a['primary_test_weeks'], True)}.\n")
    out += ['Calibration curve of C (nominal vs observed coverage):', '', '| nominal | n | observed |', '|---|---|---|']
    for row in r['sensitivity']['calibration_curve']:
        out.append(f"| {row['nominal'] * 100:.0f}% | {row['n']} | {f(row['observed'], True)} |")
    dr = r['sensitivity']['drift']
    out += ['', f"Drift (median bias of C per week, n >= 5): {dr['note'] or ''}", '']
    for w in dr['weeks']:
        out.append(f"- {w['week']}: n {w['n']}, {f(w.get('median_bias')) if 'median_bias' in w else 'n too small'}")
    h = r['sensitivity']['hours']
    out += ['', 'Hours (C): ' + '; '.join(
        f"{k}: n {v['n']}, " + (f"median error {f(v['median_error'])}, 50% range held {f(v['coverage50'], True)}"
                                if 'median_error' in v else 'n too small') for k, v in h.items()), '']
    out += ['### H3-proxy (secondary, 60/40 cut; not a test of H3)', '', '| k | draws | mean median error | fallback share |', '|---|---|---|---|']
    for k in ('10', '20', '30', 'all'):
        v = r['H3_proxy'].get(k) or {}
        out.append(f"| {k} | {v.get('draws', '-')} | {f(v.get('mean_median_error'))} | {f(v.get('fallback_share'), True)} |")
    d3 = r['H3_proxy'].get('D3')
    if d3:
        out.append(f"\nD3 = error(all) - error(k = 10) = {f(d3['D3'])} {ci(d3['ci90'])}{' (interval hidden: small-cell rule)' if d3['ci90'] is None else ''}, n {d3['n']}, {d3['days']} days: "
                   f"**{d3['verdict']}** ({d3['note']}).\n")
    e = r['effort']
    out += ['### Effort (description only)', '',
            f"Known-effort share of tokens: training side {f(e['known_share_training'].get('known_share'), True)}, "
            f"test side {f(e['known_share_test'].get('known_share'), True)}.", '',
            '| size | dominant effort | n | median actual |', '|---|---|---|---|']
    for row in e['table_E1m']:
        out.append(f"| {row['size']} | {row['effort']} | {row['n']} | "
                   f"{f(row['median_actual'] / 1e6) + ' M' if 'median_actual' in row else 'n too small'} |")
    return '\n'.join(out) + '\n'


# ---- idle cap ---------------------------------------------------------------------------------------------------------

def idle_cap(outdir, days=30):
    import time as _t
    import adapters
    ad = adapters.get('claude-code')
    sess = ad.list_sessions(_t.time() - days * 86400)
    tot = {15: 0.0, 30: 0.0, 60: 0.0}
    ratios15, ratios60 = [], []
    n = 0
    for path, sid, _ in sess:
        try:
            s = ad.read_session(path, sid, _t.monotonic() + 60)
        except Exception:
            continue
        act = {}
        for cap in tot:
            a = 0.0
            for tr in s.transcripts:
                prev = None
                for m in tr.messages:
                    if prev is not None and 0 <= m.time - prev <= cap * 60:
                        a += m.time - prev
                    prev = m.time if prev is None else max(prev, m.time)
            act[cap] = a
        if act[30] <= 0:
            continue
        n += 1
        for cap in tot:
            tot[cap] += act[cap]
        ratios15.append(act[15] / act[30])
        ratios60.append(act[60] / act[30])
    res = {'sessions': n}
    if n < 10:
        res['note'] = 'not run: fewer than 10 sessions with active time'
    else:
        res.update({'total_ratio_15_to_30': r4(tot[15] / tot[30]), 'total_ratio_60_to_30': r4(tot[60] / tot[30]),
                    'median_session_ratio_15_to_30': r4(median(ratios15)),
                    'median_session_ratio_60_to_30': r4(median(ratios60))})
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'idle_cap.json'), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(res, indent=1, sort_keys=True) + '\n')
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(prog='evaluate')
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--input', required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--resamples', type=int, default=B, help=argparse.SUPPRESS)
    i = sub.add_parser('idle-cap')
    i.add_argument('--out', required=True)
    i.add_argument('--days', type=int, default=30)
    a = ap.parse_args(argv)
    if a.cmd == 'run':
        run(a.input, a.out, a.resamples)
    else:
        idle_cap(a.out, a.days)
    return 0


if __name__ == '__main__':
    sys.exit(main())
