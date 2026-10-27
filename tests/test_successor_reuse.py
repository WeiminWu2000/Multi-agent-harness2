import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from mah2.dsstar.harness import initial
from mah2.dsstar.optimizer import Experiment

class SuccessorReuseTests(unittest.TestCase):
    def fixture(self, root, enabled=True, runnable=True):
        exp=Experiment({'reuse_identical_successor':enabled},root/'round_1')
        base=initial();role=copy.deepcopy(base);role['roles']['coder']='Check joins.'
        coord=copy.deepcopy(base);coord['coordination']['coder_receives_question']=True;coord['coordination']['version']=2
        for name,h in [('reference',base),('candidate_a',role),('candidate_b',coord)]:
            p=exp.root/name;p.mkdir();program=b'print("fixture")\n';(p/'submission.py').write_bytes(program)
            (p/'outcome.json').write_text(json.dumps({'runnable':runnable,'program_sha256':hashlib.sha256(program).hexdigest()}))
        exp.run_team=Mock(return_value={'runnable':True,'fresh':True})
        return exp,[('reference',base),('candidate_a',role),('candidate_b',coord)]

    def test_each_exact_match_reuses_without_execution(self):
        for index in range(3):
            with self.subTest(index=index),tempfile.TemporaryDirectory() as tmp:
                exp,choices=self.fixture(Path(tmp));out=exp.execute_successor(copy.deepcopy(choices[index][1]),{},Path(tmp),choices)
                exp.run_team.assert_not_called();self.assertTrue(out['runnable'])
                self.assertEqual((exp.root/'successor').resolve(),exp.root/choices[index][0])
                receipt=json.loads((exp.root/'successor_reuse.json').read_text())
                self.assertFalse(receipt['executed']);self.assertEqual(receipt['source_stage'],choices[index][0])

    def test_combination_is_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp,choices=self.fixture(Path(tmp));combined=copy.deepcopy(choices[1][1]);combined['coordination']=choices[2][1]['coordination']
            self.assertTrue(exp.execute_successor(combined,{},Path(tmp),choices)['fresh'])
            exp.run_team.assert_called_once();self.assertFalse((exp.root/'successor_reuse.json').exists())

    def test_historical_mode_still_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp,choices=self.fixture(Path(tmp),enabled=False)
            exp.execute_successor(choices[0][1],{},Path(tmp),choices);exp.run_team.assert_called_once()

    def test_failed_or_modified_program_is_not_reused(self):
        for bad_hash in [False,True]:
            with self.subTest(bad_hash=bad_hash),tempfile.TemporaryDirectory() as tmp:
                exp,choices=self.fixture(Path(tmp),runnable=bad_hash)
                if bad_hash:(exp.root/'reference/submission.py').write_text('changed')
                exp.execute_successor(choices[0][1],{},Path(tmp),choices);exp.run_team.assert_called_once()

    def test_recursive_loop_runs_three_teams_and_avoids_duplicate_choices(self):
        from mah2.dsstar.recursion import run_recursive
        class OfflineExperiment(Experiment):
            executions=[]
            pools=[]
            def run_team(self,stage,harness,packet,data):
                self.executions.append((self.root.name,stage))
                p=self.root/stage;p.mkdir();(p/'trace.jsonl').write_text('')
                code=('print('+repr(self.root.name+stage)+')\n').encode()
                (p/'submission.py').write_bytes(code)
                out={'runnable':True,'program_sha256':hashlib.sha256(code).hexdigest()}
                (p/'outcome.json').write_text(json.dumps(out))
                if stage=='reference':(self.root/'reference_harness.json').write_text(json.dumps(harness))
                return out
            def edit(self,stage,prompt,ev,scope):
                h=copy.deepcopy(ev['base_harness']);record={'valid':True,'harness':h}
                (self.root/(stage+'_decision.json')).write_text(json.dumps(record))
                return h,record
            def select(self,packet,choices,fallback):
                self.pools.append(list(choices))
                return 'reference',choices['reference'],json.loads((self.root/'reference/outcome.json').read_text())
            def reflect(self,*args):pass
        with tempfile.TemporaryDirectory() as tmp:
            c={'allowance_usd':1,'reuse_identical_successor':True,'public_selection':True,'retain_candidate_archive':True,'runnable_fallback':True}
            run_recursive(c,Path(tmp)/'optimization','whole_team',{'task_inst':'fixture'},Path(tmp),[],2,OfflineExperiment)
            self.assertEqual(len(OfflineExperiment.executions),6)
            self.assertTrue(all(stage!='successor' for _,stage in OfflineExperiment.executions))
            self.assertTrue(all('successor' not in pool for pool in OfflineExperiment.pools))
            self.assertEqual(sum(x.startswith('archive_') for x in OfflineExperiment.pools[1]),3)
