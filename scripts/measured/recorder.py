"""Records one session: adapter -> de-duplication -> attribution -> one ledger line (REQ-01..REQ-14)."""
from __future__ import annotations

import fnmatch
import os
import time

import adapters
from adapters.base import Deadline, Session

from . import SCHEMA_VERSION, VERSION, gitrefs, paths, store
from .attribute import attribute
from .ids import Matcher

LEDGER_KEYS = ('schema_version', 'session_id', 'agent', 'adapter_version', 'machine', 'reason', 'recorded_at', 'first',
               'last', 'messages', 'duplicate_messages', 'subagents', 'skipped_lines', 'fresh_tokens',
               'cache_read_tokens', 'by_model_effort', 'tasks', 'untied', 'tagged', 'commits')
OPT_IN = ('cwd', 'branch', 'repo', 'title')


def ignored(cwd: str, patterns) -> bool:
    """True when the folder or one of its parents matches an `ignore_paths` glob (REQ-43)."""
    if not cwd or not patterns:
        return False
    pats = [os.path.normpath(os.path.expanduser(p)) for p in patterns if isinstance(p, str) and p]
    p = os.path.normpath(os.path.expanduser(cwd))
    while True:
        if any(fnmatch.fnmatchcase(p, pat) for pat in pats):
            return True
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent


def session_cwd(s: Session, hook_cwd: str) -> str:
    if hook_cwd:
        return hook_cwd
    for t in s.transcripts:
        if t.tid == 'main' and t.cwds:
            return sorted(t.cwds)[0]
    return ''


def dedupe(s: Session, seen: dict) -> int:
    """Drop messages whose key another session already counted; claim the rest for this session (REQ-03). Returns the
    number dropped. `seen` (hash -> session id) is updated in place."""
    dropped = 0
    kept = set()  # a key in two transcripts of the same session also counts once
    for t in s.transcripts:
        keep = []
        for m in t.messages:
            h = store.key_hash(m.key)
            owner = seen.get(h)
            if (owner is not None and owner != s.session_id) or h in kept:
                dropped += 1
                continue
            kept.add(h)
            seen[h] = s.session_id
            keep.append(m)
        t.messages = keep
    return dropped


def build_entry(s: Session, cfg: dict, reason: str, hook_cwd: str, duplicates: int, adapter) -> dict | None:
    msgs = [m for t in s.transcripts for m in t.messages]
    if not msgs:
        return None
    first = min(m.time for m in msgs)
    last = max(m.time for m in msgs)
    matcher = Matcher(cfg['id_patterns'])
    commit_ids = bool(cfg.get('commit_ids'))
    cache = {}

    def commits_for(t):
        if not commit_ids:
            return []
        found = set()
        for cwd in t.cwds | ({hook_cwd} if hook_cwd and t.tid == 'main' else set()):
            g = gitrefs.find_gitdir(cwd)
            if not g:
                continue
            if g not in cache:
                cache[g] = gitrefs.local_commits(g[0], g[1], first - 60, last + cfg['commit_window_min'] * 60)
            found.update(cache[g])
        return sorted(found)

    tasks, untied, tagged, n_commits = attribute(s, commits_for, matcher, cfg['idle_cap_min'] * 60,
                                                 cfg['commit_window_min'] * 60, commit_ids)
    for v in tasks.values():
        v['start'], v['end'] = store.iso(v['start']), store.iso(v['end'])
    if tagged and 'from' in tagged:
        tagged['from'] = store.iso(tagged['from'])
    bme = {}
    for m in msgs:
        c = bme.setdefault(m.model, {}).setdefault(m.effort, {'fresh': 0, 'cache_reads': 0, 'messages': 0})
        c['fresh'] += m.fresh
        c['cache_reads'] += m.cache_reads
        c['messages'] += 1
    entry = {
        'schema_version': SCHEMA_VERSION, 'session_id': s.session_id, 'agent': adapter.name,
        'adapter_version': adapter.version, 'machine': cfg['machine_id'], 'reason': reason,
        'recorded_at': store.now_iso(), 'first': store.iso(first), 'last': store.iso(last), 'messages': len(msgs),
        'duplicate_messages': duplicates, 'subagents': sum(1 for t in s.transcripts if t.tid != 'main'),
        'skipped_lines': s.skipped_lines, 'fresh_tokens': sum(m.fresh for m in msgs),
        'cache_read_tokens': sum(m.cache_reads for m in msgs),
        'by_model_effort': {mo: dict(sorted(es.items())) for mo, es in sorted(bme.items())},
        'tasks': tasks, 'untied': untied, 'tagged': tagged, 'commits': n_commits,
    }
    opt = cfg.get('store') or {}
    if opt.get('cwd') and hook_cwd:
        entry['cwd'] = paths.tilde(hook_cwd)[:300]
    if (opt.get('branch') or opt.get('repo')) and hook_cwd:
        g = gitrefs.find_gitdir(hook_cwd)
        if g and opt.get('branch'):
            b = gitrefs.head_branch(g[0])
            if b:
                entry['branch'] = b
        if g and opt.get('repo'):
            entry['repo'] = gitrefs.repo_name(g[1], g[2])
    if opt.get('title') and s.title:
        entry['title'] = s.title[:80]
    return entry


def record(hook: dict, cfg: dict, reason: str, deadline: float, adapter=None) -> dict | None:
    """Record one session from hook input. Writes the line; returns it, or None when there's nothing to record.
    Raises Deadline or store.LockTimeout (the caller writes the warning and keeps the old line)."""
    adapter = adapter or adapters.get('claude-code')
    transcript = hook.get('transcript_path') or ''
    if not isinstance(transcript, str) or not transcript.endswith('.jsonl') or not os.path.isfile(transcript):
        return None
    sid = hook.get('session_id') or os.path.basename(transcript)[:-6]
    sid = ''.join(c for c in str(sid) if c.isalnum() or c in '-_')[:80]
    hook_cwd = hook.get('cwd') if isinstance(hook.get('cwd'), str) else ''
    if ignored(hook_cwd, cfg.get('ignore_paths')):
        return None
    s = adapter.read_session(transcript, sid, deadline, want_title=bool((cfg.get('store') or {}).get('title')))
    hook_cwd = session_cwd(s, hook_cwd)
    if ignored(hook_cwd, cfg.get('ignore_paths')):
        return None
    if s.lines and not any(t.messages for t in s.transcripts) and s.lines - s.skipped_lines > 0 \
            and not any(t.prompts for t in s.transcripts):
        store.add_warning('format')
        return None
    if time.monotonic() > deadline:
        raise Deadline(transcript)
    with store.Lock(paths.lock_path(), deadline):
        seen = store.load_seen()
        dup = dedupe(s, seen)
        entry = build_entry(s, cfg, reason, hook_cwd, dup, adapter)
        if entry is None:
            return None
        if time.monotonic() > deadline:
            raise Deadline(transcript)
        store.replace_session_line(cfg['machine_id'], entry)
        store.save_seen(seen)
    return entry
