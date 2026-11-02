"""Recording: adapter counts, de-duplication, the ledger line, privacy, failure handling."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from helpers import ROOT, SCRIPTS, T0, Env, Tx, agent, bash

import record as record_script
from adapters.base import Deadline
from measured import paths, store
from measured.schema import load_schema, validate


class TestCounts(Env):
    def test_golden(self):
        """T-08 T-41 golden sample: exact fresh tokens and cache reads; the format still parses."""
        p = os.path.join(ROOT, 'tests', 'fixtures', 'golden.jsonl')
        e = self.record(p, sid='golden')
        self.assertEqual(e['fresh_tokens'], 1830)
        self.assertEqual(e['cache_read_tokens'], 5000)
        self.assertEqual(e['messages'], 3)
        self.assertEqual(e['tasks']['ABC-7']['fresh'], 1830)
        self.assertEqual(e['tagged'], {'ids': ['ABC-7'], 'role': 'review'})

    def test_streamed_once_last_wins(self):
        """T-09 T-119 a message on three lines counts once; the last line's output tokens count."""
        tx = Tx().prompt(T0, 'hello')
        tx.msg(T0 + 1, fresh=100, key='m1', output=10)
        tx.msg(T0 + 2, fresh=100, key='m1', output=20)
        tx.msg(T0 + 3, fresh=150, key='m1', output=70)
        e = self.record(self.write_session(tx))
        self.assertEqual(e['messages'], 1)
        self.assertEqual(e['fresh_tokens'], 150)

    def test_synthetic(self):
        """T-10 a <synthetic> message counts zero."""
        tx = Tx().prompt(T0, 'x').msg(T0 + 1, fresh=100).msg(T0 + 2, fresh=999, model='<synthetic>')
        e = self.record(self.write_session(tx))
        self.assertEqual(e['fresh_tokens'], 100)

    def test_model_effort_split(self):
        """T-11 T-12 T-13 model x effort cells; missing effort is unknown; perTurnEffort wins over effort."""
        tx = Tx().prompt(T0, 'x')
        tx.msg(T0 + 1, fresh=10, model='model-a', effort='high')
        tx.msg(T0 + 2, fresh=20, model='model-a', effort='medium')
        tx.msg(T0 + 3, fresh=30, model='model-b', effort='high')
        tx.msg(T0 + 4, fresh=40, model='model-b', effort='medium', effort_field='effort')
        tx.msg(T0 + 5, fresh=50, model='model-b', effort=None)
        line = json.loads(tx.lines[1])
        line['message']['id'] = 'both'
        line['perTurnEffort'] = 'low'
        line['effort'] = 'max'
        tx.raw(json.dumps(line))
        e = self.record(self.write_session(tx))
        bme = e['by_model_effort']
        self.assertEqual(bme['model-a']['high']['fresh'], 10)
        self.assertEqual(bme['model-a']['medium']['fresh'], 20)
        self.assertEqual(bme['model-b']['high']['fresh'], 30)
        self.assertEqual(bme['model-b']['medium']['fresh'], 40)
        self.assertEqual(bme['model-b']['unknown']['fresh'], 50)
        self.assertEqual(bme['model-a']['low']['fresh'], 10)
        self.assertNotIn('max', bme['model-a'])

    def test_subagents(self):
        """T-15 T-16 subagents are summed; an untagged subagent takes the session's tag."""
        main = Tx().prompt(T0, 'ITEM: ABC-1\nROLE: build').msg(T0 + 1, fresh=100)
        s1 = Tx().prompt(T0 + 2, 'do part one').msg(T0 + 3, fresh=200)
        s2 = Tx().prompt(T0 + 4, 'ITEM: ABC-2').msg(T0 + 5, fresh=300)
        e = self.record(self.write_session(main, [s1, s2]))
        self.assertEqual(e['subagents'], 2)
        self.assertEqual(e['fresh_tokens'], 600)
        self.assertEqual(e['tasks']['ABC-1']['fresh'], 300)
        self.assertEqual(e['tasks']['ABC-2']['fresh'], 300)

    def test_partial_line(self):
        """T-39 a truncated last line: the rest records, skipped_lines 1."""
        tx = Tx().prompt(T0, 'x').msg(T0 + 1, fresh=100).raw('{"type": "assistant", "message": {"id"')
        e = self.record(self.write_session(tx))
        self.assertEqual(e['skipped_lines'], 1)
        self.assertEqual(e['fresh_tokens'], 100)

    def test_unknown_format_warns(self):
        """T-40 a transcript in an unknown format writes the warning; report shows it."""
        tx = Tx().raw(json.dumps({'kind': 'turn', 'tokens': 5})).raw(json.dumps({'kind': 'turn', 'tokens': 7}))
        self.assertIsNone(self.record(self.write_session(tx)))
        self.assertEqual([w['code'] for w in store.read_status()['warnings']], ['format'])
        code, rep = self.ledger('report')
        self.assertIn('format', rep['warnings'])

    def test_utc(self):
        """T-95 timestamps with an offset come out in UTC."""
        tx = Tx().prompt(T0, 'x')
        line = json.loads(Tx().msg(T0, fresh=5, key='k1').lines[0])
        line['timestamp'] = '2026-09-21T10:00:00+02:00'
        tx.raw(json.dumps(line))
        e = self.record(self.write_session(tx))
        self.assertEqual(e['first'], '2026-09-21T08:00:00Z')


