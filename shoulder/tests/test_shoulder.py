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

    def test_evaluator_requires_structured_rating_output(self):
        rating = {'unit': '.', 'score': 2, 'confidence': .8, 'evidence_ids': ['e1'],
                  'reason': 'handler.py:1 verifies the flow', 'gaps': []}
        def run(command, **kwargs):
            schema = json.loads(Path(command[command.index('--output-schema') + 1]).read_text())
            self.assertEqual(schema['required'], ['ratings'])
            item = schema['properties']['ratings']['items']
            self.assertFalse(item['additionalProperties'])
            self.assertEqual(set(item['required']), set(rating))
            self.assertEqual(item['properties']['score']['maximum'], 5)
            self.assertEqual(item['properties']['evidence_ids']['minItems'], 1)
            self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
            Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps({'ratings': [rating]}))
        with patch.object(s.subprocess, 'run', side_effect=run):
            result = s.evaluate([], {'units': {'.': 'root'}, 'ratings': {}}, 'model', self.repo)
        self.assertEqual(result, {'ratings': [rating]})

    def test_calibration_questions_are_grounded_and_bounded(self):
        (self.repo / 'handler.py').write_text('def handle(value):\n    return value\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'handler.py'], check=True)
        questions = s.interview_questions(self.repo, '.')
        self.assertEqual([q['id'] for q in questions], ['flow', 'boundaries', 'failure'])
        self.assertTrue(all('handler.py:1' in q['question'] for q in questions))

    def test_calibration_rejects_empty_source_and_checkout_answers(self):
        with self.assertRaises(ValueError):
            s.interview_questions(self.repo, '.')
        file = self.repo / 'answers.json'
        file.write_text('{}')
        with self.assertRaises(ValueError):
            s.interview_answers(file, self.repo, self.root / 'private', [])

    def test_calibration_persists_private_evidence_and_limits_unit(self):
        file = self.root / 'answers.json'
        file.write_text(json.dumps({'answers': [{'id': 'flow', 'answer': 'Input returns unchanged.'}]}))
        questions = [{'id': 'flow', 'question': 'Trace handler.py:1.'}]
        evidence = s.interview_answers(file, self.repo, self.root / 'private', questions)
        self.assertEqual(evidence[0]['line'], 1)
        self.assertEqual(Path(evidence[0]['source']).stat().st_mode & 0o777, 0o600)
        state = {'units': {'.': 'root', 'other': 'other'}, 'ratings': {}}
        rating = {'unit': 'other', 'score': 2, 'confidence': .9, 'evidence_ids': ['e1'], 'reason': 'source:1', 'gaps': []}
        with patch.object(s, 'evaluate', return_value={'ratings': [rating]}):
            with self.assertRaises(ValueError):
                s.assess_interview(state, '.', evidence, 'model', self.repo)
        self.assertEqual(state['ratings'], {})

    def test_calibration_rejects_invalid_answer_shapes(self):
        file = self.root / 'answers.json'
        question = [{'id': 'flow', 'question': 'Trace source.py:1.'}]
        for rows in ([], [{'id': 'flow', 'answer': ' '}], [{'id': 'other', 'answer': 'text'}],
                     [{'id': 'flow', 'answer': 'text'}] * 2):
            file.write_text(json.dumps({'answers': rows}))
            with self.assertRaises(ValueError):
                s.interview_answers(file, self.repo, self.root / 'private', question)

    def test_calibration_cli_errors_and_existing_level_preparation(self):
        (self.repo / 'handler.py').write_text('def handle(value):\n    return value\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'handler.py'], check=True)
        with patch.dict(os.environ, {'SHOULDER_STATE_DIR': str(self.root / 'private')}):
            base = ['shoulder', 'calibrate', '--repo', str(self.repo)]
            for extra in ([], ['--unit', 'missing']):
                with patch('sys.argv', base + extra), patch('sys.stderr'):
                    with self.assertRaises(SystemExit):
                        s.main()
            state = {'identity': s.identity(self.repo), 'units': {'.': 'root'},
                     'ratings': {'.': {'score': 3, 'source': 'self'}}, 'weeks': {}}
            s.save(s.state_path(self.repo), state)
            with patch('sys.argv', base + ['--unit', '.']), patch('builtins.print') as output:
                s.main()
                self.assertFalse(json.loads(output.call_args.args[0])['unassessed'])
            answers = self.root / 'bad.json'
            answers.write_text('not JSON')
            with patch('sys.argv', base + ['--unit', '.', '--answers-file', str(answers)]):
                with self.assertRaisesRegex(SystemExit, 'Calibration failed'):
                    s.main()

    def test_calibration_skips_test_source(self):
        (self.repo / 'test_handler.py').write_text('def test_handler(): pass\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'test_handler.py'], check=True)
        with self.assertRaisesRegex(ValueError, 'production source'):
            s.interview_questions(self.repo, '.')

    def test_single_interview_cannot_award_expert_level(self):
        evidence = [{'id': 'e1', 'source': 'private.jsonl', 'line': 1}]
        rating = {'unit': '.', 'score': 5, 'confidence': .9, 'evidence_ids': ['e1'],
                  'reason': 'source.py:1', 'gaps': []}
        for old in ({}, {'score': 3, 'source': 'inferred'}, {'score': 5, 'source': 'inferred'}):
            state = {'units': {'.': 'root'}, 'ratings': {'.': old} if old else {}}
            with patch.object(s, 'evaluate', return_value={'ratings': [rating]}):
                result = s.assess_interview(state, '.', evidence, 'model', self.repo)
            self.assertFalse(result['persisted'])
            self.assertEqual(state['ratings'].get('.', {}), old)
            self.assertIn('breadth', result['assessment_note'])

    def test_calibration_flags_self_protection_weak_evidence_and_same_level(self):
        evidence = [{'id': 'e1', 'source': 'private.jsonl', 'line': 1}]
        state = {'units': {'.': 'root'}, 'ratings': {'.': {'score': 2, 'source': 'self'}}}
        rating = {'unit': '.', 'score': 3, 'confidence': .9, 'evidence_ids': ['e1'], 'reason': 'source:1', 'gaps': []}
        with patch.object(s, 'evaluate', return_value={'ratings': [rating]}):
            result = s.assess_interview(state, '.', evidence, 'model', self.repo)
        self.assertTrue(result['self_rating_protected'])
        self.assertFalse(result['unassessed'])
        self.assertFalse(result['persisted'])
        state['ratings'] = {'.': {'score': 3, 'source': 'inferred'}}
        with patch.object(s, 'evaluate', return_value={'ratings': [rating]}):
            result = s.assess_interview(state, '.', evidence, 'model', self.repo)
        self.assertTrue(result['persisted'])
        self.assertFalse(result['level_increased'])
        rating['confidence'] = .5
        with patch.object(s, 'evaluate', return_value={'ratings': [rating]}):
            result = s.assess_interview(state, '.', evidence, 'model', self.repo)
        self.assertFalse(result['unassessed'])
        state['ratings'] = {}
        with patch.object(s, 'evaluate', return_value={'ratings': [rating]}):
            result = s.assess_interview(state, '.', evidence, 'model', self.repo)
        self.assertTrue(result['unassessed'])

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
