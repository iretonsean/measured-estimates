"""Task ID patterns and init (REQ-08, REQ-19)."""
from __future__ import annotations

import re
import unittest

from helpers import Env

from measured import paths
from measured.ids import DEFAULT_PATTERN, ISSUE_PATTERN, Matcher, pattern_from_example, validate_pattern


class TestPatterns(unittest.TestCase):
    def test_default(self):
        """T-28 the default matches ENG-42 and ABC-123, not UTF-8, SHA-256, ISO-8601, GPT-4, AES-256 or numbers."""
        m = Matcher([DEFAULT_PATTERN])
        self.assertEqual(m.find('ENG-42 and ABC-123'), ['ENG-42', 'ABC-123'])
        for w in ('UTF-8', 'SHA-256', 'ISO-8601', 'GPT-4', 'AES-256', '1234', 'review-S1', 'x-ABC-1'):
            self.assertEqual(m.find(f'text {w} text'), [], w)

    def test_custom(self):
        """T-29 a custom pattern from the config replaces the default."""
        m = Matcher([r'TK\d+'])
        self.assertEqual(m.find('TK7 ENG-42'), ['TK7'])

    def test_invalid(self):
        """T-30 an invalid or empty-matching pattern is refused."""
        self.assertIn('compile', validate_pattern('(['))
        self.assertIn('empty', validate_pattern('a*'))
        self.assertIsNone(validate_pattern(DEFAULT_PATTERN, limit_s=1.0))

    def test_redos(self):
        """T-121 a catastrophic-backtracking pattern is refused."""
        self.assertIsNotNone(validate_pattern(r'(a+)+b', limit_s=0.05, hard_timeout_s=2.0))

    def test_examples(self):
        """T-122 an example builds a prefix pattern; #12 builds the issue preset."""
        p = pattern_from_example('ENG-42')
        self.assertEqual(Matcher([p]).find('ENG-7 OPS-8 XENG-9'), ['ENG-7'])
        self.assertEqual(pattern_from_example('#12'), ISSUE_PATTERN)
        self.assertEqual(Matcher([ISSUE_PATTERN]).find('fix #12 and a&#13'), ['#12'])
        self.assertEqual(Matcher([pattern_from_example('K42')]).find('K7 K42 K42.1 H264'), ['K42', 'K42.1'])
        with self.assertRaises(ValueError):
            pattern_from_example('not an id')


class TestInit(Env):
    def test_init_yes(self):
        """T-55 init --yes on a scratch home writes a valid config and the folders."""
        code, out = self.ledger('init', '--yes')
        self.assertEqual(code, 0)
        cfg = paths.load_config()
        self.assertTrue(cfg['initialized'])
        self.assertEqual(cfg['id_patterns'], [DEFAULT_PATTERN])
        self.assertFalse(cfg['commit_ids'])
        self.assertIn('python_version', out)

    def test_keeps_settings(self):
        """T-56 a second init keeps the machine id and settings unless a flag changes them."""
        self.ledger('init', '--yes', '--example', 'ENG-42', '--confirm-ids')
        a = paths.load_config()
        self.ledger('init', '--yes')
        b = paths.load_config()
        self.assertEqual((a['machine_id'], a['id_patterns'], a['commit_ids']), (b['machine_id'], b['id_patterns'], True))
        self.ledger('init', '--yes', '--no-commit-ids')
        self.assertFalse(paths.load_config()['commit_ids'])

    def test_machine_id(self):
        """T-57 the machine id is 16 hex chars and isn't the hostname."""
        import socket
        self.ledger('init', '--yes')
        mid = paths.load_config()['machine_id']
        self.assertRegex(mid, r'^[0-9a-f]{16}$')
        self.assertNotIn(mid, socket.gethostname())

    def test_init_ignore(self):
        """T-146 init --ignore adds folder globs to ignore_paths (repeatable, kept on a second init)."""
        self.ledger('init', '--yes', '--ignore', '~/work/client-*', '--ignore', '~/private')
        self.ledger('init', '--yes', '--ignore', '~/private')
        self.assertEqual(paths.load_config()['ignore_paths'], ['~/work/client-*', '~/private'])

    def test_refused_pattern_keeps_config(self):
        """T-30 T-122 a refused pattern leaves the config unchanged; commit ids need the person's own pattern."""
        self.ledger('init', '--yes')
        before = paths.load_config()
        code, out = self.ledger('init', '--yes', '--id-pattern', '([')
        self.assertEqual(code, 1)
        self.assertEqual(paths.load_config(), before)
        code, out = self.ledger('init', '--yes', '--confirm-ids')
        self.assertEqual(code, 1)
        self.assertFalse(paths.load_config()['commit_ids'])


if __name__ == '__main__':
    unittest.main()
