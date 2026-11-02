"""Calibration: finished, measured tasks -> estimate ranges per size (REQ-26).

Input task record: {id, size, kind, date (YYYY-MM-DD of its end), fresh, active_h, elapsed_h, guess ([lo, hi] or None),
dominant_effort}. Only measured tasks go in (REQ-25); the caller counts the others.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import SCHEMA_VERSION
from .stats import SMALL, geomid, inside, log_ratio, median, pct, quantile, wrange

WINDOW_DAYS = 28
MIN_N = 5
MIN_POOL = 3
SIZE_VALUE = {'XS': 1, 'S': 2, 'M': 3, 'L': 4, 'XL': 5}


def size_value(size, scale=None) -> float | None:
    if not isinstance(size, str) or not size:
        return None
    order = list(scale) if scale else list(SIZE_VALUE)
    vals = {s.upper(): i + 1 for i, s in enumerate(order)}
    parts = size.upper().split('-')
    if not all(p in vals for p in parts):
        return None
    return sum(vals[p] for p in parts) / len(parts)


def norm_size(size, scale=None):
    return size.upper() if size_value(size, scale) is not None else None


def in_window(tasks: list, days: int = WINDOW_DAYS) -> list:
    dates = sorted(t['date'] for t in tasks if t.get('date'))
    if not dates:
        return list(tasks)
    newest = date.fromisoformat(dates[-1][:10])
    start = (newest - timedelta(days=days)).isoformat()
    return [t for t in tasks if t.get('date') and t['date'][:10] >= start]


def _pick(all_t, recent, size, kind=None):
    of = lambda lst: [t for t in lst if t['size'] == size and (kind is None or t.get('kind') == kind)]
    for lst, need, source in ((recent, MIN_N, 'window'), (all_t, MIN_N, 'all'), (all_t, MIN_POOL, 'all, small n')):
        got = of(lst)
        if len(got) >= need:
            return got, source
    return None, None


def ranges(tasks: list, scale: float = 1.0) -> dict:
    """The estimate part of a row: 50% and 80% ranges (widened for small n) and medians."""
    tok = [t['fresh'] * scale for t in tasks]
    act = [t['active_h'] * scale for t in tasks if t.get('active_h') is not None]
    ela = [t['elapsed_h'] * scale for t in tasks if t.get('elapsed_h') is not None]
    t50, c50 = wrange(tok, 0.5)
    t80, c80 = wrange(tok, 0.8)
    a50, _ = wrange(act, 0.5)
    e50, _ = wrange(ela, 0.5)
    return {'range50': {'tokens': t50, 'active_h': a50, 'elapsed_h': e50}, 'range80': {'tokens': t80},
            'median': {'tokens': median(tok), 'active_h': median(act), 'elapsed_h': median(ela)},
            'narrow50': c50, 'narrow80': c80}


def describe(tasks: list) -> dict:
    ratios = [t['fresh'] / geomid(t['guess']) for t in tasks if t.get('guess')]
    effort = {}
    for t in tasks:
        effort.setdefault(t.get('dominant_effort') or 'unknown', []).append(t)
    return {
        'n': len(tasks),
        'stats': {'tokens': pct([t['fresh'] for t in tasks]),
                  'active_h': pct([t.get('active_h') for t in tasks]),
                  'elapsed_h': pct([t.get('elapsed_h') for t in tasks])},
        'ratio_to_guess': pct(ratios, (0.25, 0.5, 0.75)),
        'by_effort': {e: {'n': len(lst), 'median_tokens': median([t['fresh'] for t in lst]),
                          **({'estimate': ranges(lst)} if len(lst) >= SMALL else {})}
                      for e, lst in sorted(effort.items())},
    }


def _confidence(source, n):
    if 'small' in source:
        return 'rough'
    return 'good' if n >= 10 else 'low'


def size_rows(all_t: list, recent: list, scale=None) -> dict:
    rows = {}
    for size in sorted({t['size'] for t in all_t if t.get('size')}, key=lambda s: size_value(s, scale) or 0):
        got, source = _pick(all_t, recent, size)
        if got:
            rows[size] = {**describe(got), 'source': source, 'confidence': _confidence(source, len(got)),
                          'estimate': ranges(got), '_tasks': got}
    return rows


def guess_mids(tasks: list) -> dict:
    by = {}
    for t in tasks:
        if t.get('size') and t.get('guess'):
            by.setdefault(t['size'], []).append(geomid(t['guess']))
    return {s: median(v) for s, v in by.items()}


def scaled_row(rows: dict, size: str, gmids: dict, scale=None) -> dict | None:
    """A row for a size without enough data: the nearest measured size, times the ratio of the median guesses of the
    two sizes, or 2 per scale step without guesses (REQ-26)."""
    v = size_value(size, scale)
    measured = [s for s, r in rows.items() if not r.get('scaled_from')]
    if v is None or not measured:
        return None
    ref = sorted(measured, key=lambda s: (abs(size_value(s, scale) - v), -size_value(s, scale)))[0]
    gs, gr = gmids.get(size), gmids.get(ref)
    factor = gs / gr if gs and gr else 2 ** (v - size_value(ref, scale))
    base = rows[ref]
    return {'n': 0, 'source': f'scaled from {ref} x {round(factor, 2)}', 'scaled_from': ref, 'scale': factor,
            'confidence': 'rough', 'estimate': ranges(base['_tasks'], factor), '_tasks': base['_tasks']}


def backtest(all_t: list, scale=None) -> dict:
    """Leave-one-out: the size row against guess x ratio, on tasks with a size and a guess (REQ-26)."""
    res = {'size': [], 'guess': []}
    for t in [x for x in all_t if x.get('size') and x.get('guess')]:
        rest = [x for x in all_t if x is not t]
        rows = size_rows(rest, in_window(rest), scale)
        row = rows.get(t['size']) or scaled_row(rows, t['size'], guess_mids(rest), scale)
        if not row:
            continue
        r_size = row['estimate']['range50']['tokens']
        ratios = [x['fresh'] / geomid(x['guess']) for x in row['_tasks'] if x.get('guess') and x is not t]
        if len(ratios) >= MIN_N:
            rr, _ = wrange(ratios, 0.5)
            g = geomid(t['guess'])
            r_guess = [g * rr[0], g * rr[1]]
        else:
            r_guess = r_size
        for key, r in (('size', r_size), ('guess', r_guess)):
            if r:
                res[key].append((abs(log_ratio(t['fresh'], geomid(r))), inside(t['fresh'], r)))
    out = {}
    for key, v in res.items():
        out[key] = {'n': len(v), 'median_error': median([e for e, _ in v]),
                    'coverage50': (sum(1 for _, i in v if i) / len(v)) if v else None}
    out['chosen'] = 'guess' if out['guess']['n'] and out['size']['median_error'] is not None and \
        out['guess']['median_error'] < out['size']['median_error'] else 'size'
    return out


def attribution(sessions: list, since: str | None) -> dict:
    tot = items = proc = untied = 0
    for s in sessions:
        last = (s.get('last') or s.get('first') or '')[:10]
        if since and last and last < since:
            continue
        tot += s.get('fresh_tokens') or 0
        for k, v in (s.get('tasks') or {}).items():
            if k.startswith('process:'):
                proc += (v or {}).get('fresh') or 0
            else:
                items += (v or {}).get('fresh') or 0
        untied += sum((s.get('untied') or {}).values())
    return {'total_tokens': tot, 'task_tokens': items, 'process_tokens': proc, 'untied_tokens': untied,
            'items_share': (items / tot) if tot else None, 'overhead': (tot / items) if items else 1.0}


def calibrate(tasks: list, sessions: list = (), scale=None, now: str = '', left_out: int = 0,
              with_backtest: bool = True) -> dict:
    all_t = [dict(t, size=norm_size(t.get('size'), scale)) for t in tasks if t.get('fresh') and t['fresh'] > 0]
    recent = in_window(all_t)
    rows = size_rows(all_t, recent, scale)
    cells = {}
    for size in rows:
        for kind in sorted({t.get('kind') for t in all_t if t['size'] == size and t.get('kind')}):
            got = [t for t in recent if t['size'] == size and t.get('kind') == kind]
            if len(got) >= MIN_N:
                cells[f'{size}/{kind}'] = {**describe(got), 'source': 'window', 'confidence': _confidence('window', len(got)),
                                           'estimate': ranges(got), '_tasks': got}
    dates = sorted(t['date'] for t in all_t if t.get('date'))
    win_from = min((t['date'] for t in recent if t.get('date')), default=None)
    cal = {
        'schema_version': SCHEMA_VERSION, 'updated': now,
        'window': {'days': WINDOW_DAYS, 'min_n': MIN_N, 'from': win_from, 'to': dates[-1] if dates else None},
        'data': {'measured': len(all_t), 'in_window': len(recent), 'left_out_not_measured': left_out,
                 'with_guess': sum(1 for t in all_t if t.get('guess'))},
        'sizes': rows, 'cells': cells, 'guess_mids': guess_mids(all_t),
        'attribution': attribution(list(sessions), win_from),
        'scale': list(scale) if scale else list(SIZE_VALUE),
    }
    if with_backtest:
        cal['backtest'] = backtest(all_t, scale)
    return cal


def strip_private(cal: dict) -> dict:
    """The calibration without the task lists (what's written to calibration.json)."""
    def clean(r):
        return {k: v for k, v in r.items() if not k.startswith('_')}
    out = dict(cal)
    out['sizes'] = {s: clean(r) for s, r in cal['sizes'].items()}
    out['cells'] = {s: clean(r) for s, r in cal['cells'].items()}
    return out


def estimate_for(cal: dict, size: str, kind: str | None = None) -> dict | None:
    """The row an estimate uses: size + kind cell (n >= 5 in the window), else the size row, else a scaled row."""
    scale = cal.get('scale')
    s = norm_size(size, scale)
    if s is None:
        return None
    if kind and f'{s}/{kind}' in cal.get('cells', {}):
        r = cal['cells'][f'{s}/{kind}']
        return {**r, 'from': f'{s} {kind}'}
    if s in cal.get('sizes', {}):
        return {**cal['sizes'][s], 'from': s}
    r = scaled_row(cal.get('sizes', {}), s, cal.get('guess_mids', {}), scale)
    if r:
        return {**r, 'from': r['source']}
    return None


def pooled_row(tasks: list) -> dict | None:
    if not tasks:
        return None
    return {**describe(tasks), 'source': 'all sizes', 'confidence': 'rough', 'estimate': ranges(tasks), '_tasks': tasks}
