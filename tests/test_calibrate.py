"""Calibration and statistics (REQ-26)."""
from __future__ import annotations

import math
import statistics
import unittest

import helpers  # sets sys.path  # noqa

from measured import calibrate as C
from measured.stats import geomid, log_ratio, quantile, widened_levels


def task(i, fresh, size='S', date='2026-09-20', kind=None, guess=None):
    return {'id': f'T{i}', 'size': size, 'kind': kind, 'date': date, 'fresh': fresh, 'active_h': 1.0,
            'elapsed_h': 2.0, 'guess': guess, 'dominant_effort': 'high'}


class TestStats(unittest.TestCase):
    def test_quantile(self):
        """T-77 quantiles with linear interpolation."""
        self.assertEqual([quantile([5], p) for p in (0, 0.25, 0.5, 0.9, 1)], [5, 5, 5, 5, 5])
        self.assertEqual([quantile([3, 1], p) for p in (0, 0.25, 0.5, 0.9, 1)], [1, 1.5, 2, 2.8, 3])
        self.assertEqual([round(quantile([1, 2, 3, 4, 5], p), 9) for p in (0, 0.25, 0.5, 0.9, 1)], [1, 2, 3, 4.6, 5])
        self.assertIsNone(quantile([], 0.5))

    def test_widening(self):
        """T-130 widened levels: n 5 L 0.5 -> [0.125, 0.875]; n 5 L 0.8 clipped; n 41 L 0.5 -> [0.2375, 0.7625]."""
        self.assertEqual(widened_levels(5, 0.5), (0.125, 0.875, False))
        lo, hi, clipped = widened_levels(5, 0.8)
        self.assertEqual((lo, hi, clipped), (0.0, 1.0, True))
        lo, hi, clipped = widened_levels(41, 0.5)
        self.assertAlmostEqual(lo, 0.2375)
        self.assertAlmostEqual(hi, 0.7625)
        r = C.ranges([task(i, 100 * i) for i in range(1, 6)])
        self.assertTrue(r['narrow80'])
        self.assertFalse(r['narrow50'])

    def test_geometric_midpoint(self):
        """T-131 range [1, 4] and actual 2 gives error 0."""
        self.assertEqual(geomid([1, 4]), 2.0)
        self.assertEqual(abs(log_ratio(2, geomid([1, 4]))), 0.0)


