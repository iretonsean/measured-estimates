"""The hook wrapper hooks/run.sh (REQ-02)."""
from __future__ import annotations

import json
import os
import subprocess
import unittest

from helpers import ROOT, Env

WRAPPER = os.path.join(ROOT, 'hooks', 'run.sh')


class TestWrapper(Env):
    def fake_bin(self, name, body):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, 'python3')
        with open(p, 'w') as f:
            f.write('#!/bin/sh\n' + body + '\n')
        os.chmod(p, 0o755)
        return d, p

    def tools_dir(self):
        """A folder with only the shell tools the wrapper needs (no python3 in it)."""
        import shutil
        d = os.path.join(self.tmp, 'tools')
        if not os.path.isdir(d):
            os.makedirs(d)
            for name in ('dirname', 'cat', 'touch', 'uname'):
                os.symlink(shutil.which(name), os.path.join(d, name))
        return d

    def run_wrapper(self, path_dirs, **env):
        e = dict(os.environ, PATH=os.pathsep.join([*path_dirs, self.tools_dir()]), **env)
        return subprocess.run(['/bin/sh', WRAPPER, 'stop'], input=json.dumps({'session_id': 'x'}), env=e,
                              capture_output=True, text=True, timeout=30)

    def test_no_python(self):
        """T-06 no python3 found: exit 0, no output."""
        empty = os.path.join(self.tmp, 'empty')
        os.makedirs(empty)
        r = self.run_wrapper([empty], ME_FALLBACK_DIRS='')
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        good_marker = os.path.join(self.tmp, 'ran')
        good_dir, _ = self.fake_bin('good', f'touch "{good_marker}"')
        self.run_wrapper([empty, good_dir], ME_FALLBACK_DIRS='')
        self.assertTrue(os.path.exists(good_marker))  # the search itself works

    def test_relative_and_old_python_skipped(self):
        """T-148 a python3 in a relative PATH folder never runs; a python3 below 3.9 is passed over for a newer one."""
        rel_marker = os.path.join(self.tmp, 'rel-ran')
        rel_dir, _ = self.fake_bin('rel', f'touch "{rel_marker}"')
        old_marker = os.path.join(self.tmp, 'old-ran')
        old_dir, _ = self.fake_bin('old', f'case "$1" in -c) exit 1;; esac\ntouch "{old_marker}"')
        new_marker = os.path.join(self.tmp, 'new-ran')
        new_dir, _ = self.fake_bin('new', f'touch "{new_marker}"')
        e = dict(os.environ, PATH=os.pathsep.join(['rel', old_dir, new_dir, self.tools_dir()]), ME_FALLBACK_DIRS='')
        subprocess.run(['/bin/sh', WRAPPER, 'stop'], input='{}', env=e, cwd=self.tmp, capture_output=True, text=True,
                       timeout=30)
        self.assertFalse(os.path.exists(rel_marker))
        self.assertFalse(os.path.exists(old_marker))
        self.assertTrue(os.path.exists(new_marker))

    def test_macos_stub_skipped(self):
        """T-115 on Darwin without developer tools the system stub is never run; another python3 is used."""
        marker = os.path.join(self.tmp, 'stub-ran')
        stub_dir, stub = self.fake_bin('stub', f'touch "{marker}"')
        good_marker = os.path.join(self.tmp, 'good-ran')
        good_dir, _ = self.fake_bin('good', f'touch "{good_marker}"')
        no_xcode = os.path.join(self.tmp, 'xcs')
        with open(no_xcode, 'w') as f:
            f.write('#!/bin/sh\nexit 2\n')
        os.chmod(no_xcode, 0o755)
        env = {'ME_SYSTEM_PYTHON': stub, 'ME_UNAME': 'Darwin', 'ME_XCODE_SELECT': no_xcode, 'ME_FALLBACK_DIRS': ''}
        r = self.run_wrapper([stub_dir], **env)
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertFalse(os.path.exists(marker))
        r = self.run_wrapper([stub_dir, good_dir], **env)
        self.assertFalse(os.path.exists(marker))
        self.assertTrue(os.path.exists(good_marker))
        # With developer tools present, the system python3 is fine.
        yes_xcode = os.path.join(self.tmp, 'xcs-ok')
        with open(yes_xcode, 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(yes_xcode, 0o755)
        self.run_wrapper([stub_dir], **dict(env, ME_XCODE_SELECT=yes_xcode))
        self.assertTrue(os.path.exists(marker))


if __name__ == '__main__':
    unittest.main()
