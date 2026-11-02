"""The evaluation script on invented data (REQ-39)."""
from __future__ import annotations

import json
import os
import random
import sys
import unittest

from helpers import ROOT, Env, iso

sys.path.insert(0, os.path.join(ROOT, 'tools', 'ci'))

import evaluate  # noqa: E402
from check_aggregates import check_results  # noqa: E402

DAY = 86400
T = 1_790_000_000


def invented_input(n=72, seed=7):
    rng = random.Random(seed)
    tasks = []
    for i in range(n):
        size = rng.choice(['XS', 'S', 'S', 'M', 'M', 'L'])
        base = {'XS': 1e5, 'S': 3e5, 'M': 8e5, 'L': 2e6}[size]
        actual = base * rng.lognormvariate(0, 0.6)
        start = T + (i // 5) * DAY + rng.randint(0, 3600)
        end = start + rng.randint(1800, 20000)
        lead = actual * (0.8 if i % 11 == 0 else 0.1)
        tasks.append({'id': f'CANARY-{i}', 'size': size, 'kind': rng.choice(['bug', 'feature']),
                      'guess': [base * 2, base * 5], 'actual': actual,
                      'by_role': {'build': actual - lead, 'lead': lead}, 'active_h': rng.uniform(0.2, 3),
                      'elapsed_h': rng.uniform(1, 10), 'start': iso(start)[:19] + 'Z', 'end': iso(end)[:19] + 'Z',
                      'by_effort': {rng.choice(['high', 'medium']): actual}})
    weeks = [{'week': evaluate.iso_week(iso(T + w * 7 * DAY)[:19] + 'Z'), 'total': 1e8, 'tied': 4.5e7} for w in range(3)]
    return {'snapshot': iso(T + 40 * DAY)[:19] + 'Z', 'tasks': tasks, 'weeks': weeks}


class TestEvaluate(Env):
    def test_reproducible_and_aggregate(self):
        """T-100 T-101 two runs give identical output; no task ID and no value cell from n < 5 in it."""
        inp = os.path.join(self.tmp, 'in.json')
        with open(inp, 'w') as f:
            json.dump(invented_input(), f)
        outs = []
        for k in ('a', 'b'):
            d = os.path.join(self.tmp, k)
            evaluate.run(inp, d, n_boot=200)
            outs.append((open(os.path.join(d, 'results.json')).read(), open(os.path.join(d, 'results.md')).read()))
        self.assertEqual(outs[0], outs[1])
        self.assertNotIn('CANARY', outs[0][0] + outs[0][1])
        res = json.loads(outs[0][0])
        self.assertEqual(check_results(res), [])
        p = res['primary_rolling_origin']
        self.assertGreater(p['n'], 20)
        for k in ('a_vs_G', 'b_vs_R', 'c_vs_N'):
            self.assertIn('verdict', p['H1'][k])
        self.assertIn(p['H2']['verdict'], ('pass', 'fail', 'inconclusive'))
        self.assertLess(res['counts']['e1m'], res['counts']['e1'])


if __name__ == '__main__':
    unittest.main()
