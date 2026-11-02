#!/usr/bin/env python3
"""Hook entry point (REQ-01, REQ-02). Never fails a session: exit 0 on every error, nothing on stdout.

  record.py session-end   hook process for SessionEnd: reads the hook JSON, starts a detached child, returns
  record.py stop          hook process for Stop (declared async): at most once per session per stop_every_min
  record.py child <reason> <hook-json>   the detached child: records, then syncs when a remote is set
  record.py manual        records the hook JSON on stdin in the foreground (for testing)
"""
import os
import sys

MIN_PYTHON = (3, 9)


def python_ok(version_info=None) -> bool:
    v = version_info if version_info is not None else sys.version_info
    return tuple(v[:2]) >= MIN_PYTHON


def _setup_path():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def read_hook_input(stream, limit=1 << 20) -> dict:
    import json
    try:
        raw = stream.read(limit)
        d = json.loads(raw) if raw and raw.strip() else {}
        return d if isinstance(d, dict) else {}
    except (ValueError, OSError, UnicodeDecodeError):
        return {}


def spawn_child(reason: str, hook: dict) -> None:
    """Start the detached child (new session, stdio to /dev/null) and return at once."""
    import json
    import subprocess
    small = {k: hook.get(k) for k in ('session_id', 'transcript_path', 'cwd') if isinstance(hook.get(k), str)}
    subprocess.Popen([sys.executable, os.path.abspath(__file__), 'child', reason, json.dumps(small)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True, cwd='/')


def run_child(reason: str, hook: dict) -> None:
    import time
    from adapters.base import Deadline
    from measured import paths, store
    from measured.recorder import record
    budget = float(os.environ.get('MEASURED_ESTIMATES_DEADLINE_S') or 30)
    deadline = time.monotonic() + budget
    cfg = paths.ensure_config()
    try:
        store.clean_stamps()
    except OSError:
        pass
    try:
        entry = record(hook, cfg, reason, deadline)
    except Deadline:
        store.add_warning('deadline')
        return
    except store.LockTimeout:
        store.add_warning('lock')
        return
    except store.NewerSchema:
        store.add_warning('newer-schema')
        return
    if entry and (cfg.get('sync') or {}).get('remote'):
        from measured import sync
        sync.run(cfg, force=(reason == 'session_end'))


def main(argv) -> None:
    if not python_ok():
        return
    _setup_path()
    mode = argv[1] if len(argv) > 1 else ''
    if mode == 'session-end':
        spawn_child('session_end', read_hook_input(sys.stdin))
    elif mode == 'stop':
        hook = read_hook_input(sys.stdin)
        from measured import paths, store
        cfg = paths.load_config()
        if store.stamp_due(hook.get('session_id') or '', float(cfg.get('stop_every_min') or 15) * 60):
            spawn_child('stop', hook)
    elif mode == 'child' and len(argv) > 3:
        import json
        try:
            hook = json.loads(argv[3])
        except ValueError:
            return
        run_child(argv[2] if argv[2] in ('session_end', 'stop', 'manual', 'backfill') else 'manual', hook)
    elif mode == 'manual':
        run_child('manual', read_hook_input(sys.stdin))


if __name__ == '__main__':
    try:
        sys.stdout = open(os.devnull, 'w')
        main(sys.argv)
    except BaseException:  # never fail a session because of the ledger
        pass
    os._exit(0)