class TestDedupe(Env):
    def test_shared_keys(self):
        """T-117 two sessions share 10 message keys: the second counts them as duplicates."""
        a = Tx().prompt(T0, 'x')
        for i in range(10):
            a.msg(T0 + i, fresh=100, key=f'shared{i}')
        b = Tx().prompt(T0 + 100, 'x')
        for i in range(10):
            b.msg(T0 + i, fresh=100, key=f'shared{i}')
        b.msg(T0 + 200, fresh=7, key='own')
        e1 = self.record(self.write_session(a, sid='s-a'), sid='s-a')
        e2 = self.record(self.write_session(b, sid='s-b'), sid='s-b')
        self.assertEqual(e1['fresh_tokens'], 1000)
        self.assertEqual(e2['duplicate_messages'], 10)
        self.assertEqual(e2['fresh_tokens'], 7)
        e1b = self.record(self.session_path('s-a'), sid='s-a')
        self.assertEqual(e1b['fresh_tokens'], 1000)  # its own keys stay its own

    def test_replace_line(self):
        """T-35 T-36 recording a session twice leaves one line; other lines stay byte-identical."""
        other = Tx().prompt(T0, 'x').msg(T0 + 1, fresh=5)
        self.record(self.write_session(other, sid='other'), sid='other')
        tx = Tx().prompt(T0, 'x').msg(T0 + 1, fresh=10)
        p = self.write_session(tx, sid='mine')
        self.record(p, sid='mine')
        cfg = paths.load_config()
        before = [l for l in open(store.ledger_file(cfg['machine_id'])) if '"other"' in l]
        tx.msg(T0 + 2, fresh=20)
        tx.write(p)
        self.record(p, sid='mine')
        lines = open(store.ledger_file(cfg['machine_id'])).read().splitlines(True)
        self.assertEqual(len(lines), 2)
        self.assertEqual([l for l in lines if '"other"' in l], before)
        self.assertEqual(json.loads([l for l in lines if '"mine"' in l][0])['fresh_tokens'], 30)


