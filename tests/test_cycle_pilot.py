import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from mah2.dsstar.recursion import run_recursive
from mah2.dsstar.harness import initial
from mah2 import mass_rhi
ROOT=Path(__file__).resolve().parents[1]

class Cycles(unittest.TestCase):
    def test_output_contract_replacement_requires_equivalence_and_measured_fidelity(self):
        from mah2.public_evidence import supports_replacement
        row=dict(incumbent='P1',candidate='P2',basis='public_output_contract',criterion='changed source values',
                 protocol='compare source strings after equal scientific sets verified',direction='min',
                 incumbent_value=2,candidate_value=0,source_paths=['input.csv'],scientific_equivalence=True,
                 incumbent_rows=10,candidate_rows=10)
        probe=dict(returncode=0,comparison=row)
        self.assertFalse(supports_replacement(probe,'P1','P2'))
        self.assertTrue(supports_replacement(probe,'P1','P2',True))
        for change in ({'scientific_equivalence':False},{'candidate_rows':1},{'candidate_rows':0},
                       {'source_paths':['../private.csv']},{'candidate_value':2},{'incumbent_value':11},
                       {'candidate_value':-1},{'candidate_value':False}):
            self.assertFalse(supports_replacement(dict(probe,comparison={**row,**change}),'P1','P2',True))

    def test_probe_json_accepts_indented_final_object_after_logs(self):
        from mah2.public_evidence import final_json_object
        record={'check':{'observations':{'values':[1,2],'note':'braces { in a string }'}}}
        for text in (json.dumps(record),json.dumps(record,indent=2),'progress\n'+json.dumps(record,indent=2)+'\n\n','{"earlier":true}\n'+json.dumps(record,indent=2)):
            self.assertEqual(final_json_object(text),record)
        for text in ('',json.dumps(record,indent=2)+'\nlater log','{"check": {"observations": {}}', '[{"check": {}}]'):
            self.assertIsNone(final_json_object(text))

    def test_dispatcher_stop_request_prevents_new_claims(self):
        from regression_support import dispatch_cycle_pilot as dispatch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);claims=root/'private/unit_dispatch';claims.mkdir(parents=True)
            (claims/'stop_new_work.json').write_text('{"reason":"revision ready"}')
            (root/'config.json').write_text(json.dumps(dict(run_group='unit',concurrency=1,tasks=[1],methods=['whole_team_harness2'])))
            with patch.object(dispatch,'ROOT',root),patch.dict(dispatch.os.environ,{'SLURM_PROCID':'0'}),patch('sys.argv',['dispatch_cycle_pilot.py','--config','config.json']),patch.object(dispatch.os,'sched_getaffinity',return_value={0,1,2,3}),patch.object(dispatch.os,'sched_setaffinity'),patch.object(dispatch.subprocess,'run') as run:
                dispatch.main()
            run.assert_not_called();self.assertFalse((claims/'0.log').exists())

    def test_dispatcher_separates_shared_masks_and_preserves_four_cpu_rank_masks(self):
        from regression_support.dispatch_cycle_pilot import worker_cpu_mask
        shared=set(range(4))|set(range(32,36))
        first=worker_cpu_mask(shared,0,2);second=worker_cpu_mask(shared,1,2)
        self.assertEqual(first,list(range(4)));self.assertEqual(second,list(range(32,36)))
        self.assertTrue(set(first).isdisjoint(second))
        self.assertEqual(worker_cpu_mask({4,5,6,7},1,2),[4,5,6,7])
        with self.assertRaises(RuntimeError):worker_cpu_mask({0,1,2},0,2)

    def test_three_rounds_retain_all_runnable_candidates(self):
        sizes=[];caps=[]
        class Experiment:
            def __init__(self,c,path):self.path=path;path.mkdir();caps.append(c['allowance_usd'])
            def run(self,method,packet,data,library,starting_harness,round_index,round_count,retained_candidates):
                sizes.append(len(retained_candidates))
                for label,fname in [('reference','reference_harness.json'),('candidate_a','proposal_a_decision.json'),('candidate_b','proposal_b_decision.json'),('successor','composer_decision.json')]:
                    stage=self.path/label;stage.mkdir()
                    (stage/'outcome.json').write_text(json.dumps({'runnable':label!='candidate_b'}))
                    (self.path/fname).write_text(json.dumps(starting_harness if label=='reference' else {'harness':starting_harness}))
                (self.path/'selected_harness.json').write_text(json.dumps(starting_harness))
                return {'runnable':True,'selected_stage':'reference'}
        with tempfile.TemporaryDirectory() as d:
            result=run_recursive({'allowance_usd':1,'retain_candidate_archive':True,'public_selection':True,'runnable_fallback':True},Path(d)/'run','whole_team',{},Path(d),[],3,Experiment)
            self.assertTrue((Path(d)/'run/successor/outcome.json').exists())
        self.assertEqual(sizes,[0,3,6]);self.assertAlmostEqual(sum(caps),1)
        self.assertEqual(result['selected_round'],3)

    def test_two_rounds_carry_harness_and_split_total_budget(self):
        starts=[];caps=[]
        class Experiment:
            def __init__(self,c,path):self.path=path;path.mkdir();caps.append(c['allowance_usd'])
            def run(self,method,packet,data,library,starting_harness,round_index,round_count):
                starts.append(copy.deepcopy(starting_harness));h=copy.deepcopy(starting_harness)
                h['roles']['coder']=f'round {round_index}'
                (self.path/'composer_decision.json').write_text(json.dumps({'harness':h}))
                return {'runnable':True}
        with tempfile.TemporaryDirectory() as d:
            run_recursive({'allowance_usd':1},Path(d)/'run','whole_team',{},Path(d),[],2,Experiment)
        self.assertEqual(caps,[.5,.5]);self.assertEqual(starts[0],initial())
        self.assertEqual(starts[1]['roles']['coder'],'round 1')
    def test_carry_forward_releases_unused_money_but_reserves_future_stages(self):
        from mah2.dsstar.optimizer import Experiment
        c=json.loads((ROOT/'tests/fixtures/cycles10.json').read_text())['dsstar']
        c.update(allowance_usd=.5,input_per_million=.37,output_per_million=1.25,budget_policy='carry_forward')
        class Client:
            def __init__(self,c,b,ledger,stage):self.budget=b
        with tempfile.TemporaryDirectory() as d:
            e=Experiment(c,Path(d)/'round',Client)
            reference=e.client('reference');self.assertAlmostEqual(reference.budget.cap,.1)
            reference.budget.charged=.02
            proposal=e.client('proposal_a');self.assertAlmostEqual(proposal.budget.cap,.105)
            proposal.budget.charged=.03
            other=e.client('proposal_b');self.assertAlmostEqual(other.budget.cap,.1)
            other.budget.charged=.025
            # Simulate consuming every released allowance: future shares remain.
            candidate=e.client('candidate_a');self.assertAlmostEqual(candidate.budget.cap,.175)
            candidate.budget.charged=.175
            self.assertAlmostEqual(e.client('candidate_b').budget.cap,.1)
    def test_large_editor_prompt_keeps_full_output_with_transferred_funds(self):
        from mah2.gateway import Gateway
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'choices':[{'message':{'content':'{}'}}],'usage':{'cost':.003}}
        class Session:
            def post(self,*args,**kwargs):self.payload=kwargs['json'];return Response()
        c=json.loads((ROOT/'tests/fixtures/cycles10.json').read_text())
        with tempfile.TemporaryDirectory() as d:
            session=Session();g=Gateway(d,c,1.,session)
            g.charged=.02;g.set_stage('round_1/proposal_a',.105)
            g.request({'messages':[{'role':'user','content':'x'*60000}],'max_tokens':8192})
            self.assertEqual(session.payload['max_tokens'],8192)
            self.assertLessEqual(g.calls[0]['reserved_usd'],.105)
            self.assertAlmostEqual(g.charged,.023)
    def test_fixed_budget_remains_available_for_historical_reproduction(self):
        from mah2.dsstar.optimizer import Experiment
        c=json.loads((ROOT/'tests/fixtures/cycles10.json').read_text())['dsstar']
        c.update(allowance_usd=.5,input_per_million=.37,output_per_million=1.25)
        class Client:
            def __init__(self,c,b,ledger,stage):self.budget=b
        with tempfile.TemporaryDirectory() as d:
            e=Experiment(c,Path(d)/'round',Client)
            e.client('reference').budget.charged=.02
            self.assertAlmostEqual(e.client('proposal_a').budget.cap,.025)
    def test_released_mass_driver_executes_two_updates_and_final_selection(self):
        config=json.loads((ROOT/'tests/fixtures/cycles10.json').read_text())
        class Gateway:
            charged=0.;stages=[]
            def set_stage(self,name,cap):
                assert self.charged+cap<=1.+1e-9
                self.stages.append((name,cap))
            def request(self,payload):
                self.charged+=.001
                text=' '.join(m['content'] for m in payload['messages'])
                if 'improved_multi_agent_design' in text and 'comparing **two**' not in text:
                    reply={'improved_multi_agent_design':'Create an agent team with following agent candidates to solve this problem:\nA data analyst writes the program and an auditor checks it.'}
                else:reply={'winner':'tie','rationale':'Both fixture outputs are identical.'}
                return {'choices':[{'message':{'content':json.dumps(reply)}}],'usage':{'cost':.001}}
        def episode(g,w,p,data,directory,c,prompt_override):
            directory.mkdir(parents=True);(directory/'work').mkdir()
            (directory/'work/submission.py').write_text('print("fixture")')
            (directory/'work/logs.txt').write_text('Fixture executed.')
            result={'agent':{'returncode':0},'runnable':True}
            (directory/'outcome.json').write_text(json.dumps(result));return result
        for policy in ('fixed','carry_forward'):
            config['mass_rhi']['budget_policy']=policy
            with tempfile.TemporaryDirectory() as d,patch('mah2.mass_rhi.episode',episode):
                g=Gateway();g.stages=[];result=mass_rhi.run(g,config,{'task_inst':'Write a program','output_fname':'pred_results/out.csv'},Path(d),Path(d)/'run',5,1.)
                self.assertEqual(result['cycles_completed'],2);self.assertEqual(result['team_executions'],4)
                self.assertTrue(result['selected'].endswith('t1005_bare'))
                self.assertEqual([n for n,c in g.stages if n.startswith('rhi')],['rhi_v0','rhi_v1','rhi_v2'])
                if policy=='fixed':self.assertAlmostEqual(sum(c for n,c in g.stages),1.)
                else:self.assertAlmostEqual(g.stages[1][1],.36)
