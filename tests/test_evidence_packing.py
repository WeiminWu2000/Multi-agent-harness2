import copy
import json
import unittest

from mah2.dsstar.harness import initial
from mah2.dsstar.optimizer import editor_evidence


class EvidencePackingTests(unittest.TestCase):
    def packet(self, summary):
        runs = {}
        for name in ('reference', 'candidate_a', 'candidate_b'):
            runs[name] = {'trace': [dict(id=f'e{i:04d}', kind='final_replay',
                                         public_artifact_summary=copy.deepcopy(summary)) for i in range(6)],
                          'outcome': {'runnable': True}}
        return dict(task={'task_inst': 'Analyze the public input.'}, base_harness=initial(),
                    library=[], runs=runs)

    def assert_preserved(self, original, packed):
        self.assertEqual(packed['task'], original['task'])
        self.assertEqual(packed['base_harness'], original['base_harness'])
        for name in original['runs']:
            self.assertEqual([e['id'] for e in packed['runs'][name]['trace']],
                             [e['id'] for e in original['runs'][name]['trace']])

    def test_repeated_structured_summaries_are_shared_without_losing_columns_or_values(self):
        summary = dict(path='pred_results/out.csv', exists=True,
                       columns=[f'measurement_{i}' for i in range(80)],
                       preview=[[str(i / 7) for i in range(80)]])
        original = self.packet(summary)
        unchanged = copy.deepcopy(original)
        packed = editor_evidence(original, 8000)
        self.assertLessEqual(len(json.dumps(packed, ensure_ascii=False).encode()), 8000)
        self.assert_preserved(original, packed)
        self.assertEqual(original, unchanged)
        self.assertEqual(list(packed['public_artifact_summaries'].values()), [summary])
        for run in packed['runs'].values():
            for event in run['trace']:
                ref = event['public_artifact_summary']['public_summary_ref']
                self.assertEqual(packed['public_artifact_summaries'][ref], summary)

    def test_text_previews_are_bounded_while_full_events_remain_addressable(self):
        original = self.packet(dict(path='pred_results/out.txt', exists=True, preview='x' * 4000))
        packed = editor_evidence(original, 8000)
        self.assertLessEqual(len(json.dumps(packed, ensure_ascii=False).encode()), 8000)
        self.assert_preserved(original, packed)
        self.assertTrue(packed['evidence_view']['full_trace_events_available'])
        self.assertIn('EXCERPT', json.dumps(packed))

    def test_wide_reflection_keeps_selected_replay_with_digest(self):
        from mah2.dsstar.optimizer import reflection_evidence
        original=self.packet(dict(columns=[f'column_{i}' for i in range(100)],preview=[[str(i) for i in range(100)] for _ in range(3)]))
        original.update(adopted_harness=initial(),selected_stage='reference',composition={'evidence':[f'reference:e{i:04d}' for i in range(6)]})
        unchanged=copy.deepcopy(original)
        packed=reflection_evidence(original)
        self.assertLessEqual(len(json.dumps(packed).encode()),16000)
        self.assertEqual(original,unchanged)
        self.assertEqual(packed['selected_events'][0]['id'],'e0000')
        summary=packed['selected_events'][0]['public_artifact_summary']
        self.assertEqual(summary['column_count'],100)
        self.assertEqual(len(summary['summary_sha256']),64)


if __name__ == '__main__':
    unittest.main()