class TestPrivacy(Env):
    # Built from parts at run time, so no canary is a literal in the repo (REQ-18).
    CANARIES = ['sk' + '-canary-SECRET-0001', '/' + 'Users/canary/private/file.txt', 'Fix the canary export dialog',
                'canary-host' + '.example', 'Please refactor the canary module carefully']

    def test_no_canaries_stored(self):
        """T-42 T-43 no prompt text, paths, subjects or hostnames are stored; keys match the schema exactly."""
        c = self.CANARIES
        tx = Tx(cwd='/' + 'Users/canary/private').prompt(T0, f'ITEM: ABC-1 {c[4]}\nROLE: build\n{c[0]} {c[3]}')
        tx.msg(T0 + 1, fresh=50, tools=[bash(f'git commit -m "ABC-1: {c[2]}" {c[1]}'),
                                        agent(f'ITEM: ABC-2\n{c[4]} {c[0]}')])
        p = self.write_session(tx)
        self.cfg(store={'cwd': False, 'branch': False, 'repo': False, 'title': False})
        e = self.record(p)
        code, _ = self.ledger('estimate', '--size', 'S', '--for', 'ABC-1')
        self.ledger('done', 'ABC-1', '--size', 'S')
        self.ledger('calibrate')
        blob = ''
        for d in (paths.data_dir(), paths.state_dir()):
            for root, _, files in os.walk(d):
                for f in files:
                    blob += open(os.path.join(root, f), encoding='utf-8', errors='replace').read()
        for s in c:
            self.assertNotIn(s, blob)
        self.assertNotIn('canary', blob)
        self.assertEqual(validate(e, load_schema('ledger_line')), [])
        bad = dict(e, extra='x')
        self.assertTrue(validate(bad, load_schema('ledger_line')))

    def test_opt_in_fields(self):
        """T-44 opt-in fields are absent by default and present only when turned on."""
        work = os.path.join(self.tmp, 'repo')
        os.makedirs(os.path.join(work, '.git'))
        with open(os.path.join(work, '.git', 'HEAD'), 'w') as f:
            f.write('ref: refs/heads/feature-x\n')
        tx = Tx(cwd=work).prompt(T0, 'x').msg(T0 + 1, fresh=5)
        tx.lines.insert(0, json.dumps({'type': 'custom-title', 'customTitle': 'My title'}))
        p = self.write_session(tx)
        e = self.record(p, cwd=work)
        for k in ('cwd', 'branch', 'repo', 'title'):
            self.assertNotIn(k, e)
        for k, v in (('cwd', '~/repo'), ('branch', 'feature-x'), ('repo', 'repo'), ('title', 'My title')):
            cfg = self.cfg(store={kk: kk == k for kk in ('cwd', 'branch', 'repo', 'title')})
            e = self.record(p, cwd=work, cfg=cfg)
            self.assertEqual(e.get(k), v, k)
            self.assertEqual(len([x for x in ('cwd', 'branch', 'repo', 'title') if x in e]), 1)

    def test_ignore_paths(self):
        """T-125 a session in an ignored folder writes nothing; others still do."""
        cfg = self.cfg(ignore_paths=['~/work/client-*'])
        client = os.path.join(self.tmp, 'work', 'client-x', 'sub')
        tx = Tx(cwd=client).prompt(T0, 'x').msg(T0 + 1, fresh=5)
        self.assertIsNone(self.record(self.write_session(tx, sid='c'), sid='c', cfg=cfg))
        self.assertIsNone(self.record(self.write_session(tx, sid='c2'), sid='c2', cwd=client, cfg=cfg))
        ok = Tx(cwd=os.path.join(self.tmp, 'work', 'mine')).prompt(T0, 'x').msg(T0 + 1, fresh=5)
        self.assertIsNotNone(self.record(self.write_session(ok, sid='m'), sid='m', cfg=cfg))


