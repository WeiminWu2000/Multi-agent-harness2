import contextlib
import io
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests/regression_support'))
import report_cycle_pilot as report
import review_cycle_candidates as runner


class ReviewReportingTests(unittest.TestCase):
    def test_pooled_report_keeps_pending_and_development_separate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'results').mkdir()
            methods=['whole_team_harness2','mass_rhi']
            old=[dict(task=1,method=m,strict_success=int(m==methods[0]),total_upper_usd=.2) for m in methods]
            (root/'results/old.json').write_text(json.dumps(dict(complete=True,rows=old)))
            c=dict(tasks=[2],methods=methods,run_group='new',calibration_group='cal',comparison='test',combined_cohorts=[dict(label='development',report='results/old.json')])
            (root/'config.json').write_text(json.dumps(c))
            with patch.object(report,'ROOT',root),patch('sys.argv',['report','--config','config.json']),contextlib.redirect_stdout(io.StringIO()):report.main()
            result=json.loads((root/'results/combined20.json').read_text())
            self.assertFalse(result['complete'])
            self.assertEqual(result['cohorts']['new']['paired']['pending'],1)
            self.assertEqual(result['cohorts']['development']['paired']['harness_only'],1)
            self.assertEqual(result['pooled']['totals'][methods[0]]['successes'],1)
            self.assertEqual(result['pooled']['totals'][methods[0]]['planned'],2)

    def test_hybrid_report_keeps_codex_cost_unknown_and_third_arm_pending(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'results').mkdir()
            baseline=[dict(task=1,method=m,strict_success=1,total_upper_usd=.2) for m in ('whole_team_harness2','mass_rhi')]
            ref=root/'reference.json';ref.write_text(json.dumps({'rows':baseline}))
            c=dict(tasks=[1],methods=['codex_coordination_harness2'],run_group='new',calibration_group='cal',comparison='hybrid',reference_reports=[str(ref)],comparison_report='three.json')
            (root/'config.json').write_text(json.dumps(c))
            with patch.object(report,'ROOT',root),patch('sys.argv',['report','--config','config.json']),contextlib.redirect_stdout(io.StringIO()):report.main()
            result=json.loads((root/'results/three.json').read_text())
            self.assertFalse(result['complete']);self.assertEqual(len(result['rows']),3)
            self.assertEqual(result['totals']['codex_coordination_harness2']['completed'],0)
            row=result['rows'][-1]
            self.assertIsNone(row['strict_success']);self.assertIsNone(row['total_model_cost_usd'])
            self.assertIsNone(row['codex_usage']['cost_usd'])

    def test_component_gate_rejects_generation_changes(self):
        name='mah2/dsstar/optimizer.py'
        old='class Experiment:\n def select(self): return 1\n def run(self): return 2\n'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/name;p.parent.mkdir(parents=True)
            p.write_text(old.replace('return 1','return 3'))
            previous={name:hashlib.sha256(old.encode()).hexdigest()}
            current={name:hashlib.sha256(p.read_bytes()).hexdigest()}
            (root/'test').write_text(old)
            with patch.object(runner,'ROOT',root),patch.object(runner,'source_hashes',return_value=current):
                runner.selection_only_change(previous,'test')
                p.write_text(old.replace('return 2','return 4'))
                with self.assertRaisesRegex(RuntimeError,'Non-selection'):runner.selection_only_change(previous,'test')

    def test_lineage_accounting_includes_all_ancestors_and_rejects_cycles(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for group,parent,amount in [('base',None,.2),('review','base',.01),('third','review',.1)]:
                run=root/'runs'/group/'whole_team_harness2'/'1'
                (run/'api').mkdir(parents=True)
                (run/'api/ledger.jsonl').write_text(json.dumps(dict(charged_usd=amount,usage={'cost':amount}))+'\n')
                (run/'config.json').write_text(json.dumps(dict(candidate_parent_group=parent)))
            with patch.object(report,'ROOT',root):
                latest=root/'runs/third/whole_team_harness2/1'
                self.assertAlmostEqual(report.lineage_cost(latest)['total_upper_usd'],.31)
                self.assertAlmostEqual(report.cost(latest)['total_upper_usd'],.1)
                (root/'runs/base/whole_team_harness2/1/config.json').write_text('{"candidate_parent_group":"third"}')
                with self.assertRaisesRegex(ValueError,'Cyclic'):report.lineage_cost(latest)

    def test_calibration_attempt_path_is_not_overwritten_by_candidate_names(self):
        for attempt, name in ((0, 'fixture'), (2, 'fixture_attempt2')):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory() as d:
                root = Path(d); (root / 'private').mkdir()
                config = dict(run_group='review', calibration_group='cal', dsstar={},
                              review_calibration_attempt=attempt, budget={'calibration_cap': 1.5, 'total_cap': 31})
                class Box:
                    def __init__(self, directory, data, current_config):
                        self.root = directory; self.root.mkdir()
                    def run(self, program, filename, timeout):
                        (self.root / 'pred_results').mkdir()
                        (self.root / 'pred_results/join.csv').write_text('id,value,label\n1,10,A\n2,20,B\n')
                        return {'returncode': 0}
                def fake_review(parent, destination, current_config, task, parent_cost, cap, *, data, grader):
                    self.assertEqual(destination.name, name)
                    destination.mkdir(parents=True)
                    (destination / 'commit.json').write_text('{}')
                    grade = grader(task, parent / 'optimization/round_1/candidate_a', destination / 'evaluation', current_config)
                    return dict(grade=grade, selected_label='r1_candidate_a', review_cost_usd=0,
                                review_decision={'replacement_probe': 'selector_0'})
                with patch.object(runner, 'ROOT', root), patch.object(runner, 'Sandbox', Box), \
                     patch.object(runner, 'review', fake_review), patch.object(runner, 'total_cost', return_value=0), \
                     patch.object(runner, 'source_hashes', return_value={}), contextlib.redirect_stdout(io.StringIO()):
                    runner.calibrate(config)
                self.assertTrue((root / 'runs/cal/whole_team_harness2' / name / 'result.json').exists())
                self.assertFalse((root / 'runs/cal/whole_team_harness2/candidate_a').exists())

    def test_method_cost_includes_generation_without_double_counting_study_spending(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'results').mkdir()
            config = dict(tasks=[1], methods=['whole_team_harness2'], run_group='review',
                          candidate_parent_group='parent', retained_methods={'mass_rhi': 'mass'},
                          calibration_group='cal', shared_run_groups=['parent', 'review', 'mass'],
                          shared_calibration_groups=[], comparison='cached review')
            (root / 'config.json').write_text(json.dumps(config))
            for group, method, amount in [('parent', 'whole_team_harness2', .2),
                                          ('review', 'whole_team_harness2', .01),
                                          ('mass', 'mass_rhi', .3)]:
                run = root / 'runs' / group / method / '1'
                (run / 'api').mkdir(parents=True)
                (run / 'api/ledger.jsonl').write_text(json.dumps(dict(charged_usd=amount, usage={'cost': amount}, status='returned')) + '\n')
                (run / 'result.json').write_text(json.dumps(dict(status='completed', runnable=True,
                                                                grade={'status': 'graded', 'official_success': 1})))
            with patch.object(report, 'ROOT', root), patch.object(sys, 'argv', ['report', '--config', 'config.json']), contextlib.redirect_stdout(io.StringIO()):
                report.main()
            result = json.loads((root / 'results/review.json').read_text())
            self.assertAlmostEqual(result['totals']['whole_team_harness2']['total_upper_usd'], .21)
            self.assertAlmostEqual(result['cumulative_study_upper_usd'], .51)
            own = next(r for r in result['rows'] if r['method'] == 'whole_team_harness2')
            self.assertAlmostEqual(own['inherited_generation_upper_usd'], .2)
            self.assertAlmostEqual(own['new_review_upper_usd'], .01)


if __name__ == '__main__':
    unittest.main()
