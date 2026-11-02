#!/usr/bin/env python3
"""Checks that shipped and published numbers are aggregates only (REQ-17, T-50, T-51, T-135).

  python3 tools/ci/check_aggregates.py data/starter.json [results.json ...]
  python3 tools/ci/check_aggregates.py --self-test
"""
from __future__ import annotations

import copy
import json
import sys

SMALL, TAILS = 5, 10
STARTER_TOP = {'schema_version', 'origin', 'units', 'attribution', 'sizes'}
STARTER_ROW = {'n', 'range50', 'range80', 'median', 'narrow50', 'narrow80'}
MEASURES = {'tokens', 'active_h', 'elapsed_h'}
# Keys that may hold a number in an object with n < 5 (counts and labels, not values computed from the tasks).
COUNT_KEYS = {'n', 'days', 'draws', 'n_test', 'n_train', 'n80', 'nominal', 'kinds_other', 'below', 'inside', 'above',
              'weeks', 'to_scaled_or_N', 'to_N', 'no_start'}


def check_starter(d) -> list:
    errs = []
    if not isinstance(d, dict):
        return ['starter: not an object']
    extra = set(d) - STARTER_TOP
    if extra:
        errs.append(f'starter: extra keys {sorted(extra)}')
    if not isinstance(d.get('origin'), str) or '\n' in d.get('origin', '') or len(d.get('origin', '')) > 300:
        errs.append('starter: origin must be one line')
    if set(d.get('attribution') or {}) - {'items_share', 'overhead'}:
        errs.append('starter: attribution has extra keys')
    for size, row in (d.get('sizes') or {}).items():
        if set(row) - STARTER_ROW:
            errs.append(f'starter {size}: extra keys {sorted(set(row) - STARTER_ROW)}')
        n = row.get('n')
        if not isinstance(n, int) or n < SMALL:
            errs.append(f'starter {size}: n must be >= {SMALL}')
            continue
        if ('range80' in row or 'narrow80' in row) and n < TAILS:
            errs.append(f'starter {size}: 80% range needs n >= {TAILS}')
        for part in ('range50', 'range80', 'median'):
            if part in row and set(row[part]) - MEASURES:
                errs.append(f'starter {size}.{part}: extra keys')
        for k in ('range80',):
            if k in row and set(row[k]) - {'tokens'}:
                errs.append(f'starter {size}.range80: tokens only')
    return errs


def _numeric(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, list):
        return any(_numeric(x) for x in v)
    return False


def check_results(d, path='$') -> list:
    """Every object with an integer n < 5 holds only counts and labels; p10/p90 only with n >= 10; no 'id' keys."""
    errs = []
    if isinstance(d, dict):
        n = d.get('n')
        if 'id' in d or 'ids' in d:
            errs.append(f'{path}: task id key')
        if isinstance(n, int) and not isinstance(n, bool):
            if n < SMALL:
                for k, v in d.items():
                    if k not in COUNT_KEYS and _numeric(v):
                        errs.append(f'{path}.{k}: value from n = {n} < {SMALL}')
            if n < TAILS:
                for k in ('p10', 'p90'):
                    if d.get(k) is not None:
                        errs.append(f'{path}.{k}: needs n >= {TAILS}')
        for k, v in d.items():
            errs += check_results(v, f'{path}.{k}')
    elif isinstance(d, list):
        for i, v in enumerate(d):
            errs += check_results(v, f'{path}[{i}]')
    return errs


def self_test() -> int:
    good = {'schema_version': 1, 'origin': 'one line', 'units': {}, 'sizes': {
        'S': {'n': 12, 'range50': {'tokens': [1, 2]}, 'range80': {'tokens': [0.5, 3]}, 'median': {'tokens': 1.5}}}}
    ok = not check_starter(good)
    bad = copy.deepcopy(good)
    bad['sizes']['S']['ids'] = ['x']
    ok &= bool(check_starter(bad))
    bad = copy.deepcopy(good)
    bad['sizes']['M'] = {'n': 4, 'range50': {'tokens': [1, 2]}, 'median': {'tokens': 1}}
    ok &= bool(check_starter(bad))
    bad = copy.deepcopy(good)
    bad['sizes']['S']['n'] = 7
    ok &= bool(check_starter(bad))
    res = {'rows': [{'n': 12, 'median_error': 0.5}, {'n': 1, 'note': 'n too small'}]}
    ok &= not check_results(res)
    res['rows'].append({'n': 1, 'median_actual': 123.0})
    ok &= bool(check_results(res))
    ok &= bool(check_results({'n': 7, 'p10': 1.0}))
    print('self-test ok' if ok else 'self-test FAILED')
    return 0 if ok else 1


def main(argv) -> int:
    if '--self-test' in argv:
        return self_test()
    errs = []
    for p in argv[1:]:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        errs += [f'{p}: {e}' for e in (check_starter(d) if p.endswith('starter.json') else check_results(d))]
    for e in errs:
        print(e)
    print(f'{len(errs)} problems')
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