if __name__=='__main__':unittest.main()

class Reliability(unittest.TestCase):
    def test_replacement_requires_successful_matching_public_measurements(self):
        from mah2.public_evidence import supports_replacement
        probe=dict(returncode=0,comparison=dict(incumbent='P1',candidate='P2',basis='held_out_public_data',
            criterion='MSE',protocol='Matched held-out independent examples',direction='min',incumbent_value=2.,candidate_value=1.))
        self.assertTrue(supports_replacement(probe,'P1','P2'))
        self.assertFalse(supports_replacement({**probe,'returncode':1},'P1','P2'))
        for key,value in [('candidate_value',float('nan')),('candidate_value',10**1000),('candidate_value',2.),('candidate','P3'),('basis','training_fit'),('direction','unknown')]:
            bad=copy.deepcopy(probe);bad['comparison'][key]=value
            self.assertFalse(supports_replacement(bad,'P1','P2'))

    def test_public_probe_copies_artifacts_and_cannot_modify_original_program(self):
        from mah2.dsstar.optimizer import Experiment
        class Box:
            def __init__(self,root,data,c):self.root=root;root.mkdir(parents=True)
            def run(self,code,name,timeout):
                assert timeout==3
                assert (self.root/'outputs/P1/out.csv').read_text()=='id,y\n1,2\n'
                (self.root/'programs/P1.py').write_text('changed copy')
                return dict(returncode=0,seconds=.1,stdout='probe log\n'+json.dumps({'comparison':{'criterion':'fixture'},'check':{'observations':{'rows':1}}},indent=2)+'\n',stderr='')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'data';data.mkdir();e=Experiment({'public_probe_seconds':3},root/'round_1');e.data=data
            p=e.root/'reference';(p/'replay/pred_results').mkdir(parents=True)
            (p/'submission.py').write_text('print(1)');(p/'replay/pred_results/out.csv').write_text('id,y\n1,2\n')
            with patch('mah2.dsstar.optimizer.Sandbox',Box):record=e.public_probe('print(1)','selector',{'P1':'reference'})
            self.assertEqual((p/'submission.py').read_text(),'print(1)');self.assertEqual(record['comparison']['criterion'],'fixture')
            self.assertEqual(record['check']['observations']['rows'],1)
            self.assertEqual(record['snapshots'][0]['included'],True);self.assertEqual(e.probes['selector_0'],record)

    def test_previous_round_replacement_is_gated_on_executed_public_probe(self):
        import re
        from mah2.dsstar.optimizer import Experiment
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);e=Experiment({'public_probes':True,'evidence_gated_selection':True},root/'round_2');choices={}
            for label in ('reference','previous'):
                h=initial();h['roles']['coder']=label;choices[label]=h;p=e.root/label;p.mkdir();(p/'replay').mkdir()
                (p/'submission.py').write_text('print(1)');(p/'replay/out.csv').write_text('y\n1\n')
                (p/'outcome.json').write_text(json.dumps(dict(runnable=True,program_sha256=label)))
            class Client:
                calls=0;probe=False
                def complete(self,prompt,role):
                    self.calls+=1;self.inc=re.search(r'Prior-round incumbent: (P\d+)',prompt).group(1)
                    self.new='P1' if self.inc=='P2' else 'P2'
                    if self.probe and self.calls==1:return json.dumps({'public_probe':'run a matched public check'})
                    return json.dumps(dict(selected=self.new,rationale='candidate',replacement_probe='selector_0'))
            client=Client();e.client=lambda stage:client
            selected,_,_=e.select({'task_inst':'Predict y','output_fname':'out.csv'},choices,('reference',{},{}))
            self.assertEqual(selected,'previous')
            self.assertEqual(client.calls,5)
            def probe(code,stage,labels):
                r=dict(probe_id='selector_0',returncode=0,comparison=dict(incumbent=client.inc,candidate=client.new,
                    basis='held_out_public_data',criterion='MSE',protocol='Matched held-out examples',direction='min',incumbent_value=2.,candidate_value=1.))
                e.probes['selector_0']=r;return r
            client.calls=0;client.probe=True;e.public_probe=probe
            selected,h,out=e.select({'task_inst':'Predict y','output_fname':'out.csv'},choices,('reference',{},{}))
            self.assertEqual(selected,'reference');self.assertEqual(h['roles']['coder'],out['program_sha256'])
            self.assertEqual(client.calls,2)

    def test_selector_recovers_a_plain_text_probe_without_weakening_replacement_gate(self):
        import re
        from mah2.dsstar.optimizer import Experiment
        with tempfile.TemporaryDirectory() as d:
            e=Experiment({'public_probes':True,'evidence_gated_selection':True},Path(d)/'round_2');choices={}
            for label in ('reference','previous'):
                choices[label]=initial();p=e.root/label;p.mkdir();(p/'replay').mkdir()
                (p/'submission.py').write_text('print(1)');(p/'replay/out.csv').write_text('y\n1\n')
                (p/'outcome.json').write_text(json.dumps({'runnable':True}))
            class Client:
                calls=0
                def complete(self,prompt,role):
                    self.calls+=1;self.inc=re.search(r'Prior-round incumbent: (P\d+)',prompt).group(1)
                    self.new='P1' if self.inc=='P2' else 'P2'
                    if self.calls in (1,3):
                        if self.calls==3:assert 'Replacement rejected' in prompt
                        return json.dumps({'public_probe':'plain' if self.calls==1 else 'structured'})
                    return json.dumps(dict(selected=self.new,rationale='measured',replacement_probe='selector_0' if self.calls==2 else 'selector_1'))
            client=Client();e.client=lambda stage:client
            def probe(code,stage,labels):
                name=f'selector_{len(e.probes)}';record=dict(probe_id=name,returncode=0,comparison=None)
                if code=='structured':record['comparison']=dict(incumbent=client.inc,candidate=client.new,basis='explicit_public_requirement',criterion='missing rows',protocol='compare both outputs to the same public join',direction='min',incumbent_value=1,candidate_value=0)
                e.probes[name]=record;return record
            e.public_probe=probe
            selected,_,_=e.select({'task_inst':'Join the public tables','output_fname':'out.csv'},choices,('previous',{},{}))
            self.assertEqual(selected,'reference');self.assertEqual(client.calls,4)
            record=json.loads((e.root/'selection.json').read_text())
            self.assertEqual(len(record['rejected_replacements']),1)
            self.assertEqual(record['replacement_probe'],'selector_1')

    def test_public_file_reader_bounds_bytes_and_blocks_private_paths(self):
        from mah2.public_evidence import read_public_inputs
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'public';root.mkdir();secret=Path(d)/'private.txt';secret.write_text('SECRET')
            (root/'first.py').write_text('a'*10);(root/'second.csv').write_text('b'*10)
            (root/'link').symlink_to(secret);(root/'binary.npy').write_bytes(b'\x00binary')
            r=read_public_inputs(root,{'paths':['first.py','second.csv']},max_bytes=12)
            self.assertEqual([v['bytes_read'] for v in r['items']],[10,2]);self.assertTrue(r['items'][1]['truncated'])
            self.assertEqual(read_public_inputs(root,{'path':'first.py','offset':8})['items'][0]['content'],'aa')
            for name in ('../private.txt',str(secret),'link'):
                with self.assertRaises(ValueError):read_public_inputs(root,{'path':name})
            self.assertIn('content_omitted',read_public_inputs(root,{'path':'binary.npy'})['items'][0])
            listing=read_public_inputs(root,{'path':'.'},max_entries=2)['items'][0]
            self.assertTrue(listing['truncated']);self.assertEqual(len(listing['entries']),2)
            self.assertNotIn('SECRET',json.dumps(listing))

    def test_editor_can_ground_revision_in_public_source_without_private_access(self):
        from mah2.dsstar.optimizer import Experiment
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'data';data.mkdir();(data/'helper.py').write_text('def preserve(values): return tuple(values)')
            e=Experiment({'public_input_reads':True},root/'round_1');e.data=data
            class Client:
                calls=0
                def complete(self,prompt,role):
                    self.calls+=1
                    if self.calls==1:return json.dumps({'read_input':{'path':'helper.py'}})
                    assert 'def preserve(values): return tuple(values)' in prompt
                    return json.dumps({'harness':initial()})
            client=Client();e.client=lambda stage:client
            harness,decision=e.edit('proposal_a','Inspect before changing',{'base_harness':initial(),'runs':{}},'invariant')
            self.assertTrue(decision['valid']);self.assertEqual(client.calls,2);self.assertEqual(harness,initial())
            receipt=json.loads((e.root/'proposal_a_input_reads.jsonl').read_text())
            self.assertEqual(receipt['result']['items'][0]['path'],'helper.py')

    def test_public_check_requires_executed_structured_observations(self):
        from mah2.public_evidence import has_public_check
        probe=dict(returncode=0,check=dict(kind='source_consistency',criterion='toy formula',
            protocol='compare a public implementation on one input',observations={'mismatch_count':1}))
        self.assertTrue(has_public_check(probe))
        for key,value in (('kind','confidence'),('criterion',''),('protocol',''),('observations',{})):
            invalid=copy.deepcopy(probe);invalid['check'][key]=value
            self.assertFalse(has_public_check(invalid))
        probe['returncode']=1;self.assertFalse(has_public_check(probe))

    def test_changed_harness_requires_its_own_executed_public_check(self):
        from mah2.dsstar.optimizer import Experiment
        with tempfile.TemporaryDirectory() as d:
            e=Experiment({'public_probes':True,'require_public_checks':True},Path(d)/'round_1')
            base=initial();changed=copy.deepcopy(base);changed['roles']['coder']='Check a representative value against supplied definitions.'
            ev={'base_harness':base,'runs':{'reference':{'trace':[{'id':'e1'}]}}}
            reply=dict(harness=changed,evidence=['reference:e1'],public_check='claimed source check',
                expected_behavior='preserve supplied formula',public_check_probe='proposal_a_0')
            calls=[]
            class Client:
                def complete(self,prompt,role):
                    calls.append(prompt)
                    if len(calls)==2:
                        assert 'Your last reply failed validation' in prompt
                        return json.dumps({'public_probe':'perform the public toy check'})
                    return json.dumps(reply)
            def probe(*args):
                row=dict(probe_id='proposal_a_0',returncode=0,check=dict(kind='source_consistency',
                    criterion='toy formula',protocol='one supplied input',observations={'mismatch_count':1}))
                e.probes[row['probe_id']]=row;return row
            e.client=lambda stage:Client();e.public_probe=probe
            h,decision=e.edit('proposal_a','Inspect before changing',ev,'invariant')
            self.assertEqual(len(calls),3);self.assertTrue(decision['valid']);self.assertEqual(h,changed)
            self.assertEqual(decision['observed_public_check']['check']['observations']['mismatch_count'],1)
            self.assertEqual(len((e.root/'proposal_a_validation.jsonl').read_text().splitlines()),1)

    def test_selector_public_reads_recover_within_bounds_and_repeated_errors_keep_incumbent(self):
        from mah2.dsstar.optimizer import Experiment
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'data';data.mkdir();(data/'train.csv').write_text('id,target\n1,2\n')
            e=Experiment({'public_input_reads':True},root/'round_2');e.data=data;choices={}
            for label in ('reference','previous'):
                h=initial();h['roles']['coder']=label;choices[label]=h;p=e.root/label;p.mkdir();(p/'replay').mkdir()
                (p/'submission.py').write_text('print(1)');(p/'replay/out.csv').write_text('id,target\n1,2\n')
                (p/'outcome.json').write_text(json.dumps(dict(runnable=True,program_sha256=label)))
            class Client:
                calls=0
                def complete(self,prompt,role):
                    self.calls+=1
                    if self.calls>1:assert 'id,target' in prompt
                    return json.dumps({'read_input':{'path':'train.csv'}})
            client=Client();e.client=lambda stage:client
            selected,h,out=e.select({'task_inst':'Predict target','output_fname':'out.csv'},choices,('reference',{},{}))
            self.assertEqual(client.calls,4);self.assertEqual(selected,'previous')
            record=json.loads((e.root/'selection.json').read_text());self.assertFalse(record['valid']);self.assertIn('read limit',record['error'])
            client.complete=lambda *a,**k:json.dumps({'read_input':{'path':'../private.txt'}})
            selected,_,_=e.select({'task_inst':'Predict target','output_fname':'out.csv'},choices,('reference',{},{}))
            self.assertEqual(selected,'previous')
            calls=[]
            def grounded_reply(prompt,role):
                calls.append(prompt)
                if len(calls)==1:return json.dumps({'read_input':{'path':'./data/train.csv'}})
                if len(calls)==2:
                    self.assertIn('Public input read failed',prompt)
                    self.assertIn('omit ./data/ and ./datasets/',prompt)
                    return json.dumps({'read_input':{'path':'train.csv'}})
                self.assertIn('id,target',prompt)
                return json.dumps(dict(selected='P1',rationale='Checked public source schema'))
            client.complete=grounded_reply
            selected,h,out=e.select({'task_inst':'Predict target','output_fname':'out.csv'},choices,('reference',{},{}))
            self.assertEqual(len(calls),3);self.assertEqual(h['roles']['coder'],out['program_sha256'])
            record=json.loads((e.root/'selection.json').read_text())
            self.assertTrue(record['valid']);self.assertEqual(len(record['tool_errors']),1)

    def test_selector_failed_probe_allows_correction_without_bypassing_replacement_gate(self):
        from mah2.dsstar.optimizer import Experiment
        with tempfile.TemporaryDirectory() as d:
            e=Experiment({'public_probes':True,'evidence_gated_selection':True},Path(d)/'round_2');choices={}
            for label in ('reference','previous'):
                choices[label]=initial();p=e.root/label;p.mkdir();(p/'replay').mkdir()
                (p/'submission.py').write_text('print(1)');(p/'replay/out.csv').write_text('id,target\n1,2\n')
                (p/'outcome.json').write_text(json.dumps(dict(runnable=True)))
            replies=[]
            class Client:
                def complete(self,prompt,role):
                    replies.append(prompt)
                    if len(replies)==1:return json.dumps({'public_probe':None})
                    assert 'Public check could not execute' in prompt
                    # A failed check must not authorize replacement, even if the model claims it did.
                    incumbent=prompt.split('Prior-round incumbent: ')[1].split('.')[0]
                    new='P2' if incumbent=='P1' else 'P1'
                    return json.dumps(dict(selected=new,rationale='claimed improvement',replacement_probe='selector_0'))
            e.client=lambda stage:Client()
            def failed_probe(*args):raise ValueError('public_probe must contain Python code')
            e.public_probe=failed_probe
            selected,_,_=e.select({'task_inst':'Predict target','output_fname':'out.csv'},choices,('reference',{},{}))
            record=json.loads((e.root/'selection.json').read_text())
            self.assertEqual(len(replies),5);self.assertEqual(selected,'previous')
            self.assertEqual(len(record['rejected_replacements']),4)
            self.assertEqual(record['tool_errors'][0]['tool'],'public_probe')
            self.assertIn('No executed public comparison',record['error'])

    def test_reflection_prioritizes_actual_selected_program_evidence(self):
        from mah2.dsstar.optimizer import reflection_evidence
        ev=dict(base_harness=initial(),adopted_harness=initial(),selected_stage='reference',composition={'evidence':[]},
                selection={'rationale':'Retained the earlier public-validated program'},runs={
                    'reference':{'trace':[{'id':'e1','kind':'final_replay','returncode':0}],'outcome':{'runnable':True,'official_success':'SECRET'}},
                    'successor':{'trace':[{'id':'e2','kind':'rollout_failure','error':'failed'}],'outcome':{'runnable':False}}})
        view=reflection_evidence(ev)
        self.assertEqual(view['selected_events'][0]['run'],'reference');self.assertEqual(view['selected_stage'],'reference')
        self.assertNotIn('SECRET',json.dumps(view))

    def test_analyzer_cannot_receive_full_task_and_uses_short_execution_limit(self):
        from mah2.dsstar.rollout import Rollout
        class Client:
            def complete(self,prompt,role):self.prompt=prompt;return 'print(1)'
        class Box:
            def __init__(self,root,data,c):self.root=root;root.mkdir(parents=True);self.timeouts=[]
            def run(self,code,name,timeout):
                self.timeouts.append(timeout)
                return dict(returncode=0,stdout='',stderr='',seconds=0.,timeout=False,artifacts={})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'data';data.mkdir();client=Client()
            config=dict(public_context=True,bounded_analysis=True,analysis_seconds=60,rollout_seconds=1800)
            r=Rollout(client,initial(),config,root/'run',data,Box)
            r.question='TASK_SENTINEL: train a very expensive model'
            r.ask('code_for_analyze','./data/huge.csv')
            self.assertNotIn('TASK_SENTINEL',client.prompt);self.assertIn('Analyzer boundary',client.prompt)
            r.ask('debug_for_analyze','print(1)','Fix a parsing error')
            self.assertNotIn('TASK_SENTINEL',client.prompt);self.assertIn('Analyzer boundary',client.prompt)
            r.ask('initial_implementation','plan',[],[])
            self.assertIn('TASK_SENTINEL',client.prompt)
            r.execute('print(1)','analyze_0.py');r.execute('print(1)','intermediate.py')
            self.assertEqual(r.box.timeouts[0],60);self.assertGreater(r.box.timeouts[1],60)

    def test_historical_profile_blocks_knowledge_and_metadata_before_editors(self):
        from mah2.task_context import input_packet,render_task
        row=dict(task_inst='Solve public task',output_fname='out.csv',domain='SECRET',domain_knowledge='SECRET',dataset_preview='SECRET',dataset_folder_tree='SECRET',gold='SECRET')
        packet=input_packet(row,'historical_task_only')
        self.assertEqual(set(packet),{'task_inst','output_fname'})
        self.assertNotIn('SECRET',render_task(packet))
        self.assertNotIn('SECRET',json.dumps({'task':packet}))
        with self.assertRaises(ValueError):input_packet(row,'unknown')

    def test_public_selection_ignores_hidden_outcomes_and_retains_incumbent_on_bad_reply(self):
        from mah2.dsstar.optimizer import Experiment
        with tempfile.TemporaryDirectory() as d:
            e=Experiment({},Path(d)/'round_2');choices={}
            for label in ('reference','candidate_a','successor','previous'):
                h=initial();h['roles']['coder']=label;choices[label]=h
                p=e.root/label;p.mkdir();(p/'replay').mkdir()
                (p/'submission.py').write_text('print(1)')
                (p/'replay/out.csv').write_text('value\n1\n')
                (p/'outcome.json').write_text(json.dumps(dict(runnable=label!='successor',program_sha256=label,official_success='SECRET')))
            class Client:
                def complete(self,prompt,role):
                    self.prompt=prompt;return '{"selected":"unknown", "rationale":"invalid"}'
            client=Client();e.client=lambda stage:client
            selected,h,out=e.select({'task_inst':'Write one value','output_fname':'out.csv'},choices,('successor',choices['successor'],{}))
            self.assertEqual(selected,'previous');self.assertEqual(h['roles']['coder'],out['program_sha256'])
            self.assertNotIn('SECRET',client.prompt)
            record=json.loads((e.root/'selection.json').read_text())
            self.assertNotIn('successor',record['mapping'].values())
            alias=next(a for a,l in record['mapping'].items() if l=='candidate_a')
            client.complete=lambda *a,**k:json.dumps(dict(selected=alias,rationale='Matches public specification'))
            selected,h,out=e.select({'task_inst':'Write one value','output_fname':'out.csv'},choices,('successor',{},{}))
            self.assertEqual(selected,'candidate_a');self.assertEqual(h['roles']['coder'],out['program_sha256'])

    def test_selected_previous_program_and_harness_survive_recursion(self):
        class Experiment:
            def __init__(self,c,path):self.path=path;path.mkdir()
            def run(self,method,packet,data,library,starting_harness,round_index,round_count):
                h=copy.deepcopy(starting_harness)
                if round_index==1:
                    h['roles']['coder']='retained';p=self.path/'candidate_a';p.mkdir();(p/'submission.py').write_text('print(1)')
                else:
                    assert (self.path/'previous/submission.py').read_text()=='print(1)'
                    assert h['roles']['coder']=='retained'
                (self.path/'selected_harness.json').write_text(json.dumps(h))
                return dict(runnable=True,selected_stage='candidate_a' if round_index==1 else 'previous')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'run'
            run_recursive(dict(allowance_usd=1,runnable_fallback=True,public_selection=True),root,'whole_team',{},Path(d),[],2,Experiment)
            self.assertEqual((root/'successor/submission.py').read_text(),'print(1)')
            self.assertEqual(json.loads((root/'final_harness.json').read_text())['roles']['coder'],'retained')

    def test_selector_budget_keeps_round_within_cap(self):
        from mah2.dsstar.optimizer import Experiment
        c=json.loads((ROOT/'tests/fixtures/cycles10_no_knowledge.json').read_text())['dsstar']
        c.update(allowance_usd=.5,input_per_million=.37,output_per_million=1.25)
        class Client:
            def __init__(self,c,b,ledger,stage):self.budget=b
        with tempfile.TemporaryDirectory() as d:
            e=Experiment(c,Path(d)/'round_1',Client)
            for stage in ('reference','proposal_a','proposal_b','candidate_a','candidate_b','composer','successor','selector','reflector'):
                client=e.client(stage);self.assertGreater(client.budget.cap,0)
                client.budget.charged=client.budget.cap
            self.assertAlmostEqual(sum(b.charged for b in e.budgets.values()),.5)

    def test_public_context_allowlist_drops_hidden_fields(self):
        from mah2.task_context import public_packet,render_task
        row={'task_inst':'solve','domain_knowledge':'use a four-layer network','dataset_preview':'a,b','dataset_folder_tree':'data/','output_fname':'out.csv','reference_solution':'SECRET','gold':'SECRET'}
        packet=public_packet(row);text=render_task(packet)
        self.assertIn('four-layer',text);self.assertIn('a,b',text);self.assertNotIn('SECRET',text)
    def test_python_extraction_preserves_unicode_and_does_not_truncate(self):
        from mah2.dsstar.rollout import clean_code
        self.assertEqual(clean_code('Explanation\n```python\nprint("≈")\n```\nDone.'),'print("≈")')
        with self.assertRaises(SyntaxError):clean_code('print(1)\nThis is not Python.')
    def test_artifact_inspection_refuses_escape_and_reports_headers(self):
        from mah2.public_evidence import artifact_summary
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'work';root.mkdir();(root/'out.csv').write_text('feature,value\na,1\nb,2\n')
            s=artifact_summary(root,'out.csv');self.assertEqual(s['columns'],['feature','value']);self.assertEqual(s['rows_observed'],2)
            (Path(d)/'secret').write_text('hidden');(root/'link').symlink_to(Path(d)/'secret')
            self.assertFalse(artifact_summary(root,'link')['exists']);self.assertFalse(artifact_summary(root,'../secret')['exists'])
    def test_finalization_repairs_invalid_program_and_exposes_public_artifact(self):
        import subprocess,sys
        from mah2.dsstar.rollout import Rollout
        class Box:
            def __init__(self,root,data,c):self.root=root;root.mkdir(parents=True)
            def run(self,code,name,timeout):
                (self.root/name).write_text(code)
                x=subprocess.run([sys.executable,name],cwd=self.root,text=True,capture_output=True,timeout=2)
                return {'returncode':x.returncode,'stdout':x.stdout,'stderr':x.stderr,'seconds':0.,'timeout':False,'artifacts':{}}
        program="from pathlib import Path\nPath('pred_results').mkdir(exist_ok=True)\nPath('pred_results/out.csv').write_text('id,value\\n1,2\\n')"
        class Client:
            finals=0;verified=False
            def complete(self,prompt,role):
                if role=='planner':return 'Write the output.'
                if role=='verifier':
                    self.verified='Public artifact inspection' in prompt and 'id' in prompt;return 'Yes'
                if role=='finalizer':
                    self.finals+=1
                    return 'This is not Python.' if self.finals==1 else 'Here is the repair:\n```python\n'+program+'\n```\nDone.'
                return program
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'data';data.mkdir();client=Client()
            c={'rollout_seconds':30,'max_refinements':1,'max_code_attempts':1,'max_debug_rounds':1,'max_route_attempts':1,'public_context':True,'artifact_feedback':True,'finalization_repairs':1}
            result=Rollout(client,initial(),c,root/'run',data,Box).run({'task_inst':'Write CSV','output_fname':'pred_results/out.csv'})
            self.assertTrue(result['runnable']);self.assertTrue(client.verified);self.assertEqual(client.finals,2)
            self.assertEqual((root/'run/replay/pred_results/out.csv').read_text(),'id,value\n1,2\n')
    def test_generic_memory_survives_task_specific_harness(self):
        from mah2.dsstar.optimizer import Experiment
        class Client:
            def complete(self,*a,**k):return json.dumps({'experience':{'cue':'join','lesson':'Check key uniqueness','evidence':['reference:e1'],'limitations':'Only relational tables','reconsider_when':'Keys are intentionally repeated'}})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'data';data.mkdir();(data/'task.csv').write_text('x')
            c={'lesson_only_memory':True};e=Experiment(c,root/'round');e.client=lambda stage:Client()
            h=initial();h['roles']['coder']='Read task.csv'
            ev={'adopted_harness':h,'runs':{},'composition':{}}
            view={'selected_events':[{'run':'reference','id':'e1'}]}
            library=[]
            with patch('mah2.dsstar.optimizer.reflection_evidence',return_value=view):e.reflect(ev,{'output_fname':'out.csv'},data,library)
            self.assertEqual(len(library),1);self.assertNotIn('task.csv',json.dumps(library))
    def test_recursion_preserves_previous_runnable_program_when_entire_round_fails(self):
        class Experiment:
            def __init__(self,c,path):self.path=path;path.mkdir()
            def run(self,method,packet,data,library,starting_harness,round_index,round_count):
                h=copy.deepcopy(starting_harness);h['roles']['coder']=str(round_index)
                (self.path/'selected_harness.json').write_text(json.dumps(h))
                return {'runnable':round_index==1,'selected_stage':'reference' if round_index==1 else None}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'run'
            r=run_recursive({'allowance_usd':1,'runnable_fallback':True},root,'whole_team',{},Path(d),[],2,Experiment)
            self.assertTrue(r['runnable']);self.assertEqual(r['selected_round'],1)
            self.assertEqual((root/'successor').readlink(),Path('round_1/reference'))
            self.assertEqual(json.loads((root/'final_harness.json').read_text())['roles']['coder'],'1')
    def test_failed_successor_selects_reference_harness_and_program(self):
        from mah2.dsstar.optimizer import Experiment
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'round';e=Experiment({'runnable_fallback':True},root)
            def team(stage,h,packet,data):
                p=root/stage;p.mkdir();(p/'trace.jsonl').write_text('')
                result={'runnable':stage!='successor','program_sha256':stage}
                (p/'outcome.json').write_text(json.dumps(result));return result
            def edit(stage,prompt,ev,scope):
                h=copy.deepcopy(ev['base_harness']);h['roles']['coder']=stage
                return h,{'valid':True,'harness':h}
            e.run_team=team;e.edit=edit;e.reflect=lambda *a:None
            result=e.run('whole_team',{'task_inst':'fixture'},Path(d),[])
            self.assertEqual(result['selected_stage'],'reference');self.assertEqual(result['program_sha256'],'reference')
            self.assertEqual(json.loads((root/'selected_harness.json').read_text()),initial())
