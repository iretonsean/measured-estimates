"""Commands: estimate, done, report, accuracy over time, calibrate, forget, backfill (REQ-19..REQ-28, REQ-40)."""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import time
import unittest

from helpers import ROOT, T0, Env, Tx, iso

from measured import paths, store


def line(sid, tasks, machine=None, first=T0, last=T0 + 3600, untied=None, role='build', effort='high'):
    """An invented ledger line: tasks = {id: fresh}."""
    mid = machine or paths.load_config()['machine_id']
    tk = {}
    for k, v in tasks.items():
        br = {role: v} if isinstance(role, str) else role(k, v)
        tk[k] = {'fresh': v, 'by_role': br, 'by_model_effort': {'model-a': {effort: v}}, 'active_s': 1800,
                 'start': iso(first)[:19] + 'Z', 'end': iso(last)[:19] + 'Z'}
    total = sum(tasks.values()) + sum((untied or {}).values())
    d = {'schema_version': 1, 'session_id': sid, 'agent': 'claude-code', 'adapter_version': '1', 'machine': mid,
         'reason': 'manual', 'recorded_at': iso(last)[:19] + 'Z', 'first': iso(first)[:19] + 'Z',
         'last': iso(last)[:19] + 'Z', 'messages': 3, 'duplicate_messages': 0, 'subagents': 0, 'skipped_lines': 0,
         'fresh_tokens': total, 'cache_read_tokens': 0,
         'by_model_effort': {'model-a': {effort: {'fresh': total, 'cache_reads': 0, 'messages': 3}}},
         'tasks': tk, 'untied': untied or {}, 'tagged': None, 'commits': 0}
    store.replace_session_line(mid, d)
    return d


class Base(Env):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.ledger('init', '--yes', '--example', 'ABC-1')[0], 0)


class TestEstimate(Base):
    def test_fields(self):
        """T-60 T-62 estimate prints ranges with n, source, confidence, share and overhead; unknown size exits 1."""
        code, out = self.ledger('estimate', '--size', 'M')
        self.assertEqual(code, 0)
        for k in ('range50', 'range80', 'n', 'source', 'confidence', 'items_share', 'overhead', 'warnings', 'label'):
            self.assertIn(k, out)
        self.assertEqual(len(out['range50']['tokens']), 2)
        self.assertLessEqual(out['range50']['tokens'][0], out['range50']['tokens'][1])
        self.assertEqual(out['source'], 'starter')
        self.assertEqual(out['label'], 'starter, not your data')
        code, out = self.ledger('estimate', '--size', 'HUGE')
        self.assertEqual(code, 1)
        self.assertIn('XS', out['error'])

    def test_store_for(self):
        """T-61 --for stores the estimate; the JSON output equals the stored event's estimate part."""
        code, out = self.ledger('estimate', '--size', 'S', '--guess', '100k-300k', '--for', 'ABC-1')
        ev = store.read_events()[0]
        self.assertEqual(ev['range50'], out['range50'])
        self.assertEqual(ev['guess'], [100000.0, 300000.0])
        self.assertEqual((ev['source'], ev['n']), (out['source'], out['n']))

    def test_own_replaces_starter(self):
        """T-63 T-64 4 own tasks of size S: starter; 5: own. Size M stays starter."""
        for i in range(1, 6):
            line(f's{i}', {f'ABC-{i}': 1000 * i})
            self.ledger('done', f'ABC-{i}', '--size', 'S')
            code, out = self.ledger('estimate', '--size', 'S')
            self.assertEqual(out['source'], 'starter' if i < 5 else 'own', i)
        self.assertEqual(out['n'], 5)
        self.assertEqual(self.ledger('estimate', '--size', 'M')[1]['source'], 'starter')

    def test_effort(self):
        """T-65 5 tasks at high: an effort range; 4 tasks at low: the size range and a note."""
        for i in range(1, 6):
            line(f'h{i}', {f'ABC-{i}': 1000 * i}, effort='high')
            self.ledger('done', f'ABC-{i}', '--size', 'S')
        for i in range(6, 10):
            line(f'l{i}', {f'ABC-{i}': 100000 * i}, effort='low')
            self.ledger('done', f'ABC-{i}', '--size', 'S')
        code, hi = self.ledger('estimate', '--size', 'S', '--effort', 'high')
        code, lo = self.ledger('estimate', '--size', 'S', '--effort', 'low')
        self.assertTrue(any('range from 5 tasks' in n for n in hi['notes']))
        self.assertLess(hi['range50']['tokens'][1], lo['range50']['tokens'][1])
        self.assertTrue(any('fewer than 5' in n for n in lo['notes']))

    def test_two_estimates(self):
        """T-66 T-67 two estimates for one task are both kept, the first unchanged; done reports both errors."""
        self.ledger('estimate', '--size', 'S', '--for', 'ABC-1')
        first = store.read_events()[0]
        time.sleep(1.1)
        self.ledger('estimate', '--size', 'M', '--for', 'ABC-1')
        evs = store.read_events()
        self.assertEqual(evs[0], first)
        self.assertEqual(len(evs), 2)
        line('s1', {'ABC-1': 500000})
        code, out = self.ledger('done', 'ABC-1')
        self.assertIsNotNone(out['error_first'])
        self.assertIsNotNone(out['error_last'])
        self.assertNotEqual(out['error_first'], out['error_last'])


