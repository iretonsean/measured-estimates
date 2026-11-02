"""The adapter interface (REQ-30). One adapter per agent turns that agent's session files into these records.

The core (attribution, recorder) imports only this module, never an agent-specific one. An adapter must:
- read files line by line, never whole (REQ-12);
- keep no prompt text: only the ITEM/ROLE line parts that `measured.ids.tag_lines` returns, and the first 200
  characters of commands it marks as commits or lead commands;
- check `deadline` (time.monotonic value) often and raise `Deadline` when it passes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set


class Deadline(Exception):
    pass


@dataclass
class Message:
    key: str  # message id, else request id, else line uuid
    time: float  # epoch seconds, UTC
    model: str
    effort: str
    fresh: int  # input + output + cache writes
    cache_reads: int


@dataclass
class Prompt:
    time: float
    first: bool  # the first human prompt of the transcript
    items: List[str]  # text after each ITEM: (at most 200 chars each)
    role: Optional[str]


@dataclass
class ToolEvent:
    time: float
    kind: str  # 'commit' (a git commit call), 'command' (push/merge/gh pr/gh run), 'agent' (a prompt with ITEM lines)
    head: str = ''  # at most 200 chars of the command, from the lead command on
    items: List[str] = field(default_factory=list)


@dataclass
class Transcript:
    tid: str  # 'main' or 'sub:<file name>'
    messages: List[Message] = field(default_factory=list)
    prompts: List[Prompt] = field(default_factory=list)
    tools: List[ToolEvent] = field(default_factory=list)
    cwds: Set[str] = field(default_factory=set)


@dataclass
class Session:
    session_id: str
    transcripts: List[Transcript]
    cwd: str = ''
    title: Optional[str] = None
    skipped_lines: int = 0
    lines: int = 0  # lines read, to tell an empty file from an unknown format


class Adapter:
    name = 'base'
    version = '0'

    def read_session(self, transcript_path: str, session_id: str, deadline: float, want_title: bool = False) -> Session:
        raise NotImplementedError

    def list_sessions(self, since_epoch: float) -> list:
        """[(transcript_path, session_id, mtime)] of sessions changed since `since_epoch`, oldest first."""
        raise NotImplementedError