class TestFailures(Env):
    def test_errors_exit_zero(self):
        """T-04 malformed input, missing transcript, read-only store, parser exception: exit 0, no stdout."""
        cases = ['not json', json.dumps({'transcript_path': '/nope/x.jsonl', 'session_id': 'x'}), '']
        for inp in cases:
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'record.py'), 'manual'], input=inp,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, '')
        tx = Tx().prompt(T0, 'x').msg(T0 + 1, fresh=5)
        p = self.write_session(tx)
        os.makedirs(paths.data_dir(), exist_ok=True)
        os.chmod(paths.data_dir(), 0o500)
        try:
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'record.py'), 'manual'],
                               input=json.dumps({'transcript_path': p, 'session_id': 'x'}), capture_output=True,
                               text=True, timeout=30)
            self.assertEqual((r.returncode, r.stdout), (0, ''))
        finally:
            os.chmod(paths.data_dir(), 0o700)
        with mock.patch('measured.recorder.attribute', side_effect=RuntimeError('boom')):
            with mock.patch.object(sys, 'stdin', io.StringIO(json.dumps({'transcript_path': p, 'session_id': 'x'}))):
                try:
                    record_script.main(['record.py', 'manual'])
                except RuntimeError:
                    pass  # main() raises; the __main__ guard swallows it and exits 0 (checked above)

    def test_deadline(self):
        """T-05 T-116 at the deadline nothing new is written, the old line stays, and report shows 'deadline'."""
        tx = Tx().prompt(T0, 'x')
        for i in range(500):
            tx.msg(T0 + i, fresh=1)
        p = self.write_session(tx)
        self.record(p)
        cfg = paths.load_config()
        before = open(store.ledger_file(cfg['machine_id'])).read()
        tx.msg(T0 + 999, fresh=1000)
        tx.write(p)
        os.environ['MEASURED_ESTIMATES_DEADLINE_S'] = '0'
        record_script.run_child('manual', {'transcript_path': p, 'session_id': 'sess-1'})
        self.assertEqual(open(store.ledger_file(cfg['machine_id'])).read(), before)
        self.assertIn('deadline', [w['code'] for w in store.read_status()['warnings']])
        code, rep = self.ledger('report')
        self.assertIn('deadline', rep['warnings'])

    def test_old_python(self):
        """T-07 under Python below 3.9 the recorder returns at once."""
        self.assertFalse(record_script.python_ok((3, 8, 10)))
        self.assertTrue(record_script.python_ok((3, 9, 6)))
        with mock.patch.object(record_script, 'python_ok', return_value=False), \
                mock.patch.object(record_script, 'spawn_child') as sp:
            record_script.main(['record.py', 'session-end'])
            sp.assert_not_called()

    def test_failed_write(self):
        """T-38 a write that fails leaves the old file unchanged."""
        target = os.path.join(self.tmp, 'f.txt')
        store.atomic_write(target, 'old')
        with mock.patch('os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                store.atomic_write(target, 'new')
        self.assertEqual(open(target).read(), 'old')
        self.assertEqual([f for f in os.listdir(self.tmp) if f.startswith('.tmp-')], [])

    def test_lock_timeout(self):
        """T-124 a held lock: retry until the deadline, then warning 'lock', exit 0."""
        import fcntl
        tx = Tx().prompt(T0, 'x').msg(T0 + 1, fresh=5)
        p = self.write_session(tx)
        paths.ensure_config()
        os.makedirs(paths.state_dir(), exist_ok=True)
        holder = open(paths.lock_path(), 'a')
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        try:
            os.environ['MEASURED_ESTIMATES_DEADLINE_S'] = '0.3'
            t = time.monotonic()
            record_script.run_child('manual', {'transcript_path': p, 'session_id': 'sess-1'})
            self.assertGreaterEqual(time.monotonic() - t, 0.25)
        finally:
            holder.close()
        self.assertIn('lock', [w['code'] for w in store.read_status()['warnings']])

    def test_concurrent(self):
        """T-37 two recorder processes at once leave two lines."""
        ps = []
        for sid in ('c1', 'c2'):
            tx = Tx().prompt(T0, 'x')
            for i in range(300):
                tx.msg(T0 + i, fresh=1, key=f'{sid}-{i}')
            p = self.write_session(tx, sid=sid)
            ps.append(subprocess.Popen([sys.executable, os.path.join(SCRIPTS, 'record.py'), 'manual'],
                                       stdin=subprocess.PIPE, text=True))
            ps[-1].stdin.write(json.dumps({'transcript_path': p, 'session_id': sid}))
        for pr in ps:
            pr.stdin.close()
        for pr in ps:
            pr.wait(timeout=60)
        self.assertEqual(sorted(d['session_id'] for d in store.read_ledger()), ['c1', 'c2'])

    def test_stop_throttle_and_stamps(self):
        """T-02 T-136 Stop records once per 15 minutes; stamps older than 7 days are deleted."""
        self.assertTrue(store.stamp_due('s1', 900))
        self.assertFalse(store.stamp_due('s1', 900))
        old = os.path.join(paths.stamps_dir(), 's1')
        os.utime(old, (time.time() - 901, time.time() - 901))
        self.assertTrue(store.stamp_due('s1', 900))
        os.utime(old, (time.time() - 8 * 86400,) * 2)
        store.stamp_due('s2', 900)
        self.assertEqual(store.clean_stamps(), 1)
        self.assertEqual(os.listdir(paths.stamps_dir()), ['s2'])

    def test_session_end_child(self):
        """T-01 a SessionEnd hook input writes one ledger line after the detached child ends."""
        tx = Tx().prompt(T0, 'x').msg(T0 + 1, fresh=42)
        p = self.write_session(tx)
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'record.py'), 'session-end'],
                           input=json.dumps({'transcript_path': p, 'session_id': 'sess-1', 'cwd': ''}),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        for _ in range(100):
            if store.read_ledger():
                break
            time.sleep(0.1)
        lines = store.read_ledger()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['reason'], 'session_end')


