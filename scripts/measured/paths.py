"""Folders and the config file (docs/DATA.md "Where it stores data")."""
from __future__ import annotations

import copy
import json
import os
import secrets

from . import SCHEMA_VERSION

APP = 'measured-estimates'

DEFAULT_SIZES = ['XS', 'S', 'M', 'L', 'XL']


def _xdg(var: str, fallback: str) -> str:
    base = os.environ.get(var) or os.path.join(os.path.expanduser('~'), fallback)
    return os.path.join(base, APP)


def config_dir() -> str:
    return _xdg('XDG_CONFIG_HOME', '.config')


def data_dir() -> str:
    return _xdg('XDG_DATA_HOME', os.path.join('.local', 'share'))


def state_dir() -> str:
    return _xdg('XDG_STATE_HOME', os.path.join('.local', 'state'))


def config_path() -> str:
    return os.path.join(config_dir(), 'config.json')


def ledger_dir() -> str:
    return os.path.join(data_dir(), 'ledger')


def tasks_dir() -> str:
    return os.path.join(data_dir(), 'tasks')


def calibration_path() -> str:
    return os.path.join(data_dir(), 'calibration.json')


def status_path() -> str:
    return os.path.join(state_dir(), 'status.json')


def seen_path() -> str:
    return os.path.join(state_dir(), 'seen.idx')


def lock_path() -> str:
    return os.path.join(state_dir(), 'lock')


def stamps_dir() -> str:
    return os.path.join(state_dir(), 'stamps')


def sync_dir() -> str:
    return os.path.join(state_dir(), 'sync')


def claude_dir() -> str:
    """Claude Code's own folder (transcripts live in its `projects/`)."""
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude')


def tilde(path: str) -> str:
    """A path with the home folder written as `~`."""
    home = os.path.expanduser('~')
    if path == home:
        return '~'
    if path.startswith(home + os.sep):
        return '~' + path[len(home):]
    return path


DEFAULT_CONFIG = {
    'schema_version': SCHEMA_VERSION,
    'machine_id': None,
    'initialized': False,  # set by `ledger init`; the hooks create the config before that
    'id_patterns': None,  # filled by ids.DEFAULT_PATTERN at load time when missing
    'commit_ids': False,
    'sizes': DEFAULT_SIZES,
    'idle_cap_min': 30,
    'stop_every_min': 15,
    'commit_window_min': 20,
    'backfill_days': 30,
    'ignore_paths': [],
    'store': {'cwd': False, 'branch': False, 'repo': False, 'title': False},
    'sync': {'remote': None, 'branch': 'measured-estimates'},
}


def new_machine_id() -> str:
    return secrets.token_hex(8)


def load_config() -> dict:
    """The config merged over the defaults. A missing file gives the defaults (machine_id None)."""
    from .ids import DEFAULT_PATTERN
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(config_path(), encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    if not cfg.get('id_patterns'):
        cfg['id_patterns'] = [DEFAULT_PATTERN]
    cfg['_exists'] = bool(raw)
    return cfg


def save_config(cfg: dict) -> None:
    from .store import atomic_write
    out = {k: v for k, v in cfg.items() if not k.startswith('_')}
    out['schema_version'] = SCHEMA_VERSION
    os.makedirs(config_dir(), exist_ok=True)
    atomic_write(config_path(), json.dumps(out, indent=2, sort_keys=True) + '\n')


def ensure_config() -> dict:
    """The config; on first use (the hooks run before `init`) it's created with a random machine id and the defaults."""
    cfg = load_config()
    if not cfg.get('machine_id'):
        cfg['machine_id'] = new_machine_id()
        save_config(cfg)
        cfg['_exists'] = True
    return cfg
