"""Attribution: tags, roles, commits, lead touches, time (REQ-05..REQ-09, REQ-30)."""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from unittest import mock

from helpers import T0, Env, Tx, agent, bash

from adapters.base import Message, Prompt, Session, ToolEvent, Transcript
from measured import gitrefs
from measured.attribute import attribute
from measured.ids import Matcher

M = Matcher([r'(?<![A-Za-z0-9_-])ABC-\d{1,6}(?![0-9A-Za-z_])'])


def run(transcripts, commits=None, commit_ids=True, cap=1800, window=1200):
    s = Session(session_id='s', transcripts=transcripts)
    return attribute(s, lambda t: (commits or {}).get(t.tid, []), M, cap, window, commit_ids)


def msgs(*pairs, model='m', effort='high'):
    return [Message(key=f'k{t}', time=T0 + t, model=model, effort=effort, fresh=n, cache_reads=0) for t, n in pairs]


class TestTags(unittest.TestCase):
    def test_first_prompt_two_ids(self):
        """T-17 a first-prompt tag with two IDs splits 50/50."""
        t = Transcript('main', msgs((1, 100), (2, 100)), [Prompt(T0, True, ['ABC-1, ABC-2'], None)])
        tasks, untied, tagged, _ = run([t])
        self.assertEqual((tasks['ABC-1']['fresh'], tasks['ABC-2']['fresh']), (100, 100))
        self.assertEqual(tagged, {'ids': ['ABC-1', 'ABC-2'], 'role': 'build'})

    def test_later_item_moves(self):
        """T-18 a later ITEM line moves the tokens after it to the new ID."""
        t = Transcript('main', msgs((1, 10), (5, 20)), [Prompt(T0, True, ['ABC-1'], None),
                                                         Prompt(T0 + 3, False, ['ABC-2'], None)])
        tasks, *_ = run([t])
        self.assertEqual((tasks['ABC-1']['fresh'], tasks['ABC-2']['fresh']), (10, 20))

    def test_later_item_untagged(self):
        """T-19 a later ITEM line in an untagged transcript tags only the rest."""
        t = Transcript('main', msgs((1, 10), (5, 20)), [Prompt(T0, True, [], None),
                                                         Prompt(T0 + 3, False, ['process:handoff'], None)])
        tasks, untied, tagged, _ = run([t], commit_ids=False)
        self.assertEqual(tasks['process:handoff']['fresh'], 20)
        self.assertEqual(untied, {'_untagged': 10})
        self.assertIn('from', tagged)

    def test_process(self):
        """T-20 ITEM: process:review counts under the process key."""
        t = Transcript('main', msgs((1, 10)), [Prompt(T0, True, ['process:review'], None)])
        tasks, *_ = run([t])
        self.assertEqual(list(tasks), ['process:review'])

    def test_roles(self):
        """T-21 ROLE in the first prompt and a later ROLE split the roles at that time."""
        t = Transcript('main', msgs((1, 10), (5, 20)), [Prompt(T0, True, ['ABC-1'], 'review'),
                                                         Prompt(T0 + 3, False, [], 'fix')])
        tasks, *_ = run([t])
        self.assertEqual(tasks['ABC-1']['by_role'], {'review': 10, 'fix': 20})

    def test_no_match(self):
        """T-22 text after ITEM: that matches no pattern ties nothing."""
        t = Transcript('main', msgs((1, 10)), [Prompt(T0, True, ['the export dialog'], None)])
        tasks, untied, tagged, _ = run([t], commit_ids=False)
        self.assertEqual((tasks, untied, tagged), ({}, {'_untagged': 10}, None))

    def test_bounds(self):
        """T-120 a process name of 33 chars or with spaces ties nothing; ROLE: boss is ignored; text after 200 chars
        isn't read."""
        from measured.ids import ids_from_items, tag_lines
        self.assertEqual(ids_from_items(['process:' + 'a' * 33], M), [])
        self.assertEqual(ids_from_items(['process:two words'], M), ['process:two'])
        self.assertEqual(ids_from_items(['process:Release-1'], M), ['process:release-1'])
        items, role = tag_lines('ITEM: ' + 'x' * 200 + ' ABC-9\nROLE: boss')
        self.assertEqual((ids_from_items(items, M), role), ([], None))
        self.assertEqual(M.find('y' * 199 + ' ABC-1'), [])


