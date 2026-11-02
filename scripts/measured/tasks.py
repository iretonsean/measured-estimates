"""The merged task view from append-only events of all machines, and measured actuals (REQ-24, REQ-25, REQ-34)."""
from __future__ import annotations

from . import store

BEFORE_WORK_S = 600  # an estimate counts as "before work" up to 10 minutes after the task's first message (REQ-40)


def merged(events: list) -> dict:
    out = {}
    for ev in sorted(events, key=lambda e: (e.get('at') or '', e.get('machine') or '', e.get('type') or '')):
        t = out.setdefault(ev['id'], {'id': ev['id'], 'size': None, 'kind': None, 'estimates': [], 'done': [],
                                      'done_at': None, 'updated_at': None, 'actual': None, 'status': 'open'})
        if ev.get('size'):
            t['size'] = ev['size']
        if ev.get('kind'):
            t['kind'] = ev['kind']
        if ev['type'] == 'estimate':
            t['estimates'].append(ev)
        elif ev['type'] == 'done':
            t['done'].append(ev)
            t['done_at'] = t['done_at'] or ev.get('at')
            t['updated_at'] = ev.get('at')
            t['actual'] = ev.get('actual')
            t['status'] = 'done'
    return out


def dominant_effort(by_effort: dict) -> str:
    """The known effort with the most tokens, when known efforts hold at least half; ties to the lower name."""
    total = sum(v for v in by_effort.values() if v)
    known = {e: v for e, v in by_effort.items() if e != 'unknown' and v}
    if not total or sum(known.values()) < 0.5 * total:
        return 'unknown'
    return sorted(known.items(), key=lambda x: (-x[1], x[0]))[0][0]


def is_measured(fresh: float, by_role: dict) -> bool:
    """REQ-25: build + review + fix > 0 and lead share <= 0.5."""
    work = sum(by_role.get(r, 0) for r in ('build', 'review', 'fix'))
    return work > 0 and fresh > 0 and by_role.get('lead', 0) <= 0.5 * fresh


def actual_for(task_id: str, lines: list) -> dict | None:
    fresh = 0
    by_role, bme, by_effort = {}, {}, {}
    active_s = 0
    start = end = None
    sessions, machines = set(), set()
    for ln in lines:
        v = (ln.get('tasks') or {}).get(task_id)
        if not v:
            continue
        fresh += v.get('fresh') or 0
        for r, x in (v.get('by_role') or {}).items():
            by_role[r] = by_role.get(r, 0) + (x or 0)
        for mo, es in (v.get('by_model_effort') or {}).items():
            for e, x in (es or {}).items():
                bme.setdefault(mo, {})[e] = bme.get(mo, {}).get(e, 0) + (x or 0)
                by_effort[e] = by_effort.get(e, 0) + (x or 0)
        active_s += v.get('active_s') or 0
        if v.get('start'):
            start = v['start'] if start is None else min(start, v['start'])
        if v.get('end'):
            end = v['end'] if end is None else max(end, v['end'])
        sessions.add((ln.get('machine'), ln.get('session_id')))
        machines.add(ln.get('machine'))
    if not sessions or fresh <= 0:
        return None
    elapsed = (store.parse_ts(end) - store.parse_ts(start)) / 3600 if start and end else None
    return {'fresh': fresh, 'by_role': by_role, 'by_model_effort': bme, 'dominant_effort': dominant_effort(by_effort),
            'active_h': round(active_s / 3600, 3), 'elapsed_h': round(elapsed, 3) if elapsed is not None else None,
            'start': start, 'end': end, 'sessions': len(sessions), 'machines': len(machines),
            'measured': is_measured(fresh, by_role)}


def first_estimate(task: dict) -> dict | None:
    return task['estimates'][0] if task.get('estimates') else None


def calibration_records(view: dict) -> tuple:
    """(records for calibrate, left_out_not_measured) from the done tasks of the merged view."""
    recs, left = [], 0
    for t in view.values():
        a = t.get('actual')
        if t['status'] != 'done' or not a:
            continue
        if not a.get('measured'):
            left += 1
            continue
        fe = first_estimate(t)
        recs.append({'id': t['id'], 'size': t.get('size'), 'kind': t.get('kind'),
                     'date': (a.get('end') or t.get('done_at') or '')[:10] or None,
                     'fresh': a['fresh'], 'active_h': a.get('active_h'), 'elapsed_h': a.get('elapsed_h'),
                     'guess': fe.get('guess') if fe else None, 'dominant_effort': a.get('dominant_effort')})
    return recs, left