class TestCalibrate(unittest.TestCase):
    def test_rows(self):
        """T-71 12 tasks give the expected row (hand-computed quantiles)."""
        cal = C.calibrate([task(i, 100 * i) for i in range(1, 13)])
        row = cal['sizes']['S']
        self.assertEqual((row['n'], row['source'], row['confidence']), (12, 'window', 'good'))
        lo, hi = row['estimate']['range50']['tokens']
        self.assertAlmostEqual(lo, 325.0)
        self.assertAlmostEqual(hi, 975.0)
        lo, hi = row['estimate']['range80']['tokens']
        self.assertAlmostEqual(lo, 130.0)
        self.assertAlmostEqual(hi, 1170.0)
        self.assertEqual(row['estimate']['median']['tokens'], 650.0)
        self.assertEqual(row['stats']['tokens']['p10'], quantile([100 * i for i in range(1, 13)], 0.1))

    def test_window_rule(self):
        """T-72 5 recent: window; 4 recent + 3 old: all; 2: scaled."""
        recent = [task(i, 100, date='2026-09-20') for i in range(5)]
        self.assertEqual(C.calibrate(recent)['sizes']['S']['source'], 'window')
        mix = [task(i, 100, date='2026-09-20') for i in range(4)] + [task(9 + i, 100, date='2026-07-01') for i in range(3)]
        self.assertEqual(C.calibrate(mix)['sizes']['S']['source'], 'all')
        three = [task(i, 100, date='2026-09-20') for i in range(3)]
        self.assertEqual(C.calibrate(three)['sizes']['S']['confidence'], 'rough')
        two = recent + [task(20, 500, size='M'), task(21, 500, size='M')]
        cal = C.calibrate(two)
        self.assertNotIn('M', cal['sizes'])
        self.assertTrue(C.estimate_for(cal, 'M')['scaled_from'] == 'S')

    def test_scaling(self):
        """T-73 scaling by the ratio of guesses, and by 2 per step without guesses."""
        s = [task(i, 100, guess=[50, 200]) for i in range(5)]
        m = [task(10, 900, size='M', guess=[150, 600])]
        cal = C.calibrate(s + m)
        r = C.estimate_for(cal, 'M')
        self.assertAlmostEqual(r['scale'], 3.0)
        self.assertAlmostEqual(r['estimate']['median']['tokens'], 300.0)
        cal = C.calibrate([task(i, 100) for i in range(5)])
        self.assertAlmostEqual(C.estimate_for(cal, 'L')['scale'], 4.0)
        self.assertAlmostEqual(C.estimate_for(cal, 'XS')['scale'], 0.5)

    def test_kind_cell(self):
        """T-74 a kind cell is used at n = 5, not at n = 4."""
        base = [task(i, 1000) for i in range(6)]
        four = [task(10 + i, 10, kind='bug') for i in range(4)]
        cal = C.calibrate(base + four)
        self.assertEqual(C.estimate_for(cal, 'S', 'bug')['from'], 'S')
        cal = C.calibrate(base + four + [task(20, 10, kind='bug')])
        r = C.estimate_for(cal, 'S', 'bug')
        self.assertEqual(r['from'], 'S bug')
        self.assertEqual(r['estimate']['median']['tokens'], 10)

    def test_attribution(self):
        """T-75 attribution share and overhead from session lines."""
        sessions = [{'last': '2026-09-20T10:00:00Z', 'fresh_tokens': 1000,
                     'tasks': {'ABC-1': {'fresh': 400}, 'process:review': {'fresh': 100}},
                     'untied': {'_after': 300, '_untagged': 200}},
                    {'last': '2026-01-01T10:00:00Z', 'fresh_tokens': 5000, 'tasks': {}, 'untied': {'_after': 5000}}]
        a = C.calibrate([task(i, 100) for i in range(5)], sessions)['attribution']
        self.assertEqual((a['total_tokens'], a['task_tokens'], a['process_tokens'], a['untied_tokens']), (1000, 400, 100, 500))
        self.assertAlmostEqual(a['items_share'], 0.4)
        self.assertAlmostEqual(a['overhead'], 2.5)
        self.assertEqual(C.calibrate([task(1, 5)], [])['attribution']['overhead'], 1.0)

    def test_backtest(self):
        """T-76 leave-one-out backtest numbers equal a direct computation."""
        vals = [100, 200, 300, 400, 500, 600]
        tasks = [task(i, v, guess=[100, 400]) for i, v in enumerate(vals)]
        bt = C.calibrate(tasks)['backtest']
        errs, ins = [], 0
        for i, a in enumerate(vals):
            rest = sorted(vals[:i] + vals[i + 1:])
            lo, hi = quantile(rest, 0.125), quantile(rest, 0.875)
            errs.append(abs(math.log(a / math.sqrt(lo * hi))))
            ins += lo <= a <= hi
        self.assertEqual(bt['size']['n'], 6)
        self.assertAlmostEqual(bt['size']['median_error'], statistics.median(errs))
        self.assertAlmostEqual(bt['size']['coverage50'], ins / 6)
        self.assertAlmostEqual(bt['guess']['median_error'], statistics.median(errs))


class TestDominantEffort(unittest.TestCase):
    def test_dominant(self):
        """T-14 the largest known share wins; a tie goes to the lower name; known share below 0.5 gives unknown."""
        from measured.tasks import dominant_effort
        self.assertEqual(dominant_effort({'high': 60, 'medium': 30, 'unknown': 10}), 'high')
        self.assertEqual(dominant_effort({'high': 40, 'medium': 40, 'unknown': 20}), 'high')
        self.assertEqual(dominant_effort({'low': 40, 'max': 40}), 'low')
        self.assertEqual(dominant_effort({'high': 40, 'unknown': 60}), 'unknown')
        self.assertEqual(dominant_effort({}), 'unknown')


if __name__ == '__main__':
    unittest.main()
