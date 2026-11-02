"""Files: safe writes, the lock, ledger lines, task events, the message-key index, status (REQ-10, REQ-11, REQ-29)."""
from __future__ import annotations

import errno
import fcntl
import glob
import hashlib
import json
import math
import os
import re
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
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=d)  # mkstemp makes the file 0600
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
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        self.f = os.fdopen(os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), 'a')
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


def schema_version(d: dict):
    """The schema version of a record as an int, or None when it isn't one (a foreign or broken line)."""
    v = d.get('schema_version') or 0
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def read_jsonl(path: str) -> list:
    out = []
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


# ---- ledger lines ---------------------------------------------------------------------------------------------------

def ledger_file(machine_id: str) -> str:
    return os.path.join(paths.ledger_dir(), f'{machine_id}.jsonl')


KEY_OK = re.compile(r'[A-Za-z0-9#._:-]{1,64}')
TS_OK = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')
MACHINE_OK = re.compile(r'[0-9a-f]{16}')


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def _ts_or_none(v) -> bool:
    return v is None or (isinstance(v, str) and bool(TS_OK.fullmatch(v)))


def valid_line(d: dict) -> bool:
    """A ledger line is used only when every field the commands read has the right type (lines can come from a sync
    remote, so nothing in them is trusted; REQ-15)."""
    if not isinstance(d.get('session_id'), str) or not KEY_OK.fullmatch(d['session_id'][:64] or '-'):
        return False
    if not (isinstance(d.get('machine'), str) and MACHINE_OK.fullmatch(d['machine'])):
        return False
    if not _num(d.get('fresh_tokens')) or not _ts_or_none(d.get('first')) or not _ts_or_none(d.get('last')):
        return False
    tasks, untied = d.get('tasks'), d.get('untied')
    if not isinstance(tasks, dict) or not isinstance(untied, dict) or not all(_num(v) for v in untied.values()):
        return False
    for k, v in tasks.items():
        if not KEY_OK.fullmatch(k) or not isinstance(v, dict) or not _num(v.get('fresh')) \
                or not _num(v.get('active_s', 0)) or not _ts_or_none(v.get('start')) or not _ts_or_none(v.get('end')):
            return False
        if not isinstance(v.get('by_role', {}), dict) or not all(
                k2 in ('build', 'review', 'fix', 'lead') and _num(x) for k2, x in v.get('by_role', {}).items()):
            return False
        bme = v.get('by_model_effort', {})
        if not isinstance(bme, dict) or not all(isinstance(es, dict) and all(_num(x) for x in es.values())
                                                for es in bme.values()):
            return False
    return True


def read_ledger() -> list:
    """Every valid session line of every machine in the store, migrated to the current version."""
    from .schema import migrate_ledger_line
    out = []
    for p in sorted(glob.glob(os.path.join(paths.ledger_dir(), '*.jsonl'))):
        for d in read_jsonl(p):
            if schema_version(d) is None:
                continue
            m = migrate_ledger_line(d)
            if m is not None and valid_line(m):
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
                if isinstance(d, dict) and (schema_version(d) or 0) > SCHEMA_VERSION:
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
            if (schema_version(d) or 0) > SCHEMA_VERSION:
                raise NewerSchema(path)
        try:
            with open(path, encoding='utf-8') as f:
                old = f.read()
        except FileNotFoundError:
            old = ''
        if old and not old.endswith('\n'):
            old += '\n'
        atomic_write(path, old + json.dumps(event, separators=(',', ':'), sort_keys=True) + '\n')


_EVENT_SCHEMA = None


def valid_event(d: dict) -> bool:
    """A task event is used only when it matches schemas/task_event.schema.json (events can come from a sync remote)."""
    global _EVENT_SCHEMA
    from .schema import load_schema, validate
    if _EVENT_SCHEMA is None:
        _EVENT_SCHEMA = load_schema('task_event')
    if schema_version(d) != SCHEMA_VERSION:
        return False
    a = d.get('actual')
    if isinstance(a, dict) and not all(_num(x) for x in (a.get('by_role') or {}).values()):
        return False
    return not validate(d, _EVENT_SCHEMA)


def read_events() -> list:
    out = []
    for p in sorted(glob.glob(os.path.join(paths.tasks_dir(), '*.jsonl'))):
        out.extend(d for d in read_jsonl(p) if valid_event(d))
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

WARNING_CODES = ('format', 'deadline', 'lock', 'newer-schema', 'error')
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
    os.makedirs(paths.stamps_dir(), mode=0o700, exist_ok=True)
    os.close(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
    os.utime(p)
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
