"""Test helpers: a scratch home (XDG folders) and builders for invented Claude Code transcripts.

No real transcript content is used anywhere in the tests.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

T0 = 1_790_000_000  # an invented base time (2026-09)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


class Tx:
    """Builds one transcript file line by line."""

    def __init__(self, cwd='/work/proj'):
        self.lines = []
        self.cwd = cwd
        self.n = 0

    def prompt(self, t, text, meta=False):
        d = {'type': 'user', 'message': {'role': 'user', 'content': text}, 'timestamp': iso(t), 'cwd': self.cwd,
             'uuid': f'u{len(self.lines)}'}
        if meta:
            d['isMeta'] = True
        self.lines.append(json.dumps(d))
        return self

    def msg(self, t, fresh=100, reads=0, model='model-a', effort='high', effort_field='perTurnEffort', key=None,
            tools=(), output=None, cwd=None):
        self.n += 1
        key = key or f'msg_{id(self)}_{self.n}'
        out = output if output is not None else fresh // 2
        usage = {'input_tokens': fresh - out, 'output_tokens': out, 'cache_creation_input_tokens': 0,
                 'cache_read_input_tokens': reads}
        content = [{'type': 'text', 'text': 'reply text that must never be stored'}]
        for i, (name, inp) in enumerate(tools):
            content.append({'type': 'tool_use', 'id': f'tu_{key}_{i}', 'name': name, 'input': inp})
        d = {'type': 'assistant', 'message': {'id': key, 'model': model, 'usage': usage, 'content': content},
             'requestId': f'req_{key}', 'timestamp': iso(t), 'cwd': cwd or self.cwd, 'uuid': f'a{len(self.lines)}'}
        if effort is not None:
            d[effort_field] = effort
        self.lines.append(json.dumps(d))
        return self

    def raw(self, line):
        self.lines.append(line)
        return self

    def write(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.lines) + '\n')
        return path


def bash(cmd):
    return ('Bash', {'command': cmd})


def agent(prompt):
    return ('Agent', {'prompt': prompt, 'description': 'x'})


class Env(unittest.TestCase):
    """A test case with a scratch home: XDG folders and CLAUDE_CONFIG_DIR point into a temp folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='me-test-')
        self.old_env = dict(os.environ)
        os.environ['HOME'] = self.tmp
        os.environ['XDG_CONFIG_HOME'] = os.path.join(self.tmp, 'cfg')
        os.environ['XDG_DATA_HOME'] = os.path.join(self.tmp, 'data')
        os.environ['XDG_STATE_HOME'] = os.path.join(self.tmp, 'state')
        os.environ['CLAUDE_CONFIG_DIR'] = os.path.join(self.tmp, 'claude')
        os.environ.pop('CLAUDE_PLUGIN_ROOT', None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self, **kw):
        from measured import paths
        c = paths.ensure_config()
        c.update(kw)
        paths.save_config(c)
        return paths.load_config()

    def session_path(self, sid='sess-1', project='proj'):
        return os.path.join(self.tmp, 'claude', 'projects', project, f'{sid}.jsonl')

    def write_session(self, main: Tx, subs=(), sid='sess-1', project='proj'):
        p = self.session_path(sid, project)
        main.write(p)
        for i, s in enumerate(subs):
            s.write(os.path.join(p[:-6], 'subagents', f'agent-{i}.jsonl'))
        return p

    def record(self, path, sid='sess-1', cwd='', reason='manual', deadline_s=30.0, cfg=None):
        import time
        from measured.recorder import record
        cfg = cfg or self.cfg()
        return record({'session_id': sid, 'transcript_path': path, 'cwd': cwd}, cfg, reason,
                      time.monotonic() + deadline_s)

    def ledger(self, *args):
        """Runs the CLI in-process with --json; returns (exit code, parsed output)."""
        import contextlib
        import io
        import ledger
        buf = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = ledger.main([*args, '--json'])
        out = buf.getvalue().strip()
        return code, (json.loads(out) if out else None)
