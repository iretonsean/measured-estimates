"""Traceability: every U/I test ID in docs/REQUIREMENTS.md has a test; every C test ID has a CI step; no test names
an unknown ID."""
from __future__ import annotations

import glob
import os
import re
import unittest

from helpers import ROOT


class TestTraceability(unittest.TestCase):
    def test_ids(self):
        """Every U and I test has a test; every C test has a CI step; no unknown IDs."""
        req = open(os.path.join(ROOT, 'docs', 'REQUIREMENTS.md'), encoding='utf-8').read()
        declared = dict(re.findall(r'^- (T-\d+) \(([UICXRE])\)', req, re.M))
        self.assertGreater(len(declared), 100)
        tests = ''
        for p in glob.glob(os.path.join(ROOT, 'tests', 'test_*.py')):
            tests += open(p, encoding='utf-8').read()
        named = set(re.findall(r'(?<![A-Za-z])T-\d+', ''.join(re.findall(r'"""(.*?)"""', tests, re.S))))
        ci = open(os.path.join(ROOT, '.github', 'workflows', 'ci.yml'), encoding='utf-8').read()
        missing_u = sorted(t for t, k in declared.items() if k in 'UI' and t not in named)
        missing_c = sorted(t for t, k in declared.items() if k == 'C' and t not in ci)
        unknown = sorted(named - set(declared))
        self.assertEqual(missing_u, [], 'U/I tests without a test')
        self.assertEqual(missing_c, [], 'C tests without a CI step')
        self.assertEqual(unknown, [], 'tests that name an unknown ID')


if __name__ == '__main__':
    unittest.main()
