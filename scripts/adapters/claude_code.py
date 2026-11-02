"""Claude Code adapter: reads `~/.claude/projects/*/<session>.jsonl` and `<session>/subagents/*.jsonl` (REQ-30).

Format notes (Claude Code 2.1.x): one JSON object per line. Assistant lines carry `message.usage`, `message.model`,
`message.id`, `requestId`, `timestamp`, `cwd`, and `perTurnEffort` / `effort`. A streamed reply repeats the same
message id on several lines; the last line for a key wins. Human prompts are `type: user` lines that aren't `isMeta`
and have string content or text blocks. A change in this format makes the golden-sample test in `tests/test_record.py` fail.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import time
from datetime import datetime

from measured.ids import MAX_SCAN, tag_lines

from .base import Adapter, Deadline, Message, Prompt, Session, ToolEvent, Transcript

GIT_COMMIT = re.compile(r'\bgit\b[^|;&\n]{0,200}?\bcommit\b')
LEAD_CMD = re.compile(r'\bgit\b[^|;&\n]{0,200}?\b(?:push|merge)\b|\bgh\s+(?:pr|run)\b')
EFFORT_OK = re.compile(r'[a-z0-9-]{1,16}')
MODEL_OK = re.compile(r'[A-Za-z0-9._:/@-]{1,64}')
AGENT_TOOLS = {'Agent': 'prompt', 'Task': 'prompt', 'SendMessage': 'message'}
CHECK_EVERY = 200  # lines between deadline checks


def to_epoch(at) -> float | None:
    try:
        return datetime.fromisoformat(str(at).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return None


def effort_of(d: dict) -> str:
    """`perTurnEffort`, else `effort`, else 'unknown' (REQ-04); a value that doesn't look like an effort word is
    'unknown' too, so no free text gets in."""
    for k in ('perTurnEffort', 'effort'):
        v = d.get(k)
        if isinstance(v, str) and v:
            v = v.strip().lower()
            return v if EFFORT_OK.fullmatch(v) else 'unknown'
    return 'unknown'


def model_of(msg: dict) -> str:
    v = msg.get('model')
    if isinstance(v, str) and MODEL_OK.fullmatch(v):
        return v
    return 'unknown'


def prompt_text(d: dict) -> str:
    c = (d.get('message') or {}).get('content') if isinstance(d.get('message'), dict) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(b.get('text') or '' for b in c if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def read_transcript(path: str, tid: str, deadline: float, want_title: bool = False):
    """(Transcript, skipped_lines, lines, title) of one file. Raises Deadline."""
    t = Transcript(tid=tid)
    msgs = {}
    tool_ids = set()
    skipped = lines = 0
    first_seen = False
    title = None
    with open(path, encoding='utf-8', errors='replace') as f:
        for raw in f:
            lines += 1
            if lines % CHECK_EVERY == 0 and time.monotonic() > deadline:
                raise Deadline(path)
            if not raw.strip():
                continue
            try:
                d = json.loads(raw)
            except (ValueError, RecursionError):
                skipped += 1
                continue
            if not isinstance(d, dict):
                skipped += 1
                continue
            cwd = d.get('cwd')
            if isinstance(cwd, str) and cwd:
                t.cwds.add(cwd)
            typ = d.get('type')
            if want_title and typ == 'custom-title' and isinstance(d.get('customTitle'), str):
                title = d['customTitle']
            at = to_epoch(d.get('timestamp'))
            msg = d.get('message') if isinstance(d.get('message'), dict) else {}
            if typ == 'user' and not d.get('isMeta'):
                text = prompt_text(d)
                if text.strip() and at is not None:
                    items, role = tag_lines(text)
                    first = not first_seen
                    first_seen = True
                    if first or items or role:
                        t.prompts.append(Prompt(time=at, first=first, items=items, role=role))
                continue
            if typ != 'assistant' or at is None:
                continue
            for block in msg.get('content') or []:
                if not isinstance(block, dict) or block.get('type') != 'tool_use':
                    continue
                bid = block.get('id')
                if bid and bid in tool_ids:
                    continue
                tool_ids.add(bid)
                name = block.get('name')
                inp = block.get('input') if isinstance(block.get('input'), dict) else {}
                if name == 'Bash':
                    cmd = inp.get('command') if isinstance(inp.get('command'), str) else ''
                    if GIT_COMMIT.search(cmd):
                        t.tools.append(ToolEvent(time=at, kind='commit'))
                    m = LEAD_CMD.search(cmd)
                    if m:
                        t.tools.append(ToolEvent(time=at, kind='command', head=cmd[m.start():m.start() + MAX_SCAN]))
                    items, _ = tag_lines(cmd)
                    if items:
                        t.tools.append(ToolEvent(time=at, kind='agent', items=items))
                elif name in AGENT_TOOLS:
                    text = inp.get(AGENT_TOOLS[name])
                    if not isinstance(text, str):
                        text = inp.get('content') if isinstance(inp.get('content'), str) else ''
                    items, _ = tag_lines(text)
                    if items:
                        t.tools.append(ToolEvent(time=at, kind='agent', items=items))
            u = msg.get('usage')
            if not isinstance(u, dict):
                continue
            model = model_of(msg)
            if str(msg.get('model') or '').startswith('<'):
                continue  # synthetic messages are no model calls
            key = msg.get('id') or d.get('requestId') or d.get('uuid')
            if not key:
                continue

            def n(k):
                v = u.get(k)
                return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0 else 0
            msgs[str(key)] = Message(key=str(key), time=at, model=model, effort=effort_of(d),
                                     fresh=n('input_tokens') + n('output_tokens') + n('cache_creation_input_tokens'),
                                     cache_reads=n('cache_read_input_tokens'))
    t.messages = sorted(msgs.values(), key=lambda m: (m.time, m.key))
    return t, skipped, lines, title


class ClaudeCode(Adapter):
    name = 'claude-code'
    version = '1'

    def read_session(self, transcript_path: str, session_id: str, deadline: float, want_title: bool = False) -> Session:
        base = transcript_path[:-6] if transcript_path.endswith('.jsonl') else transcript_path
        files = [(transcript_path, 'main')] + [
            (p, 'sub:' + os.path.basename(p)[:-6]) for p in sorted(glob.glob(os.path.join(base, 'subagents', '*.jsonl')))]
        s = Session(session_id=session_id, transcripts=[])
        for p, tid in files:
            try:
                t, skipped, lines, title = read_transcript(p, tid, deadline, want_title and tid == 'main')
            except OSError:
                continue
            s.transcripts.append(t)
            s.skipped_lines += skipped
            s.lines += lines
            if title:
                s.title = title
        if want_title and not s.title:
            try:
                with open(os.path.join(base, 'custom-title.json'), encoding='utf-8') as f:
                    v = json.load(f).get('customTitle')
                    if isinstance(v, str):
                        s.title = v
            except (OSError, ValueError, AttributeError):
                pass
        return s

    def list_sessions(self, since_epoch: float) -> list:
        root = os.path.join(_claude_dir(), 'projects')
        out = []
        for p in glob.glob(os.path.join(root, '*', '*.jsonl')):
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if mt < since_epoch:
                continue
            out.append((first_time(p) or mt, p, os.path.basename(p)[:-6]))
        return [(p, sid, t) for t, p, sid in sorted(out)]


def _claude_dir() -> str:
    from measured.paths import claude_dir
    return claude_dir()


def first_time(path: str) -> float | None:
    """The first timestamp in the first 200 lines (to backfill in time order)."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for i, raw in enumerate(f):
                if i > 200:
                    break
                if '"timestamp"' not in raw:
                    continue
                try:
                    v = to_epoch(json.loads(raw).get('timestamp'))
                except (ValueError, AttributeError, RecursionError):
                    continue
                if v is not None:
                    return v
    except OSError:
        pass
    return None