class TestCommits(unittest.TestCase):
    def test_own_commits(self):
        """T-24 T-27 commits by another transcript don't count; untied tokens go to _other, _after, _untagged."""
        t = Transcript('main', msgs((1, 10), (100, 20), (300, 40)), [Prompt(T0, True, [], None)],
                       [ToolEvent(T0 + 50, 'commit')])
        commits = {'main': [(T0 + 60, 'chore: tidy'), (T0 + 5000, 'ABC-9: made by another session')]}
        tasks, untied, _, n = run([t], commits)
        self.assertEqual((tasks, untied, n), ({}, {'_other': 10, '_after': 60}, 0))
        t.tools.append(ToolEvent(T0 + 4990, 'commit'))
        tasks, untied, _, n = run([t], commits)
        self.assertEqual(tasks['ABC-9']['by_role'], {'build': 60, 'lead': 10})  # its own commit now; the chore stretch touches it
        tasks, untied, _, _ = run([t], commits, commit_ids=False)
        self.assertEqual((tasks, untied), ({}, {'_untagged': 70}))
        t2 = Transcript('main', msgs((1, 10), (100, 20)), [Prompt(T0, True, [], None)], [ToolEvent(T0 + 50, 'commit')])
        tasks, untied, _, n = run([t2], {'main': [(T0 + 60, 'ABC-1: first')]})
        self.assertEqual((tasks['ABC-1']['by_role'], n), ({'build': 10, 'lead': 20}, 1))  # after it: a lead touch

    def test_lead_touches(self):
        """T-26 a message between a git push naming ABC-3 and a prompt with ITEM: ABC-4 splits between both, lead."""
        t = Transcript('main', msgs((1, 10), (20, 100), (40, 10)), [Prompt(T0, True, [], None)],
                       [ToolEvent(T0 + 10, 'command', head='git push origin feat/abc-3-login'),
                        ToolEvent(T0 + 30, 'agent', items=['ABC-4'])])
        tasks, untied, *_ = run([t])
        self.assertEqual(tasks['ABC-3']['by_role'], {'lead': 60})
        self.assertEqual(tasks['ABC-4']['by_role'], {'lead': 60})
        self.assertIsNone(tasks['ABC-3']['start'])

    def test_fake_adapter_equals_real(self):
        """T-85 the core gives the same shares from a fake adapter as from the Claude Code adapter."""
        import time
        from adapters.claude_code import ClaudeCode
        env = Env('setUp')
        env.setUp()
        try:
            tx = Tx().prompt(T0, 'ITEM: ABC-1\nROLE: fix').msg(T0 + 60, fresh=100, key='a').msg(T0 + 120, fresh=50, key='b')
            p = env.write_session(tx)
            real = ClaudeCode().read_session(p, 's', time.monotonic() + 30)
            fake = Session('s', [Transcript('main', [Message('a', T0 + 60, 'model-a', 'high', 100, 0),
                                                     Message('b', T0 + 120, 'model-a', 'high', 50, 0)],
                                            [Prompt(T0, True, ['ABC-1'], 'fix')], [], {'/work/proj'})])
            a = attribute(real, lambda t: [], M, 1800, 1200, False)
            b = attribute(fake, lambda t: [], M, 1800, 1200, False)
            self.assertEqual(a, b)
        finally:
            env.tearDown()


class TestTime(unittest.TestCase):
    def test_idle_cap(self):
        """T-31 T-34 gaps of 10, 40 and 20 minutes give 30 minutes active; the cap from the config changes it."""
        t = Transcript('main', msgs((0, 1), (600, 1), (3000, 1), (4200, 1)), [Prompt(T0, True, ['ABC-1'], None)])
        tasks, *_ = run([t])
        self.assertEqual(tasks['ABC-1']['active_s'], 1800)
        tasks, *_ = run([t], cap=3600)
        self.assertEqual(tasks['ABC-1']['active_s'], 4200)

    def test_lead_time(self):
        """T-32 a lead share adds active time but doesn't change start or end."""
        sub = Transcript('sub:x', msgs((0, 10), (100, 10)), [Prompt(T0, True, ['ABC-1'], None)])
        main = Transcript('main', msgs((500, 10), (700, 10)), [Prompt(T0 + 400, True, [], None)],
                          [ToolEvent(T0 + 800, 'agent', items=['ABC-1'])])
        base = attribute(Session('s', [sub]), lambda t: [], M, 1800, 1200, False)[0]['ABC-1']
        r = attribute(Session('s', [main, sub]), lambda t: [], M, 1800, 1200, False)[0]['ABC-1']
        self.assertEqual((r['start'], r['end']), (base['start'], base['end']))
        self.assertEqual(r['active_s'], base['active_s'] + 200)
        self.assertEqual(r['by_role'], {'build': 20, 'lead': 20})

    def test_out_of_order(self):
        """T-33 out-of-order times don't give negative time."""
        t = Transcript('main', [Message('a', T0 + 100, 'm', 'high', 1, 0), Message('b', T0 + 50, 'm', 'high', 1, 0)],
                       [Prompt(T0, True, ['ABC-1'], None)])
        tasks, *_ = run([t])
        self.assertGreaterEqual(tasks['ABC-1']['active_s'], 0)


