#!/usr/bin/env python3
"""Timing checks (T-93 recording cost, T-114 hook process return time) on generated, invented data.

  python3 tools/ci/timing.py [--child-budget 2.0] [--hook-budget 0.2]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))


def build(tmp):
    from helpers import T0, Tx
    os.environ.update({'HOME': tmp, 'XDG_CONFIG_HOME': f'{tmp}/c', 'XDG_DATA_HOME': f'{tmp}/d',
                       'XDG_STATE_HOME': f'{tmp}/s', 'CLAUDE_CONFIG_DIR': f'{tmp}/claude'})
    from measured import paths, store
    cfg = paths.ensure_config()
    p = os.path.join(tmp, 'claude', 'projects', 'p', 'big.jsonl')
    main = Tx().prompt(T0, 'ITEM: ABC-1\nROLE: build')
    for i in range(3500):
        main.msg(T0 + i * 5, fresh=1000, key=f'm{i}')
    main.write(p)
    for s in range(3):
        sub = Tx().prompt(T0 + s, 'ITEM: ABC-2')
        for i in range(500):
            sub.msg(T0 + s * 10000 + i * 5, fresh=500, key=f's{s}-{i}')
        sub.write(os.path.join(p[:-6], 'subagents', f'agent-{s}.jsonl'))
    path = store.ledger_file(cfg['machine_id'])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = {'schema_version': 1, 'session_id': '', 'machine': cfg['machine_id'], 'fresh_tokens': 10, 'tasks': {},
           'untied': {}, 'first': '2026-01-01T00:00:00Z', 'last': '2026-01-01T00:00:00Z'}
    with open(path, 'w') as f:
        for i in range(20000):
            row['session_id'] = f'old-{i}'
            f.write(json.dumps(row) + '\n')
    return p, cfg


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--child-budget', type=float, default=2.0)
    ap.add_argument('--hook-budget', type=float, default=0.2)
    a = ap.parse_args(argv)
    base = os.environ.get('RUNNER_TEMP') or os.path.join(os.path.expanduser('~'), '.cache', 'measured-estimates-build')
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='timing-', dir=base)
    try:
        p, cfg = build(tmp)
        from measured.recorder import record
        times = []
        for _ in range(5):
            t = time.perf_counter()
            e = record({'session_id': 'big', 'transcript_path': p, 'cwd': ''}, cfg, 'manual', time.monotonic() + 60)
            times.append(time.perf_counter() - t)
        assert e['messages'] == 5000, e['messages']
        child = statistics.median(times)
        hook = []
        script = os.path.join(ROOT, 'scripts', 'record.py')
        for _ in range(20):
            t = time.perf_counter()
            subprocess.run([sys.executable, script, 'session-end'], input=json.dumps(
                {'session_id': 'big', 'transcript_path': p, 'cwd': ''}), text=True, timeout=30)
            hook.append(time.perf_counter() - t)
        hook.sort()
        p95 = hook[int(0.95 * (len(hook) - 1))]
        time.sleep(3)  # let the detached children finish before the folder goes
        print(f'T-93 child record: median {child:.3f} s (budget {a.child_budget} s); '
              f'T-114 hook process: p95 {p95 * 1000:.0f} ms (budget {a.hook_budget * 1000:.0f} ms)')
        ok = child <= a.child_budget and p95 <= a.hook_budget
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