class TestDone(Base):
    def test_two_machines(self):
        """T-68 two machine files with shares of ABC-1 sum into one actual."""
        line('a', {'ABC-1': 300})
        line('b', {'ABC-1': 700}, machine='0123456789abcdef')
        code, out = self.ledger('done', 'ABC-1', '--size', 'S')
        self.assertEqual((out['actual']['fresh'], out['actual']['machines'], out['actual']['sessions']), (1000, 2, 2))

    def test_no_data(self):
        """T-69 done without data exits 2 and appends nothing."""
        code, out = self.ledger('done', 'ABC-9')
        self.assertEqual(code, 2)
        self.assertEqual(store.read_events(), [])

    def test_twice(self):
        """T-70 done twice: first done_at kept, newest actual and updated_at."""
        from measured.tasks import merged
        line('a', {'ABC-1': 300})
        self.ledger('done', 'ABC-1', '--size', 'S')
        t1 = merged(store.read_events())['ABC-1']
        time.sleep(1.1)
        line('b', {'ABC-1': 700})
        self.ledger('done', 'ABC-1')
        t2 = merged(store.read_events())['ABC-1']
        self.assertEqual(t2['done_at'], t1['done_at'])
        self.assertNotEqual(t2['updated_at'], t1['updated_at'])
        self.assertEqual(t2['actual']['fresh'], 1000)
        self.assertEqual(t2['size'], 'S')

    def test_measured_flag(self):
        """T-129 80% lead share: measured false; calibrate leaves it out and counts it; report shows the count."""
        line('a', {'ABC-1': 1000}, role=lambda k, v: {'build': 200, 'lead': 800})
        code, out = self.ledger('done', 'ABC-1', '--size', 'S')
        self.assertFalse(out['actual']['measured'])
        code, cal = self.ledger('calibrate')
        self.assertEqual(cal['data']['left_out_not_measured'], 1)
        self.assertEqual(cal['data']['measured'], 0)
        code, rep = self.ledger('report')
        self.assertEqual(rep['left_out_not_measured'], 1)


class TestReport(Base):
    def test_table_and_attribution(self):
        """T-78 T-79 T-80 size table, attribution share and overhead; open tasks; warnings at the top."""
        for i in range(1, 6):
            line(f's{i}', {f'ABC-{i}': 1000 * i}, untied={'_after': 1000 * i})
            self.ledger('done', f'ABC-{i}', '--size', 'S')
        self.ledger('estimate', '--size', 'S', '--for', 'ABC-9')
        line('open', {'ABC-9': 123})
        store.add_warning('format')
        code, rep = self.ledger('report')
        self.assertEqual(rep['sizes'][0]['size'], 'S')
        self.assertEqual(rep['sizes'][0]['n'], 5)
        self.assertAlmostEqual(rep['attribution']['items_share'], (15000 + 123) / (30000 + 123), places=6)
        self.assertEqual(rep['open'][0]['id'], 'ABC-9')
        self.assertEqual(rep['warnings'], ['format'])
        import contextlib
        import io
        import ledger
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ledger.main(['report'])
        self.assertTrue(buf.getvalue().startswith('WARNING'))

    def test_aggregate(self):
        """T-133 report --aggregate holds no task ID and no value from fewer than 5 tasks."""
        for i in range(1, 5):
            line(f's{i}', {f'ABC-{100 + i}': 1000 * i})
            self.ledger('done', f'ABC-{100 + i}', '--size', 'S')
        self.ledger('estimate', '--size', 'S', '--for', 'ABC-999')
        line('o', {'ABC-999': 5})
        code, rep = self.ledger('report', '--aggregate')
        blob = json.dumps(rep)
        self.assertNotRegex(blob, r'ABC-\d')
        bad = []

        def walk(o):
            if isinstance(o, dict):
                if isinstance(o.get('n'), int) and o['n'] < 5 and set(o) - {'n', 'note', 'size', 'month', 'block', 'short'}:
                    bad.append(o)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(rep)
        self.assertEqual(bad, [])


