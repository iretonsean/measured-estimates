"""`ledger report`: size table, attribution, warnings, open tasks, and own accuracy over time (REQ-27, REQ-40)."""
from __future__ import annotations

from .stats import SMALL, TAILS, geomid, inside, log_ratio, median
from .tasks import BEFORE_WORK_S, first_estimate
from . import store


def small(n: int, values: dict) -> dict:
    """A row under the small-cell rule: below 5 tasks only the count shows (REQ-17)."""
    if n < SMALL:
        return {'n': n, 'note': 'n too small'}
    return {'n': n, **values}


def size_table(cal: dict) -> list:
    rows = []
    for size, r in cal.get('sizes', {}).items():
        e = r['estimate']
        vals = {'range50_tokens': e['range50']['tokens'], 'range50_active_h': e['range50']['active_h'],
                'range50_elapsed_h': e['range50']['elapsed_h'], 'source': r['source'], 'confidence': r['confidence'],
                'narrow': bool(e.get('narrow50'))}
        if r['n'] >= TAILS:
            vals['range80_tokens'] = e['range80']['tokens']
        rows.append({'size': size, **small(r['n'], vals)})
    return rows


def _acc_row(items: list) -> dict:
    """items = [(actual, range50, range80 or None)]."""
    n = len(items)
    if n < SMALL:
        return {'n': n, 'note': 'n too small'}
    errs = [abs(log_ratio(a, geomid(r))) for a, r, _ in items]
    bias = [log_ratio(a, geomid(r)) for a, r, _ in items]
    out = {'n': n, 'median_error': median(errs), 'coverage50': sum(1 for a, r, _ in items if inside(a, r)) / n,
           'bias': median(bias)}
    r80 = [(a, r) for a, _, r in items if r]
    if len(r80) >= SMALL:
        out['coverage80'] = sum(1 for a, r in r80 if inside(a, r)) / len(r80)
        out['n80'] = len(r80)
    return out


def accuracy(view: dict) -> dict:
    """Own accuracy over time: first estimate (before work) against the actual at done (REQ-40)."""
    done = sorted((t for t in view.values() if t['status'] == 'done' and t.get('actual')),
                  key=lambda t: t['done_at'] or '')
    no_est = during = not_measured = 0
    rows = []  # (done_at, source, actual, range50, range80, guess)
    for t in done:
        a = t['actual']
        if not a.get('measured'):
            not_measured += 1
            continue
        fe = first_estimate(t)
        if not fe or not (fe.get('range50') or {}).get('tokens'):
            no_est += 1
            continue
        if a.get('start') and store.parse_ts(fe['at']) > store.parse_ts(a['start']) + BEFORE_WORK_S:
            during += 1
            continue
        rows.append((t['done_at'], fe.get('source') or 'own', a['fresh'], fe['range50']['tokens'],
                     (fe.get('range80') or {}).get('tokens'), fe.get('guess')))

    def group(sel):
        out = {}
        for src in ('own', 'starter'):
            items = [(a, r50, r80) for _, s, a, r50, r80, _ in sel if s == src]
            if items:
                out[src] = _acc_row(items)
        guesses = [(a, g, None) for _, _, a, _, _, g in sel if g]
        if guesses:
            out['guess'] = _acc_row(guesses)
        out['n'] = len(sel)
        return out

    months = {}
    for r in rows:
        months.setdefault((r[0] or '')[:7], []).append(r)
    blocks = []
    for i in range(0, len(rows), 10):
        chunk = rows[i:i + 10]
        blocks.append({'block': f'{i + 1}-{i + len(chunk)}', 'short': len(chunk) < 10, **group(chunk)})
    return {'months': [{'month': m, **group(v)} for m, v in sorted(months.items())], 'blocks': blocks,
            'total': group(rows), 'left_out': {'no_estimate': no_est, 'during_work': during,
                                               'not_measured': not_measured}}


def open_tasks(view: dict, lines: list) -> list:
    out = []
    for t in view.values():
        if t['status'] == 'done' or not t['estimates']:
            continue
        used = sum(((ln.get('tasks') or {}).get(t['id']) or {}).get('fresh') or 0 for ln in lines)
        if used > 0:
            out.append({'id': t['id'], 'fresh_so_far': used, 'estimated_at': t['estimates'][0]['at']})
    return sorted(out, key=lambda x: x['estimated_at'])


