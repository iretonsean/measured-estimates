"""Sync to the person's own git remote, and several machines (REQ-15, REQ-34)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest

from helpers import SCRIPTS, T0, Env, Tx

from measured import paths, store, sync

HAS_GIT = shutil.which('git') is not None


@unittest.skipUnless(HAS_GIT, 'git needed')
class TestSync(Env):
    def setUp(self):
        super().setUp()
        self.remote = os.path.join(self.tmp, 'remote.git')
        subprocess.run(['git', 'init', '-q', '--bare', self.remote], check=True)
        os.environ['GIT_CONFIG_GLOBAL'] = os.path.join(self.tmp, 'gitconfig')
        with open(os.environ['GIT_CONFIG_GLOBAL'], 'w') as f:
            f.write('[init]\n\tdefaultBranch = main\n')

    def home(self, name):
        """Point the XDG folders at a second scratch home."""
        for var, sub in (('XDG_CONFIG_HOME', 'cfg'), ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state')):
            os.environ[var] = os.path.join(self.tmp, name, sub)

    def test_record_arrives_and_hook_returns_first(self):
        """T-46 a record arrives in a local bare repo; the hook returns before the slow push ends; the sync
        environment turns prompts off."""
        self.ledger('init', '--yes', '--sync-remote', self.remote)
        fake = os.path.join(self.tmp, 'bin')
        os.makedirs(fake)
        envlog = os.path.join(self.tmp, 'env.log')
        real = shutil.which('git')
        with open(os.path.join(fake, 'git'), 'w') as f:
            f.write(f'#!/bin/sh\nenv | grep -E "^(GIT_TERMINAL_PROMPT|GCM_INTERACTIVE|GIT_SSH_COMMAND|SSH_ASKPASS_REQUIRE|'
                    f'GIT_ASKPASS|SSH_ASKPASS)=" >> "{envlog}"\n'
                    f'case "$*" in *" push "*) sleep 2;; esac\nexec "{real}" "$@"\n')
        os.chmod(os.path.join(fake, 'git'), 0o755)
        os.environ['PATH'] = fake + os.pathsep + os.environ['PATH']
        os.environ['GIT_ASKPASS'] = '/bin/false'
        p = self.write_session(Tx().prompt(T0, 'ITEM: ABC-1').msg(T0 + 1, fresh=77))
        t = time.monotonic()
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'record.py'), 'session-end'],
                           input=json.dumps({'transcript_path': p, 'session_id': 'sess-1'}), text=True,
                           capture_output=True, timeout=30)
        self.assertLess(time.monotonic() - t, 1.5)
        self.assertEqual(r.returncode, 0)
        mid = paths.load_config()['machine_id']
        for _ in range(150):
            out = subprocess.run([real, '--git-dir', self.remote, 'show', f'measured-estimates:ledger/{mid}.jsonl'],
                                 capture_output=True, text=True)
            if out.returncode == 0:
                break
            time.sleep(0.1)
        self.assertEqual(out.returncode, 0)
        self.assertIn('"fresh_tokens":77', out.stdout)
        env = open(envlog).read()
        self.assertIn('GIT_TERMINAL_PROMPT=0', env)
        self.assertIn('GCM_INTERACTIVE=never', env)
        self.assertIn('GIT_SSH_COMMAND=ssh -o BatchMode=yes', env)
        self.assertNotIn('GIT_ASKPASS=', env)
        self.assertEqual(store.read_status()['sync']['result'], 'ok')

    def test_refused_failed_and_own_files_only(self):
        """T-126 http:// is refused; a failing push writes 'fail' and report shows it; the commit holds only this
        machine's files."""
        self.ledger('init', '--yes')
        cfg = paths.load_config()
        cfg['sync'] = {'remote': 'http://example.invalid/r.git', 'branch': 'measured-estimates'}
        self.assertEqual(sync.run(cfg, force=True), 'sync-refused')
        cfg['sync']['remote'] = os.path.join(self.tmp, 'missing.git')
        self.record(self.write_session(Tx().prompt(T0, 'x').msg(T0 + 1, fresh=5)), cfg=cfg)
        code = sync.run(cfg, force=True)
        self.assertNotEqual(code, 'ok')
        code_, rep = self.ledger('report')
        self.assertEqual(rep['sync']['result'], 'fail')
        cfg['sync']['remote'] = self.remote
        # A stray file in the store must not be pushed.
        with open(os.path.join(paths.data_dir(), 'stray.txt'), 'w') as f:
            f.write('x')
        self.assertEqual(sync.run(cfg, force=True), 'ok')
        files = subprocess.run(['git', '--git-dir', self.remote, 'ls-tree', '-r', '--name-only', 'measured-estimates'],
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(files, [f"ledger/{cfg['machine_id']}.jsonl"])

    def test_lock_skips(self):
        """T-127 a second sync while the sync lock is held is skipped."""
        self.ledger('init', '--yes', '--sync-remote', self.remote)
        cfg = paths.load_config()
        with store.Lock(paths.sync_dir() + '.lock'):
            self.assertIsNone(sync.run(cfg, force=True))

    def test_two_machines(self):
        """T-94 T-128 two homes sync through one bare repo without a conflict; done sums both; the first estimate
        is machine B's."""
        self.home('b')
        self.ledger('init', '--yes', '--example', 'ABC-1', '--sync-remote', self.remote)
        cfg_b = paths.load_config()
        self.ledger('estimate', '--size', 'S', '--for', 'ABC-1')
        est_b = store.read_events()[0]
        self.record(self.write_session(Tx().prompt(T0, 'ITEM: ABC-1').msg(T0 + 1, fresh=300, key='kb'), sid='sb'),
                    sid='sb', cfg=cfg_b)
        self.assertEqual(sync.run(cfg_b, force=True), 'ok')
        self.home('a')
        self.ledger('init', '--yes', '--example', 'ABC-1', '--sync-remote', self.remote)
        cfg_a = paths.load_config()
        time.sleep(1.1)
        self.ledger('estimate', '--size', 'M', '--for', 'ABC-1')
        self.record(self.write_session(Tx().prompt(T0, 'ITEM: ABC-1').msg(T0 + 1, fresh=700, key='ka'), sid='sa'),
                    sid='sa', cfg=cfg_a)
        self.assertEqual(sync.run(cfg_a, force=True), 'ok')
        code, out = self.ledger('done', 'ABC-1', '--size', 'S')
        self.assertEqual(out['actual']['fresh'], 1000)
        from measured.tasks import merged
        self.assertEqual(merged(store.read_events())['ABC-1']['estimates'][0], est_b)
        self.home('b')
        self.assertEqual(sync.run(cfg_b, force=True), 'ok')
        self.assertEqual(len(store.read_ledger()), 2)


if __name__ == '__main__':
    unittest.main()
