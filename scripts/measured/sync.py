"""Optional sync to the person's own git remote (REQ-15, REQ-34). Runs only in the detached child.

No prompts: terminal and credential prompts are off, SSH runs in batch mode, askpass programs are unset. Only this
machine's two files are added, by path. A failure is a fixed code in status.json; `report` shows it.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import time

from . import paths, store

TOTAL_S = 60
STOP_EVERY_S = 15 * 60
MAX_FILE = 50 * 1024 * 1024
BRANCH_OK = re.compile(r'[A-Za-z0-9._/][A-Za-z0-9._/-]{0,99}')
NAME_OK = re.compile(r'[0-9a-f]{16}\.jsonl')


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
    if remote.lower().startswith('http://') or remote.startswith('-') or not BRANCH_OK.fullmatch(branch) \
            or '..' in branch:
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
        paths.private_dir(clone)
        g('init', '-q')
        g('remote', 'add', '--', 'origin', remote)
    else:
        g('remote', 'set-url', '--', 'origin', remote)
    # Links from the remote are checked out as plain files, never as links (a remote must not reach outside the store).
    g('config', 'core.symlinks', 'false')
    has_remote = g('fetch', '-q', 'origin', branch, check=False).returncode == 0
    if has_remote:
        g('checkout', '-q', '-B', branch, f'origin/{branch}')
    else:
        g('checkout', '-q', '--orphan', branch, check=False)
    own = [('ledger', store.ledger_file(mid)), ('tasks', store.tasks_file(mid))]
    rel = []
    for sub, src in own:
        folder = os.path.join(clone, sub)
        if os.path.islink(folder) or (os.path.lexists(folder) and not os.path.isdir(folder)):
            raise SyncFail('sync-refused')  # the remote replaced the folder with a link or a file
        if os.path.isfile(src):
            os.makedirs(os.path.join(clone, sub), mode=0o700, exist_ok=True)
            dst = os.path.join(clone, sub, f'{mid}.jsonl')
            tmp = dst + '.tmp'
            if os.path.lexists(tmp):
                os.unlink(tmp)
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)  # replaces a link at dst; never writes through it
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
    # Copy the other machines' files into the store (never this machine's own files, never through a link). Their
    # content is checked line by line when it's read (store.valid_line, store.valid_event).
    for sub, dst_dir in (('ledger', paths.ledger_dir()), ('tasks', paths.tasks_dir())):
        folder = os.path.join(clone, sub)
        if os.path.islink(folder) or not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            p = os.path.join(folder, name)
            if name == f'{mid}.jsonl' or not NAME_OK.fullmatch(name):
                continue
            text = _read_regular(p)
            if text is not None:
                store.atomic_write(os.path.join(dst_dir, name), text)
    return 'ok'


def _read_regular(p: str):
    """The text of a regular file of at most 50 MB, opened without following a link; None otherwise."""
    try:
        fd = os.open(p, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE:
            return None
        with os.fdopen(fd, 'r', encoding='utf-8', errors='replace') as f:
            fd = None
            return f.read()
    finally:
        if fd is not None:
            os.close(fd)
