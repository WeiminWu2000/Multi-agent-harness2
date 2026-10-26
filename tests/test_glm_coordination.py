import unittest
from unittest.mock import patch
from mah2.dsstar.provider import Client,CoordinationClient,BudgetExceeded

class GLMCoordinationTests(unittest.TestCase):
    def test_prefix_and_call_cap(self):
        client=object.__new__(CoordinationClient)
        client.calls=0
        with patch.object(Client,'complete',return_value='{}') as complete:
            for _ in range(4):client.complete('evidence',role='proposal_b')
            with self.assertRaises(BudgetExceeded):client.complete('evidence',role='proposal_b')
            self.assertEqual(complete.call_count,4)
            self.assertIn('Do not solve the scientific task',complete.call_args.args[0])
            self.assertTrue(complete.call_args.args[0].endswith('evidence'))

class FixtureFallbackTests(unittest.TestCase):
    def test_rejections_must_preserve_base_and_have_known_reason(self):
        import json,tempfile,sys
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests/regression_support'))
        from submit_cycle_pilot import safe_fixture_rejections
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=root/'optimization/round_1';d.mkdir(parents=True)
            base={'roles':{'coder':''},'coordination':{'version':1}}
            (d/'reference_harness.json').write_text(json.dumps(base))
            for stage in ('proposal_a','proposal_b','composer'):
                (d/(stage+'_decision.json')).write_text(json.dumps({'valid':True,'harness':base}))
            f=d/'composer_decision.json'
            rejected={'valid':False,'error':"Harness changes must cite this stage's executed structured public check as public_check_probe",'harness':base}
            f.write_text(json.dumps(rejected));self.assertTrue(safe_fixture_rejections(root,1))
            rejected['harness']={'different':True};f.write_text(json.dumps(rejected));self.assertFalse(safe_fixture_rejections(root,1))
            rejected['harness']=base;rejected['error']='Unexpected runtime fault';f.write_text(json.dumps(rejected));self.assertFalse(safe_fixture_rejections(root,1))