def build(cal: dict, view: dict, lines: list, aggregate: bool = False) -> dict:
    st = store.read_status()
    att = cal.get('attribution') or {}
    rep = {
        'warnings': [w['code'] for w in store.recent_warnings()],
        'sync': st.get('sync'),
        'sizes': size_table(cal),
        'attribution': {'items_share': att.get('items_share'), 'overhead': att.get('overhead')},
        'left_out_not_measured': (cal.get('data') or {}).get('left_out_not_measured', 0),
        'accuracy': accuracy(view),
        'sessions': len(lines),
    }
    if not aggregate:
        rep['open'] = open_tasks(view, lines)
    return rep


def _fmt_tokens(v):
    from .stats import sig
    if v is None:
        return '-'
    return f'{sig(v / 1e6, 2):g}M' if v >= 1e6 else f'{sig(v / 1e3, 2):g}k'


def _fmt_range(r, unit=''):
    from .stats import sig
    if not r:
        return '-'
    if unit == 'tok':
        return f'{_fmt_tokens(r[0])} to {_fmt_tokens(r[1])}'
    return f'{sig(r[0], 2):g} to {sig(r[1], 2):g}{unit}'


def text(rep: dict) -> str:
    out = []
    if rep.get('initialized') is False:
        out.append('Not set up yet: run init (see the skill, "First use").')
    for w in rep['warnings']:
        out.append({'format': 'WARNING: a session file had no readable token counts. Claude Code may have changed its '
                              'file format. Update the plugin, or open an issue.',
                    'deadline': 'WARNING: a record stopped at its time limit. That session end has no new record.',
                    'lock': 'WARNING: a record waited too long for the lock. That session end has no new record.',
                    'newer-schema': 'WARNING: the store has files from a newer version. Update the plugin.'}.get(w, w))
    s = rep.get('sync')
    if s and s.get('result') == 'fail':
        out.append(f"WARNING: last sync failed at {s['at']} ({s['code']}).")
    out.append('Sizes (your measured, finished tasks):')
    if not rep['sizes']:
        out.append('  none yet. Estimates use the starter table until a size has 5 of your tasks.')
    for r in rep['sizes']:
        if 'note' in r:
            out.append(f"  {r['size']:<5} n {r['n']:<3} ({r['note']})")
            continue
        out.append(f"  {r['size']:<5} n {r['n']:<3} 50% range {_fmt_range(r['range50_tokens'], 'tok')} tokens, "
                   f"{_fmt_range(r['range50_active_h'], ' h')} work, {_fmt_range(r['range50_elapsed_h'], ' h')} elapsed"
                   f" ({r['source']}, {r['confidence']}{', may be too narrow' if r['narrow'] else ''})")
    a = rep['attribution']
    if a.get('items_share') is not None:
        out.append(f"Tokens tied to tasks: {a['items_share'] * 100:.0f}% of all tokens (overhead x{a['overhead']:.2g}).")
    if rep['left_out_not_measured']:
        out.append(f"Left out: {rep['left_out_not_measured']} finished tasks whose tokens are mostly lead work "
                   f"(not measured).")
    acc = rep['accuracy']
    out.append('Your accuracy (first estimate before the work, against the measured tokens at done):')

    def line(label, g):
        parts = []
        for src in ('own', 'starter', 'guess'):
            r = g.get(src)
            if not r:
                continue
            if 'note' in r:
                parts.append(f"{src}: n {r['n']} (n too small)")
            else:
                c80 = f", 80% range held {r['coverage80'] * 100:.0f}%" if 'coverage80' in r else ''
                parts.append(f"{src}: n {r['n']}, error {r['median_error']:.2f}, 50% range held "
                             f"{r['coverage50'] * 100:.0f}%{c80}, bias {r['bias']:+.2f}")
        out.append(f'  {label}: ' + ('; '.join(parts) if parts else 'no tasks'))
    for m in acc['months']:
        line(m['month'], m)
    for b in acc['blocks']:
        line(f"tasks {b['block']}{' (short block)' if b['short'] else ''}", b)
    line('total', acc['total'])
    lo = acc['left_out']
    out.append(f"  left out: {lo['no_estimate']} without a stored estimate, {lo['during_work']} estimated during the "
               f"work, {lo['not_measured']} not measured.")
    if a.get('items_share') is not None:
        out.append(f"  (actual = tokens tied to the task: {a['items_share'] * 100:.0f}% of all tokens.)")
    for t in rep.get('open') or []:
        out.append(f"Open: {t['id']} has used {_fmt_tokens(t['fresh_so_far'])} tokens since its estimate. "
                   f"Run done when it ships.")
    return '\n'.join(out)