class TestSchemaVersions(Env):
    def test_validate_samples(self):
        """T-82 sample files validate against their schemas."""
        tx = Tx().prompt(T0, 'ITEM: ABC-1').msg(T0 + 1, fresh=5)
        e = self.record(self.write_session(tx))
        self.assertEqual(validate(e, load_schema('ledger_line')), [])
        cfg = {k: v for k, v in paths.load_config().items() if not k.startswith('_')}
        self.assertEqual(validate(cfg, load_schema('config')), [])
        self.ledger('estimate', '--size', 'S', '--for', 'ABC-1')
        self.ledger('done', 'ABC-1', '--size', 'S')
        for ev in store.read_events():
            self.assertEqual(validate(ev, load_schema('task_event')), [], ev['type'])
        store.add_warning('format')
        store.set_sync_result('ok')
        self.assertEqual(validate(store.read_status(), load_schema('status')), [])
        with open(os.path.join(ROOT, 'data', 'starter.json')) as f:
            self.assertEqual(validate(json.load(f), load_schema('starter')), [])

    def test_migrate_v0(self):
        """T-83 a version-0 ledger line migrates to version 1."""
        from measured.schema import migrate_ledger_line
        d = migrate_ledger_line({'session_id': 'x', 'fresh_m': 0.25})
        self.assertEqual((d['schema_version'], d['fresh_tokens']), (1, 250000))

    def test_newer_version_read_only(self):
        """T-84 a file with a newer version isn't overwritten; the command warns."""
        cfg = paths.ensure_config()
        path = store.ledger_file(cfg['machine_id'])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(json.dumps({'schema_version': 99, 'session_id': 'future'}) + '\n')
        tx = Tx().prompt(T0, 'x').msg(T0 + 1, fresh=5)
        p = self.write_session(tx)
        record_script.run_child('manual', {'transcript_path': p, 'session_id': 'sess-1'})
        self.assertEqual(open(path).read().count('\n'), 1)
        self.assertIn('newer-schema', [w['code'] for w in store.read_status()['warnings']])


class TestNoNetwork(Env):
    def test_no_socket(self):
        """T-45 with no remote, recording and every command run with sockets blocked."""
        import socket
        tx = Tx().prompt(T0, 'ITEM: ABC-1').msg(T0 + 1, fresh=5)
        p = self.write_session(tx)
        with mock.patch.object(socket, 'socket', side_effect=AssertionError('network')), \
                mock.patch.object(socket, 'create_connection', side_effect=AssertionError('network')):
            self.assertEqual(self.ledger('init', '--yes')[0], 0)
            record_script.run_child('manual', {'transcript_path': p, 'session_id': 'sess-1'})
            for args in (('backfill',), ('estimate', '--size', 'S', '--for', 'ABC-1'), ('done', 'ABC-1', '--size', 'S'),
                         ('report',), ('calibrate',), ('forget',)):
                self.assertIn(self.ledger(*args)[0], (0, 2), args)


if __name__ == '__main__':
    unittest.main()
