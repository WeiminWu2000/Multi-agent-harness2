import copy,json,tempfile,threading,unittest
from unittest.mock import patch
from pathlib import Path
from mah2.gateway import Gateway,BudgetExceeded
from regression_support.search import Search,validate,apply_proposal
ROOT=Path(__file__).resolve().parents[1]

class Response:
    def raise_for_status(self):pass
    def json(self):return {'choices':[{'message':{'content':'{}'}}],'usage':{'prompt_tokens':20,'completion_tokens':10,'cost':0.001}}
class Session:
    def __init__(self):self.n=0
    def post(self,*args,**kwargs):self.n+=1;return Response()

class Protocol(unittest.TestCase):
    def test_http_error_diagnostics_and_model_parameters(self):
        import requests
        class Rejected:
            status_code=429
            headers={'Retry-After':'10','Authorization':'not-to-be-saved'}
            text='rate limited fixture'
            def raise_for_status(self):raise requests.HTTPError('429')
        class RejectSession:
            def post(self,*args,**kwargs):
                self.payload=kwargs['json'];return Rejected()
        with tempfile.TemporaryDirectory() as d:
            c=json.loads((ROOT/'tests/fixtures/pilot.json').read_text());c['supports_seed']=False
            c['supports_response_format']=True;s=RejectSession();g=Gateway(d,c,.1,s)
            with self.assertRaises(requests.HTTPError):g.request({'messages':[],'seed':123,'response_format':{'type':'json_object'}})
            error=json.loads((Path(d)/'call_0000_error.json').read_text())
            self.assertEqual(error['status_code'],429)
            self.assertEqual(error['headers'],{'Retry-After':'10'})
            self.assertNotIn('fixture',error['body'])
            self.assertNotIn('seed',s.payload)
            self.assertEqual(s.payload['response_format'],{'type':'json_object'})
            self.assertEqual(g.calls[0]['http_status'],429)
    def test_editor_has_one_schema_and_system_scope(self):
        class Editor:
            def set_stage(self,*args):pass
            def chat(self,system,user):
                self.system=system;self.user=user
                return {'kind':'noop','rationale':'No evidence-supported repair'}
        w=json.loads((ROOT/'config/workflow.json').read_text())
        with tempfile.TemporaryDirectory() as d,patch('regression_support.search.evidence',return_value='fixture evidence'):
            s=Search.__new__(Search);s.root=Path(d);s.g=Editor();s.history=[];s.decisions=[]
            s.packet={'task_inst':'test'};s.c=json.loads((ROOT/'tests/fixtures/pilot.json').read_text())
            s.propose('local',w,'reference','local')
            self.assertTrue(s.decisions[-1]['valid'])
            self.assertIn('Change at most one existing role instruction',s.g.system)
            self.assertNotIn('improved_multi_agent_design',s.g.system+s.g.user)
            self.assertNotIn('Use uv for all Python workflows',s.g.user)
            self.assertNotIn('Explicitly increase orchestrator-subagent',s.g.user)
    def test_budget_reservation_and_actual_settlement(self):
        with tempfile.TemporaryDirectory() as d:
            c=json.loads((ROOT/'tests/fixtures/pilot.json').read_text());s=Session();g=Gateway(d,c,.003,s)
            g.set_stage('test',.003);g.request({'messages':[],'max_tokens':128})
            self.assertAlmostEqual(g.charged,.001)
            g.set_stage('denied',.0001)
            with self.assertRaises(BudgetExceeded):g.request({'messages':[]})
            self.assertEqual(s.n,1)
    def test_unknown_usage_keeps_reservation(self):
        class Unknown(Response):
            def json(self):return {'choices':[{'message':{'content':'{}'}}]}
        class U(Session):
            def post(self,*a,**k):return Unknown()
        with tempfile.TemporaryDirectory() as d:
            c=json.loads((ROOT/'tests/fixtures/pilot.json').read_text());g=Gateway(d,c,.1,U());g.set_stage('x',.1)
            g.request({'messages':[],'max_tokens':128})
            self.assertEqual(g.calls[0]['charged_usd'],g.calls[0]['reserved_usd'])
    def test_scope_and_composer_capacity(self):
        w=json.loads((ROOT/'config/workflow.json').read_text());x=copy.deepcopy(w)
        x['roles']['implementer']='new procedure';self.assertEqual(validate(x,w,'local'),x)
        x['contracts']['data_specialist.implementer']='new handoff'
        with self.assertRaises(ValueError):validate(x,w,'local')
        self.assertEqual(validate(x,w,'coordination'),x)
        x['contracts']['implementer.auditor']='second handoff'
        with self.assertRaises(ValueError):validate(x,w,'coordination')
        self.assertEqual(validate(x,w,'integrated'),x)
        self.assertEqual(validate(x,w,'composer'),x)
        patch={'kind':'handoff','edge':'data_specialist.implementer','contract':'new','endpoint_instructions':{'auditor':'unrelated'}}
        with self.assertRaises(ValueError):apply_proposal(patch,w,'coordination')
        local=apply_proposal({'kind':'role','role':'implementer','instruction':'new'},w,'local')
        self.assertEqual(local['contracts'],w['contracts'])
        self.assertEqual(local['order'],w['order'])
    def test_handoff_uses_declared_endpoint_names(self):
        w=json.loads((ROOT/'config/workflow.json').read_text())
        edge=next(iter(w['contracts']));sender,receiver=edge.split('.')
        proposal={'kind':'handoff','edge':edge,'contract':'clarified requirement',
                  'endpoint_instructions':{sender:'updated sender',receiver:'updated receiver'}}
        result=apply_proposal(proposal,w,'coordination')
        self.assertEqual(set(result['roles']),set(w['roles']))
        proposal['endpoint_instructions']={'sender':'wrong literal key','receiver':'wrong literal key'}
        with self.assertRaisesRegex(ValueError,'actual endpoints'):
            apply_proposal(proposal,w,'coordination')
    def test_serialized_workflow_preserves_validation(self):
        w=json.loads((ROOT/'config/workflow.json').read_text())
        for scope in ('integrated','composer'):
            self.assertEqual(apply_proposal({'workflow':json.dumps(w)},w,scope),w)
            bad=copy.deepcopy(w);bad['contracts']['implementer.undeclared']='handoff'
            with self.assertRaises(ValueError):
                apply_proposal({'workflow':json.dumps(bad)},w,scope)
            with self.assertRaises(ValueError):
                apply_proposal({'workflow':json.dumps(json.dumps(w))},w,scope)
    def test_plan_budget_and_task_selection(self):
        c=json.loads((ROOT/'tests/fixtures/pilot.json').read_text())
        self.assertEqual(len(c['tasks']),10);self.assertEqual(len(set(c['groups'].values())),10)
        self.assertGreater(c['budget']['per_method_task_cap'],0)
        self.assertLessEqual(c['budget']['per_method_task_cap'],1.0)
        self.assertLessEqual(20*c['budget']['per_method_task_cap']+c['budget'].get('prior_model_study_upper_usd',0),20.000001)
        self.assertFalse(c['model_training']);self.assertEqual(len(c['methods']),2)

if __name__=='__main__':unittest.main()
