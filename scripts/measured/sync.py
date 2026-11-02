"""Optional sync to the person's own git remote (REQ-15, REQ-34). Runs only in the detached child.

No prompts: terminal and credential prompts are off, SSH runs in batch mode, askpass programs are unset. Only this
machine's two files are added, by path. A failure is a fixed code in status.json; `report` shows it.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time

from . import paths, store

TOTAL_S = 60
STOP_EVERY_S = 15 * 60


def sync_env() -> dict:
    env = dict(os.environ)
    env.update({'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never', 'GIT_SSH_COMMAND': 'ssh -o BatchMode=yes',
                'SSH_ASKPASS_REQUIRE': 'never', 'GIT_PAGER': 'cat', 'GIT_CONFIG_NOSYSTEM': '1'})
    env.pop('GIT_ASKPASS', None)
    env.pop('SSH_ASKPASS', None)
    return env


def classify(stderr: str) -> str:
    s = (stderr or '').lower()
    if any(x in s for x in ('authentication', 'permission denied', 'could not read username', 'terminal prompts disabled',
                            'publickey', '403')):
        return 'sync-auth'
    if any(x in s for x in ('could not resolve', 'unable to access', 'connection', 'network', 'timed out')):
        return 'sync-network'
    if any(x in s for x in ('conflict', 'could not apply', 'rebase')):
        return 'sync-conflict'
    return 'sync-error'


class SyncFail(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def run(cfg: dict, force: bool = False, git: str = 'git') -> str | None:
    """Sync once. Returns the result code, or None when skipped (another sync runs, or the last one is too recent)."""
    remote = (cfg.get('sync') or {}).get('remote')
    if not remote:
        return None
    branch = (cfg.get('sync') or {}).get('branch') or 'measured-estimates'
    if remote.lower().startswith('http://'):
        store.set_sync_result('sync-refused')
        return 'sync-refused'
    st = store.read_status().get('sync') or {}
    if not force and st.get('at'):
        try:
            if time.time() - store.parse_ts(st['at']) < STOP_EVERY_S:
                return None
        except ValueError:
            pass
    clone = paths.sync_dir()
    try:
        lock = store.Lock(clone + '.lock', deadline=None)
        lock.__enter__()
    except store.LockTimeout:
        return None
    try:
        code = _sync(cfg, remote, branch, clone, git, time.monotonic() + TOTAL_S)
    except SyncFail as e:
        code = e.code
    except (OSError, subprocess.SubprocessError):
        code = 'sync-error'
    finally:
        lock.__exit__(None, None, None)
    store.set_sync_result(code)
    return code


def _sync(cfg, remote, branch, clone, git, deadline) -> str:
    env = sync_env()

    def g(*args, check=True):
        left = deadline - time.monotonic()
        if left <= 0:
            raise SyncFail('sync-timeout')
        try:
            r = subprocess.run([git, '-C', clone, *args], capture_output=True, text=True, timeout=left, env=env,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise SyncFail('sync-timeout')
        if check and r.returncode != 0:
            raise SyncFail(classify(r.stderr))
        return r

    mid = cfg['machine_id']
    if not os.path.isdir(os.path.join(clone, '.git')):
        os.makedirs(clone, exist_ok=True)
        g('init', '-q')
        g('remote', 'add', 'origin', remote)
    else:
        g('remote', 'set-url', 'origin', remote)
    has_remote = g('fetch', '-q', 'origin', branch, check=False).returncode == 0
    if has_remote:
        g('checkout', '-q', '-B', branch, f'origin/{branch}')
    else:
        g('checkout', '-q', '--orphan', branch, check=False)
    own = [('ledger', store.ledger_file(mid)), ('tasks', store.tasks_file(mid))]
    rel = []
    for sub, src in own:
        if os.path.isfile(src):
            os.makedirs(os.path.join(clone, sub), exist_ok=True)
            shutil.copyfile(src, os.path.join(clone, sub, f'{mid}.jsonl'))
            rel.append(f'{sub}/{mid}.jsonl')
    if rel:
        g('add', '--', *rel)
        if g('diff', '--cached', '--quiet', check=False).returncode != 0:
            g('-c', 'user.name=measured-estimates', '-c', 'user.email=sync@measured-estimates.invalid',
              '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', f'measured-estimates: machine {mid}')
        for attempt in range(2):
            if has_remote or attempt:
                r = g('pull', '-q', '--rebase', 'origin', branch, check=False)
                if r.returncode != 0 and 'couldn\'t find remote ref' not in (r.stderr or '').lower():
                    g('rebase', '--abort', check=False)
                    if attempt:
                        raise SyncFail(classify(r.stderr))
                    continue
            r = g('push', '-q', 'origin', f'HEAD:{branch}', check=False)
            if r.returncode == 0:
                break
            if attempt:
                raise SyncFail(classify(r.stderr))
    # Copy the other machines' files into the store (never this machine's own files).
    for sub, dst_dir in (('ledger', paths.ledger_dir()), ('tasks', paths.tasks_dir())):
        for p in glob.glob(os.path.join(clone, sub, '*.jsonl')):
            name = os.path.basename(p)
            if name == f'{mid}.jsonl':
                continue
            with open(p, encoding='utf-8') as f:
                store.atomic_write(os.path.join(dst_dir, name), f.read())
    return 'ok'
