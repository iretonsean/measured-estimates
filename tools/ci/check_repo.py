#!/usr/bin/env python3
"""Repo checks for CI.

  check_repo.py manifests   T-89: plugin.json, marketplace.json and hooks.json parse and name existing files
  check_repo.py versions    T-99: plugin.json, marketplace.json, the package VERSION and the CHANGELOG agree
  check_repo.py stdlib      T-91: every import in scripts/, tools/ and tests/ is standard library or local
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def manifests() -> list:
    errs = []
    for p in ('.claude-plugin/plugin.json', '.claude-plugin/marketplace.json', 'hooks/hooks.json'):
        try:
            json.load(open(os.path.join(ROOT, p), encoding='utf-8'))
        except (OSError, ValueError) as e:
            errs.append(f'{p}: {e}')
    hooks = json.load(open(os.path.join(ROOT, 'hooks/hooks.json')))
    for ev, groups in hooks['hooks'].items():
        for g in groups:
            for h in g['hooks']:
                for ref in re.findall(r'\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)', h['command']):
                    if not os.path.isfile(os.path.join(ROOT, ref)):
                        errs.append(f'hooks.json {ev}: missing {ref}')
    if 'Stop' in hooks['hooks'] and not all(h.get('async') for g in hooks['hooks']['Stop'] for h in g['hooks']):
        errs.append('hooks.json: Stop must be async')
    for p in ('skills/measured-estimates/SKILL.md', 'scripts/record.py', 'scripts/ledger.py', 'data/starter.json'):
        if not os.path.isfile(os.path.join(ROOT, p)):
            errs.append(f'missing {p}')
    return errs


def versions() -> list:
    pj = json.load(open(os.path.join(ROOT, '.claude-plugin/plugin.json')))['version']
    mj = json.load(open(os.path.join(ROOT, '.claude-plugin/marketplace.json')))['plugins'][0]['version']
    pkg = re.search(r"VERSION = '([^']+)'", open(os.path.join(ROOT, 'scripts/measured/__init__.py')).read()).group(1)
    ch = re.search(r'^## \[?(\d+\.\d+\.\d+)', open(os.path.join(ROOT, 'CHANGELOG.md')).read(), re.M).group(1)
    return [] if pj == mj == pkg == ch else [f'versions differ: plugin {pj}, marketplace {mj}, package {pkg}, changelog {ch}']


def stdlib() -> list:
    names = getattr(sys, 'stdlib_module_names', None)
    if names is None:
        return ['run this check on Python 3.10 or newer']
    local = {'measured', 'adapters', 'helpers', 'record', 'ledger', 'evaluate', 'check_aggregates', 'lint_readme',
             'scan', 'check_repo', 'make_starter', 'timing'}
    errs = []
    for d in ('scripts', 'tools', 'tests'):
        for root, _, files in os.walk(os.path.join(ROOT, d)):
            for f in files:
                if not f.endswith('.py'):
                    continue
                p = os.path.join(root, f)
                tree = ast.parse(open(p, encoding='utf-8').read())
                for node in ast.walk(tree):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        mods = [node.module]
                    for m in mods:
                        top = m.split('.')[0]
                        if top not in names and top not in local and top != '__future__':
                            errs.append(f'{os.path.relpath(p, ROOT)}: imports {m}')
    return errs


def main(argv) -> int:
    fn = {'manifests': manifests, 'versions': versions, 'stdlib': stdlib}[argv[1]]
    errs = fn()
    for e in errs:
        print(e)
    print(f'{argv[1]}: {len(errs)} problems')
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