class TestGitRefs(Env):
    def _git(self, *args, cwd):
        return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True,
                              env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@users.noreply.github.com',
                                   'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@users.noreply.github.com'})

    @unittest.skipUnless(shutil.which('git'), 'git needed')
    def test_reflog_split(self):
        """T-23 T-25 a scratch repo with two commits splits tokens before each; a pulled commit doesn't count."""
        import time
        repo = os.path.join(self.tmp, 'repo')
        os.makedirs(repo)
        self._git('init', '-q', '-b', 'main', cwd=repo)
        now = int(time.time())
        for i, subj in ((1, 'ABC-1: first'), (2, 'ABC-2: second')):
            with open(os.path.join(repo, f'f{i}'), 'w') as f:
                f.write(str(i))
            self._git('add', '.', cwd=repo)
            env_t = f'@{now + i * 100} +0000'
            subprocess.run(['git', 'commit', '-q', '-m', subj], cwd=repo, check=True,
                           env={**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@users.noreply.github.com',
                                'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@users.noreply.github.com',
                                'GIT_COMMITTER_DATE': env_t, 'GIT_AUTHOR_DATE': env_t})
        log = open(os.path.join(repo, '.git', 'logs', 'HEAD')).read()
        # A pulled commit: a reflog entry that isn't of type "commit".
        with open(os.path.join(repo, '.git', 'logs', 'HEAD'), 'a') as f:
            f.write(f'{"1" * 40} {"2" * 40} t <t@users.noreply.github.com> {now + 250} +0000\tpull: Fast-forward\n')
        self.assertIn('commit', log)
        g = gitrefs.find_gitdir(os.path.join(repo, 'sub', 'gone'))
        commits = gitrefs.local_commits(g[0], g[1], now, now + 1000)
        self.assertEqual([s for _, s in commits], ['ABC-1: first', 'ABC-2: second'])
        tx = Tx(cwd=repo).prompt(now, 'go')
        tx.msg(now + 50, fresh=10, tools=[bash('git commit -m x')])
        tx.msg(now + 150, fresh=20, tools=[bash('git add . && git commit -m y')])
        tx.msg(now + 240, fresh=40)
        p = self.write_session(tx)
        cfg = self.cfg(id_patterns=[M.patterns[0][0].pattern], commit_ids=True)
        e = self.record(p, cwd=repo, cfg=cfg)
        self.assertEqual(e['tasks']['ABC-1']['fresh'], 10)
        self.assertEqual(e['tasks']['ABC-2']['by_role'], {'build': 20, 'lead': 40})
        self.assertEqual(e['untied'], {})
        self.assertEqual(e['commits'], 2)

    def test_worktree_reader_no_subprocess(self):
        """T-123 the reflog reader parses a worktree's HEAD log and the common branch logs; no subprocess runs."""
        common = os.path.join(self.tmp, 'main', '.git')
        wt_git = os.path.join(common, 'worktrees', 'wt')
        wt = os.path.join(self.tmp, 'wt')
        os.makedirs(os.path.join(wt_git, 'logs'))
        os.makedirs(os.path.join(common, 'logs', 'refs', 'heads', 'feat'))
        os.makedirs(wt)
        with open(os.path.join(wt, '.git'), 'w') as f:
            f.write(f'gitdir: {wt_git}\n')
        with open(os.path.join(wt_git, 'commondir'), 'w') as f:
            f.write('../..\n')
        line = '{o} {n} t <t@users.noreply.github.com> {ts} +0000\t{m}\n'
        with open(os.path.join(wt_git, 'logs', 'HEAD'), 'w') as f:
            f.write(line.format(o='0' * 40, n='a' * 40, ts=T0 + 10, m='commit: ABC-5: in worktree'))
        with open(os.path.join(common, 'logs', 'refs', 'heads', 'feat', 'x'), 'w') as f:
            f.write(line.format(o='0' * 40, n='a' * 40, ts=T0 + 10, m='commit: ABC-5: in worktree'))
            f.write(line.format(o='a' * 40, n='b' * 40, ts=T0 + 20, m='commit (amend): ABC-6: amended'))
            f.write(line.format(o='b' * 40, n='c' * 40, ts=T0 + 30, m='rebase (pick): ABC-7: no'))
        with mock.patch('subprocess.run', side_effect=AssertionError('no subprocess')), \
                mock.patch('subprocess.Popen', side_effect=AssertionError('no subprocess')):
            g = gitrefs.find_gitdir(wt)
            self.assertEqual(os.path.normpath(g[1]), os.path.normpath(common))
            got = gitrefs.local_commits(g[0], g[1], T0, T0 + 100)
        self.assertEqual([s for _, s in got], ['ABC-5: in worktree', 'ABC-6: amended'])


if __name__ == '__main__':
    unittest.main()
