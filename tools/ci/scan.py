#!/usr/bin/env python3
"""Generic secret and personal-data scan of the repo files (REQ-18, T-52, T-53).

  python3 tools/ci/scan.py [root]      scan every file git tracks (or every file when git isn't there)
  python3 tools/ci/scan.py --self-test build canaries at run time, check that each one is found

Only generic patterns live here. A list of private names never goes into this repo.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

ALLOWED_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@(?:users\.noreply\.github\.com|measured-estimates\.invalid|anthropic\.com)$')
PATTERNS = {
    'anthropic key': r'sk-ant-[A-Za-z0-9_-]{20,}',
    'api key (sk-)': r'(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,}',
    'github token': r'(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}',
    'aws key': r'AKIA[0-9A-Z]{16}',
    'slack token': r'xox[abp]-[A-Za-z0-9-]{10,}',
    'private key': r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
    'token assignment': r'''(?i)token\s*[:=]\s*["'][A-Za-z0-9_\-]{16,}''',
    'home path': r'(?<![A-Za-z0-9])/(?:home|Users)/[A-Za-z0-9._-]+',
    'private ipv4': r'(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d.])',
    'local hostname': r'(?<![/~.\w-])[A-Za-z0-9-]+\.local\b',
    'email': r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
}
COMPILED = {k: re.compile(v) for k, v in PATTERNS.items()}
SKIP_DIRS = {'.git', '__pycache__'}
SKIP_EXT = {'.png', '.jpg', '.gif', '.ico', '.pdf'}


def files(root):
    try:
        out = subprocess.run(['git', '-C', root, 'ls-files', '-z'], capture_output=True, check=True).stdout
        names = [n for n in out.decode().split('\0') if n]
        if names:
            return [os.path.join(root, n) for n in names]
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for d, dirs, fs in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        found += [os.path.join(d, f) for f in fs]
    return found


def scan(root):
    hits = []
    for p in files(root):
        if os.path.splitext(p)[1].lower() in SKIP_EXT or not os.path.isfile(p):
            continue
        try:
            text = open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for name, rx in COMPILED.items():
                for m in rx.finditer(line):
                    if name == 'email' and ALLOWED_EMAIL.fullmatch(m.group(0)):
                        continue
                    hits.append((os.path.relpath(p, root), i, name))
    return hits


def self_test():
    # Every canary is built from parts here, so the repo holds none of them as a literal.
    parts = {
        'anthropic key': 'sk' + '-ant-' + 'A1b2' * 6,
        'api key (sk-)': 'sk' + '-' + 'Z9y8' * 6,
        'github token': 'gh' + 'p_' + 'Q' * 36,
        'aws key': 'AK' + 'IA' + 'ABCDEFGHIJKLMNOP',
        'slack token': 'xo' + 'xb-' + '1234567890-abc',
        'private key': '-' * 5 + 'BEGIN RSA ' + 'PRIVATE KEY' + '-' * 5,
        'token assignment': 'tok' + 'en = "' + 'x' * 20 + '"',
        'home path': '/' + 'home' + '/someone/file',
        'private ipv4': '192' + '.168.' + '1.20',
        'local hostname': 'my-box' + '.local',
        'email': 'person' + '@' + 'example' + '.org',
    }
    with tempfile.TemporaryDirectory() as d:
        for name, val in parts.items():
            with open(os.path.join(d, name.replace(' ', '_') + '.txt'), 'w') as f:
                f.write(f'line with {val} inside\n')
        with open(os.path.join(d, 'ok.txt'), 'w') as f:
            f.write('clean line ~/.local/share and someone' + '@users.noreply.github.com\n')
        hits = scan(d)
    found = {n for _, _, n in hits}
    missing = set(parts) - found
    clean_hit = [h for h in hits if h[0] == 'ok.txt']
    if missing or clean_hit:
        print(f'self-test FAILED: missing {sorted(missing)}, false hits {clean_hit}')
        return 1
    print(f'self-test ok: {len(parts)} canaries found, clean file passed')
    return 0


def main(argv):
    if '--self-test' in argv:
        return self_test()
    root = argv[1] if len(argv) > 1 else '.'
    hits = scan(root)
    for p, i, name in hits:
        print(f'{p}:{i}: {name}')  # the matched value isn't printed
    print(f'{len(hits)} hits')
    return 1 if hits else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
