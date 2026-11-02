"""Files: safe writes, the lock, ledger lines, task events, the message-key index, status (REQ-10, REQ-11, REQ-29)."""
from __future__ import annotations

import errno
import fcntl
import glob
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone

from . import SCHEMA_VERSION, paths


class LockTimeout(Exception):
    pass


class NewerSchema(Exception):
    """A file written by a newer version: read only (REQ-29)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def parse_ts(at: str) -> float:
    return datetime.fromisoformat(at.replace('Z', '+00:00')).timestamp()


def atomic_write(path: str, text: str) -> None:
    """Write to a temporary file in the same folder, then rename: a failed write leaves the old file (REQ-11)."""
    d = os.path.dirname(path) or '.'
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=d)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Lock:
    """An exclusive flock with non-blocking retries until a deadline (time.monotonic). The kernel releases it when the
    process dies, so a crashed recorder never holds it (REQ-11)."""

    def __init__(self, path: str, deadline: float | None = None, retry_s: float = 0.05):
        self.path, self.deadline, self.retry_s, self.f = path, deadline, retry_s, None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.f = open(self.path, 'a')
        while True:
            try:
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    raise
                if self.deadline is None or time.monotonic() >= self.deadline:
                    self.f.close()
                    raise LockTimeout(self.path)
                time.sleep(self.retry_s)

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()


def read_jsonl(path: str) -> list:
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


# ---- ledger lines ---------------------------------------------------------------------------------------------------

def ledger_file(machine_id: str) -> str:
    return os.path.join(paths.ledger_dir(), f'{machine_id}.jsonl')


def read_ledger() -> list:
    """Every session line of every machine in the store, migrated to the current version."""
    from .schema import migrate_ledger_line
    out = []
    for p in sorted(glob.glob(os.path.join(paths.ledger_dir(), '*.jsonl'))):
        for d in read_jsonl(p):
            m = migrate_ledger_line(d)
            if m is not None:
                out.append(m)
    return out


def replace_session_line(machine_id: str, entry: dict) -> None:
    """Replace the line of entry's session in this machine's file, or add it (REQ-10). Other lines stay byte-identical.
    Refuses (NewerSchema) when the file holds a line from a newer version."""
    path = ledger_file(machine_id)
    kept = []
    try:
        with open(path, encoding='utf-8') as f:
            for raw in f:
                if not raw.strip():
                    continue
                try:
                    d = json.loads(raw)
                except ValueError:
                    kept.append(raw if raw.endswith('\n') else raw + '\n')
                    continue
                if isinstance(d, dict) and int(d.get('schema_version') or 0) > SCHEMA_VERSION:
                    raise NewerSchema(path)
                if isinstance(d, dict) and d.get('session_id') == entry['session_id']:
                    continue
                kept.append(raw if raw.endswith('\n') else raw + '\n')
    except FileNotFoundError:
        pass
    kept.append(json.dumps(entry, separators=(',', ':'), sort_keys=True) + '\n')
    atomic_write(path, ''.join(kept))


def session_line(machine_id: str, session_id: str) -> dict | None:
    for d in read_jsonl(ledger_file(machine_id)):
        if d.get('session_id') == session_id:
            return d
    return None


# ---- task events ----------------------------------------------------------------------------------------------------

def tasks_file(machine_id: str) -> str:
    return os.path.join(paths.tasks_dir(), f'{machine_id}.jsonl')


def append_event(machine_id: str, event: dict, deadline: float | None = None) -> None:
    """Append one task event (append-only, REQ-24) under the lock, with a safe rewrite."""
    path = tasks_file(machine_id)
    with Lock(paths.lock_path(), deadline if deadline is not None else time.monotonic() + 10):
        for d in read_jsonl(path):
            if int(d.get('schema_version') or 0) > SCHEMA_VERSION:
                raise NewerSchema(path)
        try:
            with open(path, encoding='utf-8') as f:
                old = f.read()
        except FileNotFoundError:
            old = ''
        if old and not old.endswith('\n'):
            old += '\n'
        atomic_write(path, old + json.dumps(event, separators=(',', ':'), sort_keys=True) + '\n')


def read_events() -> list:
    out = []
    for p in sorted(glob.glob(os.path.join(paths.tasks_dir(), '*.jsonl'))):
        out.extend(d for d in read_jsonl(p) if d.get('type') in ('estimate', 'done') and d.get('id'))
    return out


# ---- message-key index (REQ-03) -------------------------------------------------------------------------------------

def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode('utf-8', 'replace')).hexdigest()[:16]


def load_seen() -> dict:
    out = {}
    try:
        with open(paths.seen_path(), encoding='utf-8') as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2:
                    out.setdefault(parts[0], parts[1])
    except OSError:
        pass
    return out


def save_seen(seen: dict) -> None:
    atomic_write(paths.seen_path(), ''.join(f'{h} {s}\n' for h, s in seen.items()))


# ---- status (warnings, sync result) ---------------------------------------------------------------------------------

WARNING_CODES = ('format', 'deadline', 'lock', 'newer-schema')
SYNC_CODES = ('ok', 'sync-auth', 'sync-network', 'sync-conflict', 'sync-timeout', 'sync-refused', 'sync-error')


def read_status() -> dict:
    try:
        with open(paths.status_path(), encoding='utf-8') as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault('warnings', [])
            return d
    except (OSError, ValueError):
        pass
    return {'schema_version': SCHEMA_VERSION, 'warnings': [], 'sync': None}


def add_warning(code: str) -> None:
    assert code in WARNING_CODES
    st = read_status()
    st['warnings'] = (st.get('warnings') or [])[-19:] + [{'at': now_iso(), 'code': code}]
    st['schema_version'] = SCHEMA_VERSION
    atomic_write(paths.status_path(), json.dumps(st, indent=1, sort_keys=True) + '\n')


def set_sync_result(code: str) -> None:
    assert code in SYNC_CODES
    st = read_status()
    st['sync'] = {'at': now_iso(), 'result': 'ok' if code == 'ok' else 'fail', 'code': code}
    st['schema_version'] = SCHEMA_VERSION
    atomic_write(paths.status_path(), json.dumps(st, indent=1, sort_keys=True) + '\n')


def recent_warnings(days: int = 14) -> list:
    cutoff = time.time() - days * 86400
    out = []
    for w in read_status().get('warnings') or []:
        try:
            if parse_ts(w['at']) >= cutoff and w.get('code') in WARNING_CODES:
                out.append(w)
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    return out


# ---- stamps (Stop throttle) -----------------------------------------------------------------------------------------

def stamp_due(session_id: str, every_s: float) -> bool:
    """True when the session wasn't recorded by Stop in the last `every_s` seconds; touches the stamp."""
    safe = ''.join(c for c in (session_id or 'none') if c.isalnum() or c in '-_')[:80] or 'none'
    p = os.path.join(paths.stamps_dir(), safe)
    try:
        if time.time() - os.path.getmtime(p) < every_s:
            return False
    except OSError:
        pass
    os.makedirs(paths.stamps_dir(), exist_ok=True)
    with open(p, 'w'):
        pass
    return True


def clean_stamps(max_age_days: float = 7) -> int:
    n = 0
    cutoff = time.time() - max_age_days * 86400
    for p in glob.glob(os.path.join(paths.stamps_dir(), '*')):
        try:
            if os.path.getmtime(p) < cutoff:
                os.unlink(p)
                n += 1
        except OSError:
            continue
    return n
