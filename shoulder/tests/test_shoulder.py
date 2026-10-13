import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('shoulder', Path(__file__).parents[1] / 'scripts/shoulder.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class ShoulderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)

    def test_manifests_and_private_state(self):
        unit = self.repo / 'apps/widget'
        unit.mkdir(parents=True)
        (unit / 'go.mod').write_text('module example.invalid/widget\n')
        self.assertEqual(s.units(self.repo), {'apps/widget': 'apps/widget/go.mod'})
        with patch.dict(os.environ, {'SHOULDER_STATE_DIR': str(self.repo / 'state')}):
            with self.assertRaises(ValueError):
                s.state_path(self.repo)

    def test_worktree_identity_and_unrelated_repo(self):
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Example', '-c',
                        'user.email=example@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'fixture'], check=True)
        work = self.root / 'work'
        subprocess.run(['git', '-C', str(self.repo), 'worktree', 'add', '-q', '-b', 'fixture', str(work)], check=True)
        other = self.root / 'other/repo'
        other.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(other)], check=True)
        self.assertEqual(s.identity(work), s.identity(self.repo))
        self.assertNotEqual(s.identity(other), s.identity(self.repo))
        sessions = self.root / 'sessions'
        sessions.mkdir()
        rows = [{'type': 'session_meta', 'payload': {'cwd': str(work)}}]
        for cwd, role in [(str(work), 'user'), (str(other), 'user'), (str(work), 'assistant')]:
            rows.append({'cwd': cwd, 'timestamp': '2026-01-07T12:00:00Z', 'type': 'response_item',
                         'payload': {'type': 'message', 'role': role, 'content': [{'type': 'input_text', 'text': 'I traced the failure.'}]}})
        (sessions / 'fixture.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        evidence = s.collect(self.repo, dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc),
                             dt.datetime(2026, 1, 9, 17, tzinfo=dt.timezone.utc), [sessions])
        self.assertEqual(len(evidence['evidence']), 1)
        self.assertEqual(evidence['evidence'][0]['line'], 2)

    def test_recent_evidence_and_malformed_messages(self):
        self.assertEqual(s.human_text({'type': 'response_item', 'payload': None}), '')
        roots = [self.root / 'old', self.root / 'new']
        for offset, root in enumerate(roots):
            root.mkdir()
            rows = [{'type': 'user', 'cwd': str(self.repo), 'timestamp': f'2026-01-0{6+offset}T12:00:00Z',
                     'message': {'role': 'user', 'content': 'human reasoning'}} for _ in range(200)]
            rows.append({'type': 'user', 'cwd': str(self.repo), 'timestamp': '2026-01-07T12:00:00Z',
                         'message': {'role': 'user', 'content': 'x' * 12001}})
            (root / 'fixture.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        result = s.collect(self.repo, dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc),
                           dt.datetime(2026, 1, 9, 17, tzinfo=dt.timezone.utc), roots)
        self.assertEqual(len(result['evidence']), 300)
        self.assertEqual(result['coverage']['skipped'], 2)
        self.assertTrue(result['coverage']['truncated'])
        self.assertTrue(result['evidence'][0]['source'].startswith(str(roots[1])))

    def test_reinit_preserves_self_rating(self):
        with patch.dict(os.environ, {"SHOULDER_STATE_DIR": str(self.root / "private")}):
            args = ["shoulder", "init", "--repo", str(self.repo)]
            with patch("sys.argv", args), patch("builtins.print"):
                s.main()
            path = s.state_path(self.repo)
            state = json.loads(path.read_text())
            state["ratings"]["."] = {"score": 3, "source": "self"}
            s.save(path, state)
            with patch("sys.argv", args), patch("builtins.print"):
                s.main()
            self.assertEqual(json.loads(path.read_text())["ratings"]["."]["score"], 3)

    def test_friday_cutoff_and_rating_protection(self):
        before = dt.datetime(2026, 1, 9, 16, tzinfo=dt.timezone.utc)
        self.assertEqual(str(s.period(before, 'UTC')[1].date()), '2026-01-02')
        self.assertEqual(str(s.period(before + dt.timedelta(hours=1), 'UTC')[1].date()), '2026-01-09')
        state = {'units': {'a': 'manifest', 'b': 'manifest'}, 'ratings': {'a': {'score': 2, 'source': 'self'}, 'b': {'score': 4, 'source': 'inferred'}}}
        evidence = [{'id': 'e1', 'source': 'fixture.jsonl', 'line': 1}]
        ratings = [{'unit': u, 'score': 3, 'confidence': .9, 'evidence_ids': ['e1'], 'reason': 'Synthetic reasoning', 'gaps': []} for u in ('a', 'b')]
        s.apply(state, {'ratings': ratings}, evidence)
        self.assertEqual(state['ratings']['a']['score'], 2)
        self.assertEqual(state['ratings']['b']['score'], 4)
        ratings[0]['evidence_ids'] = ['unknown']
        with self.assertRaises(ValueError):
            s.apply(state, {'ratings': ratings}, evidence)


if __name__ == '__main__':
    unittest.main()
