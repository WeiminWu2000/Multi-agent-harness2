import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mah2.dsstar.harness import initial

from regression_support import terminal_review as review_module


class FakeGateway:
    def __init__(self, directory, config, cap):
        self.cap, self.charged = cap, .01
    def close(self):
        pass


class KeepClient:
    def __init__(self, config, budget, ledger, stage):
        pass
    def complete(self, prompt, role=None):
        assert 'SECRET_HIDDEN_GRADE' not in prompt
        alias = re.search(r'insufficient evidence: (P\d+)', prompt).group(1)
        return json.dumps({'selected': alias, 'rationale': 'No measured difference.'})


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / 'parent'
        self.parent.mkdir()
        self.config = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/cycles10_no_knowledge.json').read_text())
        self.packet = {'task_inst': 'Filter the source rows.', 'output_fname': 'pred_results/out.csv',
                       'domain_knowledge': 'SECRET_HIDDEN_GRADE'}
        (self.parent / 'input_packet.json').write_text(json.dumps(self.packet))
        (self.parent / 'result.json').write_text('SECRET_HIDDEN_GRADE')
        for label, content in [('reference', 'id\n1\n'), ('candidate_a', 'id\n2\n'), ('candidate_b', 'id\n2\n')]:
            run = self.parent / 'optimization/round_1' / label
            (run / 'replay/pred_results').mkdir(parents=True)
            (run / 'replay/pred_results/out.csv').write_text(content)
            (run / 'submission.py').write_text('print(' + repr(content) + ')')
            (run / 'outcome.json').write_text(json.dumps({'runnable': True, 'replay': {'stdout': 'public'},
                                                          'official_success': 'SECRET_HIDDEN_GRADE'}))
            (run.parent / f'{label}_harness.json').write_text(json.dumps(initial()))
        (self.parent / 'optimization/successor').symlink_to('round_1/reference', target_is_directory=True)
        (self.parent / 'optimization/final_harness.json').write_text(json.dumps(initial()))

    def test_pool_ignores_grades_and_deduplicates_exact_program_outputs(self):
        pool = review_module.collect_pool(self.parent)
        self.assertEqual([x[0] for x in pool], ['previous', 'r1_candidate_a'])

    def test_pool_rejects_a_program_that_differs_from_its_replay_record(self):
        path = self.parent / 'optimization/round_1/reference/outcome.json'
        record = json.loads(path.read_text())
        record['program_sha256'] = '0' * 64
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'execution record'):
            review_module.collect_pool(self.parent)

    def test_commit_precedes_grading_costs_include_parent_and_inputs_stay_public(self):
        destination = self.root / 'review'
        before = review_module.identity(self.parent / 'optimization/successor')
        def grader(task, selected, out, config):
            self.assertTrue((destination / 'commit.json').exists())
            self.assertFalse((destination / 'result.json').exists())
            return {'status': 'graded', 'official_success': 0}
        with patch.object(review_module, 'Gateway', FakeGateway):
            result = review_module.review(self.parent, destination, self.config, 1, .2, .15,
                                          client_factory=KeepClient, grader=grader)
        self.assertAlmostEqual(result['total_cost_usd'], .21)
        self.assertEqual(result['selected_label'], 'previous')
        self.assertEqual(before, review_module.identity(self.parent / 'optimization/successor'))
        self.assertNotIn('domain_knowledge', json.loads((destination / 'input_packet.json').read_text()))
        self.assertEqual((self.parent / 'result.json').read_text(), 'SECRET_HIDDEN_GRADE')

    def test_invalid_choice_retains_incumbent(self):
        class InvalidClient(KeepClient):
            def complete(self, prompt, role=None):
                return '{"selected":"P999","rationale":"unsupported"}'
        with patch.object(review_module, 'Gateway', FakeGateway):
            result = review_module.review(self.parent, self.root / 'review', self.config, 1, .9, .15,
                                          client_factory=InvalidClient, grader=lambda *args: {})
        self.assertEqual(result['selected_label'], 'previous')
        evidence = json.loads((self.root / 'review/parent_evidence.json').read_text())
        self.assertAlmostEqual(evidence['extra_cap_usd'], .1)

    def test_malformed_selection_report_gets_bounded_correction(self):
        class CorrectingClient(KeepClient):
            def __init__(self,*args,**kwargs):self.calls=0
            def complete(self,prompt,role=None):
                self.calls+=1
                if self.calls==1:return '{"comparison":{"incumbent":"P1"}}'
                assert 'Wrong reply format' in prompt
                return super().complete(prompt,role)
        config={**self.config,'dsstar':{**self.config['dsstar'],'selection_requires_check':False}}
        with patch.object(review_module,'Gateway',FakeGateway):
            result=review_module.review(self.parent,self.root/'review',config,1,.2,.15,
                client_factory=CorrectingClient,grader=lambda *args:{})
        self.assertTrue(result['review_decision']['valid'])
        self.assertEqual(result['selected_label'],'previous')

    def test_changed_candidate_aborts_before_grading(self):
        parent = self.parent
        class MutatingClient(KeepClient):
            def complete(self, prompt, role=None):
                result = super().complete(prompt, role)
                (parent / 'optimization/round_1/reference/submission.py').write_text('changed')
                return result
        with patch.object(review_module, 'Gateway', FakeGateway), self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            review_module.review(self.parent, self.root / 'review', self.config, 1, .2, .15,
                                 client_factory=MutatingClient, grader=lambda *args: self.fail('Graded modified evidence'))
        self.assertFalse((self.root / 'review/commit.json').exists())

    def test_recursive_parent_pool_uses_committed_choice_without_reading_grade(self):
        review = self.root / 'review';review.mkdir()
        chosen = self.parent / 'optimization/round_1/candidate_a'
        (review / 'commit.json').write_text(json.dumps(dict(parent=str(self.parent), selected=str(chosen),
            selected_harness=initial(), identity=review_module.identity(chosen))))
        (review / 'result.json').write_text('SECRET_HIDDEN_GRADE')
        pool = review_module.collect_pool(review)
        self.assertEqual(pool[0][1], chosen.resolve())
        self.assertEqual(len(pool), 2)
        self.assertEqual(pool[1][1], (self.parent / 'optimization/round_1/reference').resolve())

    def test_continuation_carries_harness_and_archive_commits_before_grading(self):
        from regression_support import run_cycle_pilot
        parent = self.parent
        class FakeExperiment:
            def __init__(self, config, directory):
                self.root = directory;directory.mkdir(parents=True)
                self.config = config
            def run(self, method, packet, data, library, starting_harness, round_index, round_count, retained_candidates):
                assert set(packet) == {'task_inst','output_fname'}
                assert round_index == round_count == 3
                assert starting_harness == initial()
                assert self.config['allowance_usd'] == .1
                assert len(retained_candidates) == 1
                label, run, harness = retained_candidates[0]
                (self.root / label).symlink_to(run)
                (self.root / 'selected_harness.json').write_text(json.dumps(harness))
                (self.root / 'selection.json').write_text('{}')
                return dict(selected_stage=label, runnable=True)
        (parent / 'commit.json').write_text(json.dumps(dict(cycles_completed=2, valid_edits=5,total_edits=6)))
        (parent / 'data').mkdir()
        destination = self.root / 'continued'
        def grader(task, selected, out, config):
            self.assertTrue((destination / 'commit.json').exists())
            self.assertFalse((destination / 'result.json').exists())
            self.assertEqual(selected.resolve(), (parent / 'optimization/round_1/candidate_a').resolve())
            return dict(official_success=0)
        with patch.object(run_cycle_pilot, 'StudyGateway', FakeGateway):
            result = review_module.continue_round(parent, destination, self.config, 1, .2, .1,
                data=parent / 'data', grader=grader, experiment_class=FakeExperiment)
        self.assertAlmostEqual(result['total_cost_usd'], .21)
        self.assertEqual(result['cycles_completed'], 3)


if __name__ == '__main__':
    unittest.main()
