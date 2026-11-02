#!/usr/bin/env python3
"""README language checks (REQ-42, T-111, T-112) and the README-numbers check (REQ-41, T-109).

  python3 tools/ci/lint_readme.py README.md               sentence length, passive markers, banned words, sparkles
  python3 tools/ci/lint_readme.py --numbers README.md docs/RESULTS.md
  python3 tools/ci/lint_readme.py --self-test
"""
from __future__ import annotations

import re
import sys

PROCEDURE_MAX, DESCRIPTION_MAX = 20, 25
PROCEDURE_HEADINGS = re.compile(r'^(?:how to|install|delete|uninstall|use|run|add|set|remove|update|check|tag|estimate|'
                                r'start|record|turn|get|see|contribute|report|forget)\b', re.I)
PASSIVE = ('is done by', 'was made by', 'are sent by', 'is sent by', 'was done by', 'are made by')
BANNED = ('seamless', 'powerful', 'magic', 'effortless', 'revolutionary', 'supercharge')
SPARKLES = ('✦', '✧', '✨', '✩', '✪', '✫', '✬', '✭', '✮', '✯',
            '✰', '✱', '✲', '✳', '✴', '✵', '✶', '✷', '✸', '✹',
            '\U0001f31f', '⭐')
SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9`"(\[*_])')
ITEM = re.compile(r'^\s*(?:(\d+)\.|[-*])\s+')


def words(s: str) -> int:
    s = re.sub(r'`[^`]*`', 'X', s)  # inline code counts as one word
    s = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', s)
    return len([w for w in s.split() if re.search(r'[A-Za-z0-9]', w)])


def units(text: str):
    """(kind, heading, text, line no) for each paragraph or list item outside code, tables and comments."""
    out, buf, kind, start = [], [], None, 0
    heading = ''
    in_code = in_comment = False

    def flush():
        nonlocal buf, kind
        if buf:
            out.append((kind, heading, ' '.join(buf), start))
        buf, kind = [], None
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if line.strip().startswith('```'):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        if '<!--' in line:
            in_comment = '-->' not in line.split('<!--', 1)[1]
            flush()
            continue
        if in_comment:
            if '-->' in line:
                in_comment = False
            continue
        s = line.strip()
        if not s or s.startswith('|'):
            flush()
            continue
        if s.startswith('#'):
            flush()
            heading = s.lstrip('#').strip()
            continue
        if re.fullmatch(r'\[[^\]]*\]\([^)]*\)', s) or re.fullmatch(r'<[^>]+>', s):
            flush()
            continue
        m = ITEM.match(line)
        if m:
            flush()
            kind, start = ('numbered' if m.group(1) else 'bullet'), i
            buf = [line[m.end():].strip()]
        else:
            if kind is None:
                kind, start = 'prose', i
            buf.append(s)
    flush()
    return out


def lint(text: str) -> list:
    errs = []
    for kind, heading, para, ln in units(text):
        proc = kind == 'numbered' or (kind == 'bullet' and PROCEDURE_HEADINGS.match(heading or ''))
        limit = PROCEDURE_MAX if proc else DESCRIPTION_MAX
        for sent in SENT_SPLIT.split(para):
            n = words(sent)
            if n > limit:
                errs.append(f'line {ln}: {n} words (max {limit} for {"a procedure" if proc else "a description"}): '
                            f'{sent[:60]}...')
        low = para.lower()
        for p in PASSIVE:
            if p in low:
                errs.append(f'line {ln}: passive "{p}"')
        for b in BANNED:
            if re.search(rf'\b{b}', low):
                errs.append(f'line {ln}: banned word "{b}"')
    for ch in SPARKLES:
        if ch in text:
            errs.append(f'sparkle character U+{ord(ch):04X}')
    return errs


NUM = re.compile(r'(?<![A-Za-z0-9.])-?\d+(?:\.\d+)?(?![A-Za-wyz0-9])')


def norm(s: str) -> str:
    s = s.lstrip('+')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    if s in ('-0', ''):
        s = '0'
    return s


def numbers(text: str) -> set:
    return {norm(m.group(0)) for m in NUM.finditer(text)}


def section(text: str) -> str:
    m = re.search(r'<!-- results:start -->(.*?)<!-- results:end -->', text, re.S)
    return m.group(1) if m else ''


def check_numbers(readme: str, results: str) -> list:
    sec = section(readme)
    if not sec:
        return ['README: no <!-- results:start --> ... <!-- results:end --> section']
    have = numbers(results)
    return [f'README number {n} is not in docs/RESULTS.md' for n in sorted(numbers(sec)) if n not in have]


def self_test() -> int:
    long = 'This sentence has far too many words in it because it keeps going on and on and on past the limit of ' \
           'twenty five words for sure.'
    ok = bool(lint(long + '\n'))
    ok &= not lint('A short sentence. Another one.\n')
    ok &= bool(lint('## Install\n\n1. Run the first command and then also run the second command and the third '
                    'command and the fourth one right now.\n'))
    ok &= bool(lint('The record is done by the hook.\n'))
    ok &= bool(lint('A seamless start.\n'))
    ok &= bool(lint('Look ' + chr(0x2728) + '\n'))
    ok &= not lint('```\n' + long + '\n```\n')
    ok &= check_numbers('<!-- results:start -->ratio 0.30x, 55 of 82, 41%<!-- results:end -->',
                        'median 0.3 and 55 / 82 and 41%') == []
    ok &= bool(check_numbers('<!-- results:start -->ratio 0.31x<!-- results:end -->', 'median 0.3'))
    ok &= numbers('H1a and 2026-W43') == {'2026'}
    print('self-test ok' if ok else 'self-test FAILED')
    return 0 if ok else 1


def main(argv) -> int:
    if '--self-test' in argv:
        return self_test()
    if '--numbers' in argv:
        a = [x for x in argv[1:] if x != '--numbers']
        errs = check_numbers(open(a[0], encoding='utf-8').read(), open(a[1], encoding='utf-8').read())
    else:
        errs = lint(open(argv[1], encoding='utf-8').read())
    for e in errs:
        print(e)
    print(f'{len(errs)} problems')
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
