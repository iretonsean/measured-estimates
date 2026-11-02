"""Commits from git's reflog files, read directly (REQ-07).

`git` is never run in a folder that a transcript names: a repo's config can run programs (core.fsmonitor, pagers).
Reading `<gitdir>/logs/HEAD` and, for worktrees, the common dir's `logs/refs/heads/*` gives the same entries. Branch
reflogs in the common dir survive `git worktree remove`.
"""
from __future__ import annotations

import os

from .ids import MAX_SCAN


def find_gitdir(path: str):
    """(gitdir, commondir, worktree_top) for a folder, walking up; None when there's no repo. A missing folder is
    walked up to its nearest existing parent."""
    p = os.path.abspath(path or '')
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    while True:
        dotgit = os.path.join(p, '.git')
        if os.path.isdir(dotgit):
            return dotgit, dotgit, p
        if os.path.isfile(dotgit):
            try:
                with open(dotgit, encoding='utf-8', errors='replace') as f:
                    line = f.read(4096).strip()
            except OSError:
                return None
            if not line.startswith('gitdir:'):
                return None
            gd = line[len('gitdir:'):].strip()
            gd = gd if os.path.isabs(gd) else os.path.normpath(os.path.join(p, gd))
            common = gd
            try:
                with open(os.path.join(gd, 'commondir'), encoding='utf-8') as f:
                    c = f.read(4096).strip()
                common = c if os.path.isabs(c) else os.path.normpath(os.path.join(gd, c))
            except OSError:
                pass
            return gd, common, p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def _parse_reflog(path: str, since: float, until: float, out: dict) -> None:
    try:
        f = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return
    with f:
        for line in f:
            left, sep, msg = line.rstrip('\n').partition('\t')
            if not sep or not msg.startswith('commit'):
                continue
            parts = left.split(' ')
            if len(parts) < 4:
                continue
            try:
                ts = int(parts[-2])
            except ValueError:
                continue
            if ts < since or ts > until:
                continue
            new = parts[1]
            subject = msg.split(': ', 1)[1] if ': ' in msg else ''
            out.setdefault(new, (ts, subject[:MAX_SCAN]))


def local_commits(gitdir: str, common: str, since: float, until: float) -> list:
    """[(time, subject_head)] of commits made on this machine between since and until, from the HEAD reflog of the
    worktree and the branch reflogs of the common dir; each commit once."""
    found = {}
    _parse_reflog(os.path.join(gitdir, 'logs', 'HEAD'), since, until, found)
    heads = os.path.join(common, 'logs', 'refs', 'heads')
    for root, _, files in os.walk(heads):
        for name in files:
            _parse_reflog(os.path.join(root, name), since, until, found)
    return sorted(found.values())


def head_branch(gitdir: str) -> str | None:
    try:
        with open(os.path.join(gitdir, 'HEAD'), encoding='utf-8') as f:
            v = f.read(512).strip()
    except OSError:
        return None
    if v.startswith('ref: refs/heads/'):
        return v[len('ref: refs/heads/'):][:100]
    return None


def repo_name(common: str, top: str) -> str:
    """The repo folder name: the folder that holds the common .git dir (a worktree reports its main repo)."""
    if os.path.basename(common) == '.git':
        return os.path.basename(os.path.dirname(common))[:100]
    return os.path.basename(top)[:100]