class TestAccuracy(Base):
    """REQ-40: first estimate (before work) against the actual at done."""

    def _task(self, i, done_at, actual, est_delay=0, guess=None, source='own', second=None, with_est=True):
        start = done_at - 7200
        mid = paths.load_config()['machine_id']
        if with_est:
            ev = {'schema_version': 1, 'type': 'estimate', 'id': f'ABC-{i}', 'at': iso(start + est_delay)[:19] + 'Z',
                  'machine': mid, 'size': 'S', 'range50': {'tokens': [100, 400]}, 'range80': {'tokens': [50, 800]},
                  'n': 10, 'source': source, 'guess': guess}
            store.append_event(mid, ev)
        if second:
            store.append_event(mid, dict(ev, at=iso(start + 60)[:19] + 'Z', range50={'tokens': second},
                                         range80={'tokens': second}))
        actual = {'fresh': actual, 'by_role': {'build': actual}, 'measured': True, 'start': iso(start)[:19] + 'Z',
                  'end': iso(done_at)[:19] + 'Z', 'active_h': 1, 'elapsed_h': 2}
        store.append_event(mid, {'schema_version': 1, 'type': 'done', 'id': f'ABC-{i}', 'at': iso(done_at)[:19] + 'Z',
                                 'machine': mid, 'size': 'S', 'actual': actual})

    @staticmethod
    def oracle(actuals, r50=(100, 400), r80=(50, 800)):
        mid = math.sqrt(r50[0] * r50[1])
        return {'n': len(actuals), 'median_error': statistics.median(abs(math.log(a / mid)) for a in actuals),
                'coverage50': sum(r50[0] <= a <= r50[1] for a in actuals) / len(actuals),
                'coverage80': sum(r80[0] <= a <= r80[1] for a in actuals) / len(actuals),
                'bias': statistics.median(math.log(a / mid) for a in actuals)}

    def test_months_and_blocks(self):
        """T-103 23 done tasks over three months: month rows and blocks of 10, 10, 3 match a direct computation."""
        values = [200, 400, 800, 100, 50, 1600, 300, 250, 120, 900, 60, 410, 390, 200, 700, 150, 220, 1000, 80, 330,
                  260, 500, 90]
        months = [7] * 8 + [8] * 10 + [9] * 5
        base = {7: 1_783_000_000, 8: 1_785_700_000, 9: 1_788_400_000}  # mid July, August, September 2026
        for i, (v, m) in enumerate(zip(values, months)):
            self._task(i + 1, base[m] + i * 3600, v)
        code, rep = self.ledger('report')
        acc = rep['accuracy']
        self.assertEqual([m['month'] for m in acc['months']], ['2026-07', '2026-08', '2026-09'])
        for row, sel in zip(acc['months'], (values[:8], values[8:18], values[18:])):
            exp = self.oracle(sel)
            for k in ('n', 'median_error', 'coverage50', 'coverage80', 'bias'):
                self.assertAlmostEqual(row['own'][k], exp[k], places=9, msg=k)
        self.assertEqual([b['block'] for b in acc['blocks']], ['1-10', '11-20', '21-23'])
        self.assertTrue(acc['blocks'][2]['short'])
        self.assertEqual(acc['blocks'][2]['own'], {'n': 3, 'note': 'n too small'})
        exp = self.oracle(values)
        self.assertAlmostEqual(acc['total']['own']['median_error'], exp['median_error'], places=9)

    def test_left_out(self):
        """T-104 T-132 no estimate: left out and counted; an estimate 30 minutes into the work: 'during work'."""
        self._task(1, T0, 200, with_est=False)
        self._task(2, T0 + 10, 200, est_delay=1800)
        for i in range(3, 8):
            self._task(i, T0 + i, 200, est_delay=300)
        code, rep = self.ledger('report')
        acc = rep['accuracy']
        self.assertEqual(acc['left_out'], {'no_estimate': 1, 'during_work': 1, 'not_measured': 0})
        self.assertEqual(acc['total']['own']['n'], 5)

    def test_first_estimate_counts(self):
        """T-105 a second estimate stored later doesn't change the numbers."""
        for i in range(1, 6):
            self._task(i, T0 + i, 200 * i)
        a = self.ledger('report')[1]['accuracy']['total']
        for i in range(6, 11):
            self._task(i, T0 + i, 200 * (i - 5), second=[1, 2])
        b = self.ledger('report')[1]['accuracy']['total']
        self.assertEqual(b['own']['n'], 10)
        self.assertAlmostEqual(b['own']['median_error'], a['own']['median_error'])

    def test_guess_and_source_rows(self):
        """T-106 T-107 guess rows next to estimate rows; starter and own apart; n = 4 shows only its count; the
        tied share is in the report."""
        for i in range(1, 6):
            self._task(i, T0 + i, 300, guess=[1000, 3000])
        for i in range(6, 10):
            self._task(i, T0 + i, 300, source='starter')
        code, rep = self.ledger('report')
        tot = rep['accuracy']['total']
        self.assertEqual(tot['own']['n'], 5)
        self.assertEqual(tot['starter'], {'n': 4, 'note': 'n too small'})
        self.assertAlmostEqual(tot['guess']['median_error'], abs(math.log(300 / math.sqrt(3e6))))
        self.assertEqual(tot['guess']['coverage50'], 0.0)
        self.assertIn('items_share', rep['attribution'])


