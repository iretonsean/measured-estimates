"""Ties each message's fresh tokens to tasks, roles and times (REQ-05..REQ-09). Agent-neutral: works on
`adapters.base` records only.

Rules per transcript, in order:
1. Tag: an ITEM line in the first prompt ties the whole transcript; one in a later prompt ties from then on. A subagent
   without its own tag takes its session's tag. Role from ROLE lines (default build).
2. Commits (only with commit matching on): a message counts for the next commit this transcript made itself, when its
   subject holds a task ID.
3. Lead touches: tokens that rule 2 would put in _other/_after go to the tasks touched at both ends of the stretch (IDs
   in its own commit subjects and lead commands, with commit matching on; ITEM lines of prompts it gave to agents,
   always). Role lead.
4. Else _other (before a commit without ID), _after (after the last commit) or _untagged (commit matching off).
"""
from __future__ import annotations

import re

from adapters.base import Session, Transcript

from .ids import ROLES, Matcher, ids_from_items

BRANCH = re.compile(r'(?<![\w.-])(?:origin/)?(?:feat|feature|fix|bugfix|hotfix|chore|docs|test|wip|release)/([\w.-]{1,100})')


def transcript_tag(t: Transcript, matcher: Matcher):
    """(item_changes [(time, ids)], role_changes [(time, role)]) or None when no ITEM line ties anything."""
    changes, roles = [], []
    first_role = None
    for p in t.prompts:
        ids = ids_from_items(p.items, matcher) if p.items else []
        if p.first:
            if ids:
                changes.append((0.0, ids))
            first_role = p.role
        else:
            if ids:
                changes.append((p.time, ids))
            if p.role:
                roles.append((p.time, p.role))
    if not changes:
        return None
    return sorted(changes, key=lambda x: x[0]), [(0.0, first_role or 'build')] + sorted(roles)


def _at(changes, t):
    v = None
    for at, x in changes:
        if at <= t:
            v = x
    return v


def command_ids(head: str, matcher: Matcher) -> set:
    ids = set(matcher.find(head))
    for m in BRANCH.finditer(head):
        ids.update(matcher.find(m.group(1), upper=True))
    return ids


def lead_touches(t: Transcript, commits: list, matcher: Matcher, commit_ids: bool) -> list:
    out = []
    if commit_ids:
        out += [(ct, set(matcher.find(subj))) for ct, subj in commits]
        out += [(e.time, command_ids(e.head, matcher)) for e in t.tools if e.kind == 'command']
    out += [(e.time, set(ids_from_items(e.items, matcher))) for e in t.tools if e.kind == 'agent']
    return sorted(((x, ids) for x, ids in out if ids), key=lambda y: y[0])


def _touched(touches, t):
    before = [x for x in touches if x[0] <= t]
    after = [x for x in touches if x[0] > t]
    return sorted((before[-1][1] if before else set()) | (after[0][1] if after else set()))


def transcript_shares(t: Transcript, commits: list, tag, touches, matcher: Matcher, idle_cap_s: float,
                      commit_ids: bool, out: dict, untied: dict) -> None:
    """Adds this transcript's shares into `out` ({key: {fresh, by_role, by_model_effort, active_s, start, end}}) and
    `untied`. `commits` = [(time, subject_head)] this transcript made itself."""
    prev = None
    for m in t.messages:
        ts = m.time
        gap = ts - prev if prev is not None and 0 <= ts - prev <= idle_cap_s else 0.0
        prev = ts if prev is None else max(prev, ts)
        nxt = None
        tagged = _at(tag[0], ts) if tag else None
        if tagged:
            keys, role = list(tagged), _at(tag[1], ts) or 'build'
        else:
            role = 'build'
            keys = []
            if commit_ids:
                nxt = next((c for c in commits if c[0] >= ts), None)
                keys = matcher.find(nxt[1]) if nxt else []
            if not keys:
                keys = _touched(touches, ts)
                if keys:
                    role = 'lead'
                else:
                    k = ('_other' if nxt else '_after') if commit_ids else '_untagged'
                    untied[k] = untied.get(k, 0) + m.fresh
                    continue
        share = m.fresh / len(keys)
        for k in keys:
            r = out.setdefault(k, {'fresh': 0.0, 'by_role': {}, 'by_model_effort': {}, 'active_s': 0.0,
                                   'start': None, 'end': None})
            r['fresh'] += share
            r['by_role'][role] = r['by_role'].get(role, 0.0) + share
            me = r['by_model_effort'].setdefault(m.model, {})
            me[m.effort] = me.get(m.effort, 0.0) + share
            r['active_s'] += gap / len(keys)
            if role != 'lead':  # the lead's waiting doesn't move a task's first message or last commit
                end = nxt[0] if nxt else ts
                r['start'] = ts if r['start'] is None else min(r['start'], ts)
                r['end'] = end if r['end'] is None else max(r['end'], end)


def own_commits(t: Transcript, repo_commits: list, window_s: float) -> list:
    """The commits this transcript made: a commit within the window after one of its own `git commit` calls."""
    calls = [e.time for e in t.tools if e.kind == 'commit']
    if not calls:
        return []
    return sorted({c for c in repo_commits if any(0 <= c[0] - call <= window_s for call in calls)})


def attribute(session: Session, commits_for, matcher: Matcher, idle_cap_s: float, window_s: float,
              commit_ids: bool):
    """(tasks, untied, tagged_field, n_commits). `commits_for(transcript)` gives the reflog commits of the folders that
    transcript worked in ([(time, subject_head)])."""
    tags = {t.tid: transcript_tag(t, matcher) for t in session.transcripts}
    session_tag = tags.get('main')
    out, untied = {}, {}
    n_commits = set()
    for t in session.transcripts:
        tag = tags[t.tid] or session_tag
        commits = own_commits(t, commits_for(t), window_s) if commit_ids else []
        n_commits.update(c for c in commits if matcher.find(c[1]))
        whole = tag is not None and tag[0][0][0] == 0
        touches = [] if whole else lead_touches(t, commits, matcher, commit_ids)
        transcript_shares(t, commits, tag, touches, matcher, idle_cap_s, commit_ids, out, untied)
    tasks = {}
    for k in sorted(out):
        r = out[k]
        tasks[k] = {
            'fresh': int(round(r['fresh'])),
            'by_role': {role: int(round(v)) for role, v in sorted(r['by_role'].items(), key=lambda x: ROLES.index(x[0]))},
            'by_model_effort': {mo: {e: int(round(v)) for e, v in sorted(es.items())}
                                for mo, es in sorted(r['by_model_effort'].items())},
            'active_s': int(round(r['active_s'])),
            'start': r['start'],
            'end': r['end'],
        }
    tagged = None
    if session_tag:
        ids = []
        for _, x in session_tag[0]:
            ids += [i for i in x if i not in ids]
        tagged = {'ids': ids, 'role': session_tag[1][0][1]}
        if session_tag[0][0][0] > 0:
            tagged['from'] = session_tag[0][0][0]
    return tasks, {k: int(round(v)) for k, v in sorted(untied.items())}, tagged, len(n_commits)
