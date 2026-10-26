import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mah2.dsstar.harness import initial
from mah2.dsstar.optimizer import validate_hybrid_edit,Experiment
from mah2.dsstar.codex_editor import Client,command,usage
from mah2.dsstar.provider import Budget,BudgetExceeded,ProviderError

class CodexCoordination(unittest.TestCase):
    def test_ownership_and_composition(self):
        base=initial();proposal=copy.deepcopy(base)
        proposal['coordination'].update(version=2,coder_receives_question=True)
        ev=dict(base_harness=base,candidates={'b':{'harness':proposal}})
        validate_hybrid_edit('proposal_b',proposal,ev)
        validate_hybrid_edit('composer',proposal,ev)
        validate_hybrid_edit('composer',base,ev)
        with self.assertRaises(ValueError):validate_hybrid_edit('proposal_a',proposal,ev)
        unrelated=copy.deepcopy(proposal);unrelated['roles']['coder']='Solve the task'
        with self.assertRaises(ValueError):validate_hybrid_edit('proposal_b',unrelated,ev)
        invented=copy.deepcopy(proposal);invented['coordination']['verifier_diagnosis']=True
        with self.assertRaises(ValueError):validate_hybrid_edit('composer',invented,ev)

    def test_codex_call_limit_is_not_a_glm_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            client=Client({'codex_coordination':{'max_calls_per_round':0}},Budget(1),Path(d)/'ledger.jsonl')
            with self.assertRaises(BudgetExceeded):client.complete('test',role='proposal_b')
            with self.assertRaises(ProviderError):client.complete('test',role='coder')
            self.assertEqual(client.budget.charged,0)

    def test_only_coordination_stage_uses_codex_transport(self):
        c={'allowance_usd':1,'stage_shares':{'proposal_a':.5,'proposal_b':.5},'input_per_million':.37,'output_per_million':1.25,'codex_coordination':{'max_calls_per_round':4}}
        calls=[]
        def glm(config,budget,ledger,stage):calls.append(stage);return 'glm'
        with tempfile.TemporaryDirectory() as d:
            e=Experiment(c,Path(d)/'round',glm)
            self.assertEqual(e.client('proposal_a'),'glm')
            self.assertIsInstance(e.client('proposal_b'),Client)
        self.assertEqual(calls,['proposal_a'])

    def test_isolation_and_usage_do_not_claim_zero_codex_cost(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);auth=p/'auth';auth.touch();binary=p/'binary';binary.touch()
            args=command(p,dict(auth_file=str(auth),binary=str(binary),model='fixture',reasoning_effort='medium'))
            self.assertIn('--clearenv',args);self.assertIn('--ignore-user-config',args)
            self.assertNotIn(str(Path.cwd()),args)
            for feature in ('apps','plugins','shell_tool','multi_agent_v2'):self.assertIn(feature,args)
            out=p/'optimization/round_1/codex_proposal_b';out.mkdir(parents=True)
            (out/'usage.jsonl').write_text(json.dumps(dict(status='completed',usage={'input_tokens':100,'output_tokens':20}))+'\n')
            result=usage(p)
            self.assertEqual(result['calls'],1);self.assertEqual(result['input_tokens'],100)
            self.assertIsNone(result['cost_usd'])
