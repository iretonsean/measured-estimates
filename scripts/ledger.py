#!/usr/bin/env python3
"""measured-estimates command line (REQ-19..REQ-28). Contract: docs/CLI.md. Every command takes --json.

Exit codes: 0 done, 1 bad input, 2 no data.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

if sys.version_info < (3, 9):  # pragma: no cover
    sys.stderr.write('measured-estimates needs Python 3.9 or newer.\n')
    sys.exit(1)

from measured import VERSION, calibrate as cal_mod, paths, report as report_mod, store, tasks as tasks_mod  # noqa: E402
from measured.ids import DEFAULT_PATTERN, Matcher, pattern_from_example, validate_pattern  # noqa: E402
from measured.stats import TAILS, geomid, log_ratio, sig  # noqa: E402

STARTER = os.path.join(os.path.dirname(HERE), 'data', 'starter.json')
ID_OK = re.compile(r'[A-Za-z0-9#._:-]{1,64}')
KIND_OK = re.compile(r'[A-Za-z0-9 _-]{1,32}')


class Fail(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def emit(args, data: dict, text: str) -> None:
    if args.json:
        print(json.dumps(data, sort_keys=True, default=str))
    else:
        print(text)


# ---- shared state -----------------------------------------------------------------------------------------------------

def load_state(cfg):
    lines = store.read_ledger()
    view = tasks_mod.merged(store.read_events())
    recs, left = tasks_mod.calibration_records(view)
    cal = cal_mod.calibrate(recs, lines, scale=cfg.get('sizes'), now=store.now_iso(), left_out=left,
                            with_backtest=False)
    return lines, view, recs, cal


def load_starter() -> dict:
    try:
        with open(STARTER, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'sizes': {}}


def parse_tokens(s: str) -> float:
    m = re.fullmatch(r'\s*([0-9]*\.?[0-9]+)\s*([kKmM]?)\s*', s or '')
    if not m:
        raise Fail(f'not a token count: {s!r} (use forms such as 400k or 1.2M)')
    return float(m.group(1)) * {'': 1, 'k': 1e3, 'm': 1e6}[m.group(2).lower()]


def parse_guess(s):
    if not s:
        return None
    parts = re.split(r'\s*(?:-|to|\.\.)\s*', s.strip(), maxsplit=1)
    if len(parts) != 2:
        raise Fail('--guess needs a range, for example 400k-1.2M')
    lo, hi = parse_tokens(parts[0]), parse_tokens(parts[1])
    if not 0 < lo <= hi:
        raise Fail('--guess: low must be above 0 and not above high')
    return [lo, hi]


def ftok(v):
    if v is None:
        return '-'
    return f'{sig(v / 1e6, 2):g}M' if v >= 1e6 else f'{sig(v / 1e3, 2):g}k'


def frange(r, unit=''):
    if not r:
        return '-'
    if unit == 'tok':
        return f'{ftok(r[0])} to {ftok(r[1])}'
    return f'{sig(r[0], 2):g} to {sig(r[1], 2):g}{unit}'


# ---- commands ---------------------------------------------------------------------------------------------------------

def cmd_init(args):
    cfg = paths.load_config()
    existed = cfg.get('_exists')
    if not cfg.get('machine_id'):
        cfg['machine_id'] = paths.new_machine_id()
    interactive = not args.yes and not args.json and sys.stdin.isatty()
    pattern = args.id_pattern
    example = args.example
    if interactive and not pattern and not example:
        example = input('One example task ID (for example ENG-42 or #12). Empty: any ABC-123 form on ITEM lines: ').strip()
    if example and not pattern:
        try:
            pattern = pattern_from_example(example)
        except ValueError as e:
            raise Fail(str(e))
    if pattern:
        why = validate_pattern(pattern, limit_s=args.pattern_time_limit)
        if why:
            raise Fail(f'ID pattern refused: {why}. The config is unchanged.')
        if example and not Matcher([pattern]).find(example):
            raise Fail(f'the pattern does not match the example {example!r}. The config is unchanged.')
        cfg['id_patterns'] = [pattern]
    confirm = args.confirm_ids
    if interactive and pattern and pattern != DEFAULT_PATTERN and not confirm:
        confirm = input('May commit messages and git commands be used to find these IDs? [y/N] ').strip().lower() == 'y'
    if confirm:
        if cfg['id_patterns'] == [DEFAULT_PATTERN]:
            raise Fail('confirm a pattern from your own example first (--example ENG-42), not the default one')
        cfg['commit_ids'] = True
    if args.no_commit_ids:
        cfg['commit_ids'] = False
    remote = args.sync_remote
    if interactive and remote is None:
        remote = input('Sync remote (a private git repo you own), or empty for none: ').strip() or None
    if remote is not None:
        if remote and remote.lower().startswith('http://'):
            raise Fail('http:// remotes are refused; use ssh or https')
        cfg['sync'] = {**cfg.get('sync', {}), 'remote': remote or None}
    for pat in args.ignore or []:
        if not isinstance(pat, str) or not pat.strip() or len(pat) > 300:
            raise Fail('--ignore: a folder glob, for example ~/work/client-*')
        if pat not in cfg.get('ignore_paths', []):
            cfg['ignore_paths'] = list(cfg.get('ignore_paths') or []) + [pat]
    for d in (paths.config_dir(), paths.data_dir(), paths.ledger_dir(), paths.tasks_dir(), paths.state_dir()):
        paths.private_dir(d)
    if os.path.exists(paths.stopped_path()):
        os.unlink(paths.stopped_path())  # recording starts again
    cfg['initialized'] = True
    paths.save_config(cfg)
    data = {'config': paths.config_path(), 'store': paths.data_dir(), 'state': paths.state_dir(),
            'machine_id': cfg['machine_id'], 'id_patterns': cfg['id_patterns'], 'commit_ids': cfg['commit_ids'],
            'sync': bool((cfg.get('sync') or {}).get('remote')), 'existed': bool(existed),
            'ignore_paths': cfg.get('ignore_paths') or [],
            'python': sys.executable, 'python_version': '.'.join(map(str, sys.version_info[:3])), 'version': VERSION}
    text = (f"Ready. Config: {paths.tilde(data['config'])}. Store: {paths.tilde(data['store'])}.\n"
            f"Python: {data['python']} {data['python_version']}.\n"
            f"Task IDs: {', '.join(cfg['id_patterns'])} (commit messages {'used' if cfg['commit_ids'] else 'not used'}).\n"
            f"Sync: {'on' if data['sync'] else 'off'}. Ignored folders: {', '.join(data['ignore_paths']) or 'none'}.\n"
            "Next: run backfill to read the sessions Claude Code still keeps.")
    emit(args, data, text)


def cmd_backfill(args):
    import adapters
    from adapters.base import Deadline
    from measured.recorder import record
    if os.path.exists(paths.stopped_path()):
        raise Fail('recording is off since forget; run init first')
    cfg = paths.ensure_config()
    days = args.days or cfg.get('backfill_days') or 30
    ad = adapters.get('claude-code')
    sessions = ad.list_sessions(time.time() - days * 86400)
    done = skipped = failed = 0
    oldest = None
    for path, sid, t0 in sessions:
        try:
            e = record({'session_id': sid, 'transcript_path': path, 'cwd': ''}, cfg, 'backfill',
                       time.monotonic() + 120, ad)
        except (Deadline, store.LockTimeout, store.NewerSchema):
            failed += 1
            continue
        if e:
            done += 1
            oldest = min(oldest or e['first'], e['first'])
        else:
            skipped += 1
    data = {'sessions_found': len(sessions), 'recorded': done, 'skipped': skipped, 'failed': failed,
            'oldest': oldest, 'days': days}
    emit(args, data, f"Backfill: {done} sessions recorded, {skipped} without tokens or ignored, {failed} failed "
                     f"(last {days} days; oldest recorded session starts {oldest or '-'}).")


def _effort_row(row, effort):
    be = (row.get('by_effort') or {}).get(effort)
    if be and be.get('n', 0) >= 5 and be.get('estimate'):
        return be
    return None


def cmd_estimate(args):
    cfg = paths.ensure_config()
    scale = cfg.get('sizes')
    size = cal_mod.norm_size(args.size, scale)
    if not size:
        raise Fail(f"--size: use one of {', '.join(scale)} or a range such as S-M")
    if args.kind and not KIND_OK.fullmatch(args.kind):
        raise Fail('--kind: at most 32 letters, digits, spaces, _ or -')
    if args.effort and not re.fullmatch(r'[a-z0-9-]{1,16}', args.effort):
        raise Fail('--effort: a word such as low, medium or high')
    guess = parse_guess(args.guess)
    lines, view, recs, cal = load_state(cfg)
    own_n = sum(1 for r in recs if cal_mod.norm_size(r.get('size'), scale) == size)
    notes = []
    starter = load_starter()
    if own_n >= 5:
        row = cal_mod.estimate_for(cal, size, args.kind)
        source, label = 'own', 'your data'
        att = cal.get('attribution') or {}
    else:
        srow = (starter.get('sizes') or {}).get(size)
        if srow:
            row = {'n': srow['n'], 'estimate': {'range50': srow['range50'], 'range80': srow.get('range80') or {},
                                                'narrow50': srow.get('narrow50', False)},
                   'confidence': 'good' if srow['n'] >= 10 else 'low', 'from': f'starter {size}'}
        else:
            measured = {s: {'n': r['n'], 'estimate': {'range50': r['range50'], 'range80': r.get('range80') or {}},
                            '_tasks': None} for s, r in (starter.get('sizes') or {}).items()}
            row = None
            v = cal_mod.size_value(size, scale)
            if measured and v is not None:
                ref = sorted(measured, key=lambda s: (abs(cal_mod.size_value(s, scale) - v), -cal_mod.size_value(s, scale)))[0]
                f = 2 ** (v - cal_mod.size_value(ref, scale))
                m = measured[ref]['estimate']
                mul = lambda r: [x * f for x in r] if r else None
                row = {'n': measured[ref]['n'], 'confidence': 'rough', 'from': f'starter {ref} x {f:g}',
                       'estimate': {'range50': {k: mul(v2) for k, v2 in m['range50'].items()},
                                    'range80': {'tokens': mul((m.get('range80') or {}).get('tokens'))}}}
        source, label = 'starter', 'starter, not your data'
        att = starter.get('attribution') or {}
        notes.append(f'{size} has {own_n} of your measured tasks; your own range replaces the starter at 5.')
    if not row:
        raise Fail(f'no data for size {size}', 2)
    est = row['estimate']
    if args.effort:
        er = _effort_row(row, args.effort) if source == 'own' else None
        if er:
            est = er['estimate']
            notes.append(f"effort {args.effort}: range from {er['n']} tasks at that effort")
        else:
            notes.append(f'effort {args.effort}: fewer than 5 of your tasks at that effort for {size}; '
                         f'this is the range for all efforts')
    n = row.get('n', 0)
    r80 = (est.get('range80') or {}).get('tokens') if n >= TAILS else None
    if r80 is None:
        notes.append('the 80% range needs 10 of your tasks of this size' if source == 'own' or n < TAILS
                      else 'the starter table has no 80% range for this size')
    out = {
        'size': size, 'kind': args.kind, 'effort': args.effort, 'source': source, 'label': label, 'n': n,
        'confidence': row.get('confidence'), 'from': row.get('from'),
        'range50': {k: est['range50'].get(k) for k in ('tokens', 'active_h', 'elapsed_h')},
        'range80': {'tokens': r80}, 'narrow': bool(est.get('narrow50')),
        'items_share': att.get('items_share'), 'overhead': att.get('overhead'),
        'guess': guess, 'warnings': [w['code'] for w in store.recent_warnings()], 'notes': notes,
    }
    if args.for_id:
        if not ID_OK.fullmatch(args.for_id):
            raise Fail('--for: an ID of letters, digits and #._:- (at most 64)')
        if not Matcher(cfg['id_patterns']).is_key(args.for_id):
            notes.append(f'{args.for_id} does not match your ID pattern; sessions are tied to it only with an '
                         f'"ITEM: {args.for_id}" line if the pattern matches. Run init --example {args.for_id}.')
        ev = {'schema_version': 1, 'type': 'estimate', 'id': args.for_id, 'at': store.now_iso(),
              'machine': cfg['machine_id'], 'size': size, 'kind': args.kind, 'effort': args.effort, 'guess': guess,
              'range50': out['range50'], 'range80': out['range80'], 'n': n, 'source': source,
              'confidence': out['confidence'], 'narrow': out['narrow'], 'calibration_at': cal.get('updated')}
        store.append_event(cfg['machine_id'], ev)
        out['stored_for'] = args.for_id
    r = out['range50']
    text = [f"{size}{' ' + args.kind if args.kind else ''} ({label}, n {n}, {out['confidence']}):",
            f"  50% range: {frange(r['tokens'], 'tok')} tokens, {frange(r['active_h'], ' h')} work, "
            f"{frange(r['elapsed_h'], ' h')} elapsed{' (may be too narrow, n small)' if out['narrow'] else ''}",
            f"  80% range: {frange(r80, 'tok')} tokens" if r80 else '  80% range: not enough tasks yet (see note)']
    if out['items_share'] is not None:
        text.append(f"  Tokens tied to tasks: {out['items_share'] * 100:.0f}% of all tokens"
                    f"{' (starter data)' if source == 'starter' else ''}; total use is about "
                    f"x{sig(out['overhead'], 2)} of task tokens.")
    text += [f'  Note: {x}' for x in notes]
    if out['warnings']:
        text.append(f"  Warnings: {', '.join(out['warnings'])} (run report)")
    if args.for_id:
        text.append(f'  Stored as the estimate for {args.for_id}.')
    emit(args, out, '\n'.join(text))


def cmd_done(args):
    cfg = paths.ensure_config()
    if not ID_OK.fullmatch(args.id):
        raise Fail('ID: letters, digits and #._:- (at most 64)')
    scale = cfg.get('sizes')
    size = cal_mod.norm_size(args.size, scale) if args.size else None
    if args.size and not size:
        raise Fail(f"--size: use one of {', '.join(scale)}")
    if args.kind and not KIND_OK.fullmatch(args.kind):
        raise Fail('--kind: at most 32 letters, digits, spaces, _ or -')
    lines = store.read_ledger()
    actual = tasks_mod.actual_for(args.id, lines)
    if not actual:
        raise Fail(f'no recorded tokens for {args.id}. Tag its sessions with "ITEM: {args.id}" or put the ID in '
                   f'commit messages.', 2)
    view = tasks_mod.merged(store.read_events())
    t = view.get(args.id) or {}
    ev = {'schema_version': 1, 'type': 'done', 'id': args.id, 'at': store.now_iso(), 'machine': cfg['machine_id'],
          'size': size or t.get('size'), 'kind': args.kind or t.get('kind'), 'actual': actual}
    store.append_event(cfg['machine_id'], ev)
    view = tasks_mod.merged(store.read_events())
    t = view[args.id]
    errs = {}
    for name, e in (('first', t['estimates'][0] if t['estimates'] else None),
                    ('last', t['estimates'][-1] if t['estimates'] else None)):
        rng = (e or {}).get('range50', {}).get('tokens') if e else None
        errs[name] = log_ratio(actual['fresh'], geomid(rng)) if rng else None
    recs, left = tasks_mod.calibration_records(view)
    cal = cal_mod.calibrate(recs, lines, scale=scale, now=store.now_iso(), left_out=left)
    store.atomic_write(paths.calibration_path(), json.dumps(cal_mod.strip_private(cal), indent=1, sort_keys=True,
                                                            default=str) + '\n')
    out = {'id': args.id, 'actual': actual, 'error_first': errs['first'], 'error_last': errs['last'],
           'size': t.get('size'), 'kind': t.get('kind')}
    text = [f"{args.id} done: {ftok(actual['fresh'])} tokens tied to it, {actual['active_h']:.2g} h work, "
            f"{(actual['elapsed_h'] or 0):.2g} h elapsed, {actual['sessions']} session{'' if actual['sessions'] == 1 else 's'}."]
    if not actual['measured']:
        text.append('  Not measured: most of its tokens are lead work, so the build ran where the ledger did not see '
                    'it. It is left out of the calibration.')
    if errs['first'] is not None:
        last = '' if errs['last'] is None or len(t['estimates']) < 2 else f"; last estimate: {errs['last']:+.2f}"
        text.append(f"  Against the first stored estimate: ln(actual/midpoint) = {errs['first']:+.2f}{last}. "
                    f"(The report counts only estimates stored before the work started.)")
    else:
        text.append('  No estimate was stored for it (estimate --for).')
    if not t.get('size'):
        text.append('  No size: pass --size so it can calibrate future estimates.')
    emit(args, out, '\n'.join(text))


def cmd_report(args):
    cfg = paths.ensure_config()
    lines, view, recs, cal = load_state(cfg)
    rep = report_mod.build(cal, view, lines, aggregate=args.aggregate)
    rep['initialized'] = bool(cfg.get('initialized'))
    if args.aggregate:
        rep.pop('sync', None)
    emit(args, rep, report_mod.text(rep))


def cmd_calibrate(args):
    cfg = paths.ensure_config()
    lines = store.read_ledger()
    view = tasks_mod.merged(store.read_events())
    recs, left = tasks_mod.calibration_records(view)
    cal = cal_mod.calibrate(recs, lines, scale=cfg.get('sizes'), now=store.now_iso(), left_out=left)
    clean = cal_mod.strip_private(cal)
    store.atomic_write(paths.calibration_path(), json.dumps(clean, indent=1, sort_keys=True, default=str) + '\n')
    rep = report_mod.size_table(cal)
    bt = cal.get('backtest') or {}
    data = {'sizes': rep, 'attribution': clean['attribution'], 'data': clean['data'], 'backtest': bt,
            'written': paths.calibration_path()}
    text = report_mod.text({'warnings': [], 'sync': None, 'sizes': rep, 'attribution': clean['attribution'],
                            'left_out_not_measured': left, 'accuracy': report_mod.accuracy(view), 'open': []})
    emit(args, data, text)


def cmd_forget(args):
    targets = [paths.config_dir(), paths.data_dir(), paths.state_dir()]
    present = [d for d in targets if os.path.exists(d)]
    stop_note = ('Recording is off until you run init again. The plugin stays installed; to remove it, run '
                 '/plugin uninstall measured-estimates.')
    if args.yes:
        for d in present:
            shutil.rmtree(d, ignore_errors=True)
        # Leave only an empty marker, so this session's own end (and every later one) records nothing until init.
        paths.private_dir(paths.state_dir())
        os.close(os.open(paths.stopped_path(), os.O_WRONLY | os.O_CREAT, 0o600))
    data = {'deleted' if args.yes else 'would_delete': present, 'kept': 'Claude Code session files; any sync remote',
            'recording': 'off until init' if args.yes else 'on'}
    if args.yes:
        text = ('Deleted:\n' + '\n'.join(f'  {paths.tilde(d)}' for d in present) if present else 'Nothing to delete.') \
            + '\n' + stop_note
    else:
        text = ('This deletes:\n' + '\n'.join(f'  {paths.tilde(d)}' for d in present) +
                '\nRun again with --yes to delete. It also turns recording off until you run init again. Claude Code '
                'session files and any sync remote are not touched.' if present else 'Nothing to delete.')
    emit(args, data, text)


def parser():
    p = argparse.ArgumentParser(prog='ledger', description='measured-estimates: estimates from measured past work.')
    p.add_argument('--version', action='version', version=VERSION)
    sub = p.add_subparsers(dest='cmd', required=True)

    def add(name, fn, help_text):
        s = sub.add_parser(name, help=help_text)
        s.add_argument('--json', action='store_true', help='print one JSON object')
        s.set_defaults(fn=fn)
        return s
    s = add('init', cmd_init, 'create the config and the store')
    s.add_argument('--example', help='one example task ID, for example ENG-42 or #12')
    s.add_argument('--id-pattern', help='a regular expression for task IDs (instead of --example)')
    s.add_argument('--confirm-ids', action='store_true', help='also use commit messages and git commands')
    s.add_argument('--no-commit-ids', action='store_true', help='stop using commit messages')
    s.add_argument('--sync-remote', help='a private git remote you own ("" turns sync off)')
    s.add_argument('--ignore', action='append', help='a folder glob not to record, for example ~/work/client-* '
                                                     '(repeatable; adds to ignore_paths)')
    s.add_argument('--yes', action='store_true', help='ask nothing; use the flags and defaults')
    s.add_argument('--pattern-time-limit', type=float, default=0.05, help=argparse.SUPPRESS)
    s = add('backfill', cmd_backfill, 'record the sessions Claude Code still keeps')
    s.add_argument('--days', type=int)
    s = add('estimate', cmd_estimate, 'ranges for a new task')
    s.add_argument('--size', required=True)
    s.add_argument('--kind')
    s.add_argument('--effort')
    s.add_argument('--guess', help="your own guess first, for example 400k-1.2M")
    s.add_argument('--for', dest='for_id', help='store this estimate for a task ID')
    s = add('done', cmd_done, 'mark a task finished and measure it')
    s.add_argument('id')
    s.add_argument('--size')
    s.add_argument('--kind')
    s = add('report', cmd_report, 'sizes, attribution, accuracy over time')
    s.add_argument('--aggregate', action='store_true', help='no task IDs, no values from fewer than 5 tasks')
    add('calibrate', cmd_calibrate, 'rebuild calibration.json')
    s = add('forget', cmd_forget, 'delete all stored data')
    s.add_argument('--yes', action='store_true')
    return p


def main(argv=None) -> int:
    os.umask(0o077)
    args = parser().parse_args(argv)
    try:
        args.fn(args)
        return 0
    except Fail as e:
        if getattr(args, 'json', False):
            print(json.dumps({'error': str(e), 'code': e.code}))
        sys.stderr.write(f'{e}\n')
        return e.code
    except store.NewerSchema as e:
        sys.stderr.write(f'{e}: written by a newer version; update the plugin. Nothing was changed.\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
