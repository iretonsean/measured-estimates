#!/usr/bin/env python3
"""Builds data/starter.json from an evaluation-input file (docs/EVALUATION.md section 4). Aggregates only (REQ-17):
per size with at least 5 measured tasks, n, the 50% range and median of tokens, active and elapsed hours, and the 80%
token range only when n >= 10; 2 significant figures; no IDs, dates or names.

  python3 tools/make_starter.py --input <file outside the repo> --out data/starter.json --origin "<one line>"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))

from evaluate import eligibility, measured  # noqa: E402
from measured.calibrate import ranges  # noqa: E402
from measured.stats import SMALL, TAILS, sig  # noqa: E402

SIZES = ['XS', 'XS-S', 'S', 'S-M', 'M', 'M-L', 'L', 'L-XL', 'XL']


def sig_pair(r):
    return [sig(r[0]), sig(r[1])] if r else None


def build(d: dict, origin: str) -> dict:
    e_all, _, _, _ = eligibility(d)
    pop = [t for t in e_all if t.get('size') in SIZES and measured(t)]
    sizes = {}
    for s in SIZES:
        lst = [{'fresh': t['actual'], 'active_h': t.get('active_h'), 'elapsed_h': t.get('elapsed_h')}
               for t in pop if t['size'] == s]
        if len(lst) < SMALL:
            continue
        r = ranges(lst)
        row = {'n': len(lst),
               'range50': {k: sig_pair(r['range50'][k]) for k in ('tokens', 'active_h', 'elapsed_h') if r['range50'][k]},
               'median': {k: sig(r['median'][k]) for k in ('tokens', 'active_h', 'elapsed_h') if r['median'][k] is not None},
               'narrow50': bool(r['narrow50'])}
        if len(lst) >= TAILS:
            row['range80'] = {'tokens': sig_pair(r['range80']['tokens'])}
            row['narrow80'] = bool(r['narrow80'])
        sizes[s] = row
    weeks = d.get('weeks') or []
    tot = sum(w.get('total', 0) for w in weeks)
    tied = sum(w.get('tied', 0) for w in weeks)
    out = {'schema_version': 1, 'origin': origin,
           'units': {'tokens': 'fresh tokens (output + new input + cache writes) tied to the task',
                     'active_h': 'hours with messages less than 30 minutes apart',
                     'elapsed_h': 'hours from the first message to the last commit, waits included'},
           'sizes': sizes}
    if tot and tied:
        out['attribution'] = {'items_share': sig(tied / tot), 'overhead': sig(tot / tied)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--origin', required=True)
    a = ap.parse_args(argv)
    with open(a.input, encoding='utf-8') as f:
        d = json.load(f)
    out = build(d, a.origin)
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(json.dumps(out, indent=1, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
