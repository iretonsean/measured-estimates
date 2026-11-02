"""Task IDs, process keys and tag lines (REQ-06, REQ-08)."""
from __future__ import annotations

import re
import subprocess
import sys
from typing import Iterable

# Any `ABC-123` form; used by `init --yes`, only on ITEM lines until the person confirms (REQ-08).
DEFAULT_PATTERN = r'(?<![A-Za-z0-9_-])[A-Z][A-Z0-9]{1,9}-\d{1,6}(?![A-Za-z0-9_])'
# Common words of that form that are no task IDs (UTF-8, SHA-256, GPT-4 ...).
STOPLIST = frozenset({'UTF', 'SHA', 'ISO', 'RFC', 'AES', 'GPT', 'HTTP', 'TLS', 'CVE', 'UTC', 'ES', 'MD', 'PEP'})
ISSUE_PATTERN = r'(?<![\w&/])#\d{1,6}(?![0-9A-Za-z_])'

MAX_SCAN = 200  # characters of an ITEM line, a commit subject or a command that are searched (REQ-06, REQ-07)
TAG_ITEM = re.compile(r'^[ \t]*ITEM:[ \t]*([^\n]{0,%d})' % MAX_SCAN, re.M)
TAG_ROLE = re.compile(r'^[ \t]*ROLE:[ \t]*(build|review|fix|lead)(?![\w-])', re.M | re.I)
PROCESS = re.compile(r'(?<![\w:-])process:([a-z0-9-]{1,32})(?![\w-])', re.I)
ROLES = ('build', 'review', 'fix', 'lead')


def pattern_from_example(example: str) -> str:
    """A prefix-anchored pattern from one example task ID (ENG-42, #12, K42). ValueError when no form fits."""
    ex = (example or '').strip()
    m = re.fullmatch(r'#(\d{1,6})', ex)
    if m:
        return ISSUE_PATTERN
    m = re.fullmatch(r'([A-Za-z][A-Za-z0-9]{0,9})([-_])(\d{1,6})', ex)
    if m:
        return r'(?<![A-Za-z0-9_-])%s%s\d{1,6}(?![0-9A-Za-z_])' % (re.escape(m.group(1)), re.escape(m.group(2)))
    m = re.fullmatch(r'([A-Z])(\d{2,4})', ex)
    if m:
        return r'(?<![A-Za-z0-9_-])%s\d{2,4}(?:\.\d+)?(?![0-9A-Za-z_])' % m.group(1)
    raise ValueError(f'no ID form fits {ex!r}; use forms such as ENG-42, #12 or K42, or pass --id-pattern')


_CHECK = r'''
import re, sys, time
p = re.compile(sys.argv[1])
tests = ['a' * 10000, 'A' * 10000, '-' * 10000, 'A-' * 5000, '1' * 10000, 'ABC-' + '1' * 9990 + '!', 'a1-' * 3333,
         ' ' * 10000, '#' * 10000, 'Aa' * 5000]
t0 = time.perf_counter()
for s in tests:
    p.findall(s)
print(time.perf_counter() - t0)
'''


def validate_pattern(pattern: str, limit_s: float = 0.05, hard_timeout_s: float = 3.0) -> str | None:
    """None when the pattern is fit for use, else the reason. Checks: compiles, doesn't match an empty string, and
    takes at most `limit_s` on adversarial strings (run in a child process so a catastrophic pattern can be stopped)."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f'the pattern does not compile: {e}'
    if rx.search('') is not None or rx.fullmatch('') is not None:
        return 'the pattern matches an empty string'
    try:
        out = subprocess.run([sys.executable, '-c', _CHECK, pattern], capture_output=True, text=True,
                             timeout=hard_timeout_s, stdin=subprocess.DEVNULL)
        took = float(out.stdout.strip() or 'inf')
    except (subprocess.TimeoutExpired, ValueError, OSError):
        took = float('inf')
    if took > limit_s:
        return f'the pattern is too slow on long text ({took if took != float("inf") else "timeout"} s)'
    return None


class Matcher:
    """Finds task IDs with the configured patterns (stoplist on the default pattern)."""

    def __init__(self, patterns: Iterable[str]):
        self.patterns = [(re.compile(p), p == DEFAULT_PATTERN) for p in patterns]

    def find(self, text: str, upper: bool = False) -> list:
        """IDs in the first MAX_SCAN characters of a text, in order, each once."""
        t = (text or '')[:MAX_SCAN]
        if upper:
            t = t.upper()
        found = []
        for rx, stop in self.patterns:
            for m in rx.finditer(t):
                v = m.group(0)
                if stop and v.split('-', 1)[0] in STOPLIST:
                    continue
                found.append((m.start(), v))
        out = []
        for _, v in sorted(found):
            if v not in out:
                out.append(v)
        return out

    def is_key(self, key: str) -> bool:
        if PROCESS.fullmatch(key or ''):
            return True
        return any(rx.fullmatch(key or '') for rx, _ in self.patterns)


def tag_lines(text: str) -> tuple:
    """(item_texts, role) of one prompt: the first MAX_SCAN characters after each `ITEM:` and the first valid `ROLE:`.
    Only these leave the adapter; the rest of the prompt is dropped."""
    if not text or ('ITEM:' not in text and 'ROLE:' not in text):
        return [], None
    items = [m.group(1) for m in TAG_ITEM.finditer(text)]
    r = TAG_ROLE.search(text)
    return items, (r.group(1).lower() if r else None)


def ids_from_items(item_texts: Iterable[str], matcher: Matcher) -> list:
    """Task IDs and process keys on ITEM lines, in order, each once."""
    out = []
    for t in item_texts:
        found = [(m.start(), 'process:' + m.group(1).lower()) for m in PROCESS.finditer(t)]
        masked = PROCESS.sub(lambda m: ' ' * len(m.group(0)), t)
        rx_found = []
        for v in matcher.find(masked):
            rx_found.append((masked.find(v), v))
        for _, v in sorted(found + rx_found):
            if v not in out:
                out.append(v)
    return out