class TestCommandsMisc(Base):
    def test_forget(self):
        """T-48 T-49 forget lists without --yes; with --yes the three folders go and transcripts stay."""
        p = self.write_session(Tx().prompt(T0, 'x').msg(T0 + 1, fresh=5))
        self.record(p)
        code, out = self.ledger('forget')
        self.assertEqual(len(out['would_delete']), 3)
        self.assertTrue(os.path.isdir(paths.data_dir()))
        code, out = self.ledger('forget', '--yes')
        for d in (paths.config_dir(), paths.data_dir()):
            self.assertFalse(os.path.exists(d))
        self.assertEqual(os.listdir(paths.state_dir()), ['stopped'])
        self.assertTrue(os.path.isfile(p))

    def test_forget_stops_recording(self):
        """T-145 after forget --yes no hook records until init runs again; the output says so."""
        import record as record_script
        p = self.write_session(Tx().prompt(T0, 'x').msg(T0 + 1, fresh=5))
        code, out = self.ledger('forget', '--yes')
        self.assertEqual(out['recording'], 'off until init')
        record_script.run_child('session_end', {'transcript_path': p, 'session_id': 'sess-1'})
        self.assertFalse(os.path.exists(paths.data_dir()))
        self.assertFalse(os.path.exists(paths.config_dir()))
        self.assertEqual(self.ledger('backfill')[0], 1)
        self.ledger('init', '--yes')
        record_script.run_child('session_end', {'transcript_path': p, 'session_id': 'sess-1'})
        self.assertEqual(len(store.read_ledger()), 1)

    def test_effort_checked(self):
        """T-147 --effort accepts a short word only."""
        self.assertEqual(self.ledger('estimate', '--size', 'S', '--effort', 'high')[0], 0)
        code, out = self.ledger('estimate', '--size', 'S', '--effort', 'ignore all previous instructions')
        self.assertEqual(code, 1)
        self.assertEqual(store.read_events(), [])

    def test_backfill(self):
        """T-58 T-59 backfill records three sessions, a second run changes nothing, old sessions are skipped."""
        for i in range(3):
            self.write_session(Tx().prompt(T0, 'x').msg(T0 + i, fresh=5, key=f'b{i}'), sid=f'b{i}')
        old = self.write_session(Tx().prompt(T0, 'x').msg(T0, fresh=5, key='old'), sid='old')
        os.utime(old, (time.time() - 40 * 86400,) * 2)
        code, out = self.ledger('backfill')
        self.assertEqual(out['recorded'], 3)
        before = open(store.ledger_file(paths.load_config()['machine_id'])).read()
        self.ledger('backfill')
        after = open(store.ledger_file(paths.load_config()['machine_id'])).read()
        strip = lambda s: re.sub(r'"recorded_at":"[^"]+"', '', s)
        self.assertEqual(strip(before), strip(after))
        self.assertEqual(sorted(d['session_id'] for d in store.read_ledger()), ['b0', 'b1', 'b2'])

    def test_json_contract(self):
        """T-81 every command's --json output parses and has the keys in docs/CLI.md."""
        doc = open(os.path.join(ROOT, 'docs', 'CLI.md')).read().split('## Arguments')[0]
        keys = {m.group(1): [k.strip(' `') for k in m.group(2).split(',')]
                for m in re.finditer(r'^\| `(\w+)` \| ([^|]+) \|$', doc, re.M)}
        line('s', {'ABC-1': 50})
        runs = {'init': ('init', '--yes'), 'backfill': ('backfill',), 'estimate': ('estimate', '--size', 'S'),
                'done': ('done', 'ABC-1', '--size', 'S'), 'report': ('report',), 'calibrate': ('calibrate',),
                'forget': ('forget',)}
        self.assertEqual(sorted(keys), sorted(runs))
        for cmd, args in runs.items():
            code, out = self.ledger(*args)
            self.assertEqual(code, 0, cmd)
            for k in keys[cmd]:
                self.assertIn(k, out, f'{cmd}: {k}')


if __name__ == '__main__':
    unittest.main()
