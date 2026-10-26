"""Two frozen-model optimizers on the same MASS/Qwen-code execution substrate."""
import copy,json,random,sys
from pathlib import Path
from mah2.gateway import Gateway,BudgetExceeded
from mah2.runtime import ROOT,episode,render_workflow,official_grade
sys.path.insert(0,str(ROOT/'vendor/mass'))
from harness_improvement.iterate_multi_agent_prompt import QueryTemplate,_build_single_submission_improvement_prompt
from evaluation.bundle import build_judge_bundle,bundle_workspace_evidence
from evaluation_claudecodex.pairwise_prompts import pairwise_judge_system_for_query_num,pairwise_user_suffix


def validate(w,base,scope):
    if not isinstance(w,dict) or set(w)!={'roles','contracts','order'}:raise ValueError('workflow fields')
    roles=w['roles'];contracts=w['contracts'];order=w['order']
    if not isinstance(roles,dict) or not 1<=len(roles)<=8:raise ValueError('role count')
    if any(not isinstance(k,str) or not k.replace('_','').isalnum() or not isinstance(v,str) or not v for k,v in roles.items()):raise ValueError('roles')
    if not isinstance(order,list) or not order or set(order)!=set(roles):raise ValueError('order must cover roles')
    if not isinstance(contracts,dict):raise ValueError('contracts')
    for edge,value in contracts.items():
        ends=edge.split('.')
        if len(ends)!=2 or not set(ends)<=set(roles) or not isinstance(value,str):raise ValueError('contract endpoints')
    if len(json.dumps(w).encode())>16000:raise ValueError('workflow exceeds shared byte bound')
    changed={k for k in set(roles)|set(base['roles']) if roles.get(k)!=base['roles'].get(k)}
    edges={k for k in set(contracts)|set(base['contracts']) if contracts.get(k)!=base['contracts'].get(k)}
    if scope=='local':
        if set(roles)!=set(base['roles']) or len(changed)>1 or edges or order!=base['order']:raise ValueError('local proposal crosses interface')
    elif scope=='coordination':
        if set(roles)!=set(base['roles']):raise ValueError('coordination preserves roster')
        if len(edges)>1:raise ValueError('coordination changes more than one handoff')
        if edges:
            endpoints=set(next(iter(edges)).split('.'))
            if not changed<=endpoints:raise ValueError('unrelated endpoint instructions')
            if order!=base['order']:raise ValueError('choose contract or order change, not both')
        else:
            if changed:raise ValueError('role changes require a declared handoff change')
            # Call-order edits may reorder/recall existing agents but cannot alter roles.
    return copy.deepcopy(w)


def apply_proposal(reply,base,scope):
    """Construct scoped candidates from bounded patches; validate before probing."""
    if scope not in ('local','coordination'):
        workflow=reply['workflow']
        # Normalize one serialization layer only; preserve all structural checks.
        if isinstance(workflow,str):workflow=json.loads(workflow)
        return validate(workflow,base,scope)
    w=copy.deepcopy(base)
    if reply.get('kind')=='noop':return w
    if scope=='local':
        if reply.get('kind')!='role' or reply['role'] not in w['roles']:raise ValueError('Expected one existing role patch')
        w['roles'][reply['role']]=reply['instruction']
    elif reply.get('kind')=='handoff':
        w['contracts'][reply['edge']]=reply['contract']
        endpoints=reply.get('endpoint_instructions',{})
        if not isinstance(endpoints,dict) or not set(endpoints)<=set(reply['edge'].split('.')):
            raise ValueError('endpoint_instructions keys must be actual endpoints of edge')
        w['roles'].update(endpoints)
    elif reply.get('kind')=='order':w['order']=reply['order']
    else:raise ValueError('Expected one handoff or order patch')
    return validate(w,base,scope)


def evidence(path,packet):
    path=Path(path);record=json.loads((path/'outcome.json').read_text())
    bundle=build_judge_bundle(memory_root=path/'work',task_row={'query_id':'pilot','query':packet['task_inst']},
        log_path=path/'work/logs.txt' if (path/'work/logs.txt').exists() else None,
        report_max_chars=4000,json_max_chars=2000,code_max_chars=6000,max_code_files=2,
        log_head=1000,log_tail=2000,tree_max_files=60)
    text=bundle_workspace_evidence(bundle)
    # Same evidence truncation for both arms; official evaluations never included.
    return json.dumps({'public_replay':record['replay'],'runnable':record['runnable'],'artifact_hashes':record['artifacts']})[:4000]+'\n[Workspace excerpt, maximum 10000 characters]\n'+text[:10000]


class Search:
    def __init__(self,config,method,packet,data,root):
        self.c=config;self.method=method;self.packet=packet;self.data=data;self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=False)
        self.g=Gateway(self.root/'api',config,config['budget']['per_method_task_cap']).start()
        self.history=[];self.decisions=[];self.probe_count=0;self.comparisons=0
        (self.root/'config.json').write_text(json.dumps(config,indent=2))
        (self.root/'packet.json').write_text(json.dumps(packet,indent=2))

    def run_team(self,name,w):
        self.g.set_stage(name,self.c['algorithm']['rollout_cap'])
        self.probe_count+=1
        result=episode(self.g,w,self.packet,self.data,self.root/name,self.c)
        if result['agent']['stderr'].startswith('bwrap:'):
            raise RuntimeError('Sandbox infrastructure failure; stop before spending on revisions')
        return result

    def propose(self,name,w,current,scope,extra=None):
        self.g.set_stage(name,self.c['algorithm']['composer_cap' if scope=='composer' else 'proposal_cap'])
        ev=evidence(self.root/current,self.packet)
        template=QueryTemplate(0,'scienceagentbench','',self.packet['task_inst'],render_workflow(w),'',self.packet['task_inst'])
        system,user=_build_single_submission_improvement_prompt(template=template,current_version=len(self.history),
            current_design=render_workflow(w),workspace_evidence=ev,history_rows=[],submission_label='incumbent',
            execution_metadata=None,output_mode='json',max_design_chars=16000,target_design_chars=6000)
        # Replace incompatible upstream output/save instructions rather than appending
        # a lower-priority competing contract. Both arms share this adaptation.
        user=user.split('\n\n4. Instructions\n\n',1)[0]
        before,after=user.split('# Save rules',1)
        user=before+after[after.index('--------------------------------'):]
        system=system.replace('improved_multi_agent_design','workflow')
        system=system.replace("Prioritize two improvements: (1) stronger agent-to-agent communication contracts "
            "for each subagent 'Output to orchestrator' schema, and "
            "(2) more orchestrator-subagent hops with explicit iterative recall/re-delegation "
            "instead of one-pass unidirectional execution.\n",'')
        adapter='''\nPILOT ADAPTER: Use the shared JSON workflow surface roles (map of names to instructions), contracts (map of sender.receiver to handoff requirements), order (list of role names; repeats allowed). Return exactly {"workflow": <complete workflow>, "rationale": "evidence-linked explanation"}. The workflow must be a JSON object, not a JSON-encoded string, with exactly roles, contracts, and order. Every contract endpoint must be a declared role name; order must include every declared role. Infrastructure, model, tools, evaluator and budget are fixed. Use preinstalled Python; uv installation is unavailable. No hidden benchmark feedback is provided. No-op is valid when no supported repair fits the scope. The common maximum workflow is 16000 UTF-8 bytes and eight roles.\n'''
        instructions={'integrated':'You may revise roles, contracts, and call order together.',
                      'local':'Change at most one existing role instruction. Preserve role roster, every contract and call order.',
                      'coordination':'Preserve roster. Choose one: change ONE sender.receiver contract and optionally those endpoint instructions, leaving order fixed; OR change call order/recalls while preserving all instructions and contracts. Diagnose lost, ambiguous or ignored information.',
                      'composer':'Use the two independent probe results to retain, merge, revise or reject the proposed repairs. Agreement alone is not correctness. You may change any workflow fields. The composed result will be executed before acceptance.'}
        schemas={
            'local':'Return exactly {"kind":"role","role":"one existing role name","instruction":"complete new instruction for that role","rationale":"evidence-linked explanation"}, or {"kind":"noop","rationale":"explanation"}. Do not return a complete workflow.',
            'coordination':'Return exactly one of: {"kind":"handoff","edge":"sender.receiver","contract":"complete new contract","endpoint_instructions":{"sender":"optional replacement instruction","receiver":"optional replacement instruction"},"rationale":"explanation"}; {"kind":"order","order":["existing role names, including recalls"],"rationale":"explanation"}; {"kind":"noop","rationale":"explanation"}. For a handoff patch use real role names as keys and include only endpoints whose instructions change. Do not return a complete workflow.'}
        if scope=='coordination':
            # Use actual names in the example: literal sender/receiver keys caused
            # otherwise meaningful model proposals to introduce undeclared roles.
            edge=next(iter(w['contracts']),None)
            if edge:
                sender,receiver=edge.split('.')
                schemas[scope]=schemas[scope].replace('"edge":"sender.receiver"',json.dumps('edge')+':'+json.dumps(edge))
                schemas[scope]=schemas[scope].replace('"sender":"optional replacement instruction","receiver":"optional replacement instruction"',
                    json.dumps(sender)+':"optional replacement instruction",'+json.dumps(receiver)+':"optional replacement instruction"')
        if scope in schemas:
            adapter=adapter.replace('Return exactly {"workflow": <complete workflow>, "rationale": "evidence-linked explanation"}.',schemas[scope])
        system+=adapter+'\nMANDATORY EDIT SCOPE: '+instructions[scope]
        user+='\nCurrent structured workflow:\n'+json.dumps(w)+'\nComparison history:\n'+json.dumps(self.history)
        if extra:user+='\nIndependent proposals and probes:\n'+json.dumps(extra)
        (self.root/f'{name}_prompt.json').write_text(json.dumps({'system':system,'user':user},indent=2))
        try:
            reply=self.g.chat(system,user);candidate=apply_proposal(reply,w,scope)
            decision={'valid':True,'workflow':candidate,'rationale':reply.get('rationale','')}
        except Exception as exc:
            candidate=copy.deepcopy(w);decision={'valid':False,'error':str(exc),'workflow':candidate}
        self.decisions.append({'stage':name,**decision})
        (self.root/f'{name}_decision.json').write_text(json.dumps(decision,indent=2))
        return candidate

    def compare(self,candidate,incumbent):
        self.g.set_stage('judge_'+candidate,self.c['algorithm']['judge_cap'])
        candidate_record=json.loads((self.root/candidate/'outcome.json').read_text())
        incumbent_record=json.loads((self.root/incumbent/'outcome.json').read_text())
        if not candidate_record['runnable']:
            d={'candidate':candidate,'incumbent':incumbent,'accepted':False,'rationale':'Candidate fails public standalone replay/artifact check'}
        else:
            # Randomize labels without exposing method or search-stage names to judge.
            labels=[candidate,incumbent]
            random.Random(20261023+self.comparisons).shuffle(labels);self.comparisons+=1
            a=evidence(self.root/labels[0],self.packet);b=evidence(self.root/labels[1],self.packet)
            user='# Task\n'+self.packet['task_inst']+'\n# Workspace A\n'+a+'\n# Workspace B\n'+b+pairwise_user_suffix()
            # Host absolute run paths could reveal candidate/incumbent labels; remove them.
            for name in (candidate,incumbent):user=user.replace(str((self.root/name).resolve()),'<workspace>')
            try:
                verdict=self.g.chat(pairwise_judge_system_for_query_num(0),user)
                if verdict.get('winner') not in ['A','B','tie']:raise ValueError('invalid winner')
                picked=None if verdict['winner']=='tie' else labels[0 if verdict['winner']=='A' else 1]
                d={'candidate':candidate,'incumbent':incumbent,'accepted':picked==candidate,'rationale':verdict.get('rationale',''),'labels':labels,'winner':verdict['winner']}
            except Exception as exc:d={'candidate':candidate,'incumbent':incumbent,'accepted':False,'rationale':'Judge failed: '+str(exc)}
        self.history.append(d)
        (self.root/'history.json').write_text(json.dumps(self.history,indent=2))
        return d['accepted']

    def run(self):
        w=json.loads((ROOT/'config/workflow.json').read_text());incumbent='reference'
        try:
            self.run_team(incumbent,w)
            for i in range(1,self.c['algorithm']['max_iterations']+1):
                if self.g.remaining<self.c['algorithm']['min_cycle_budget'][self.method]:break
                if self.method=='mass_workflow_search':
                    next_w=self.propose(f'round{i}_proposal',w,incumbent,'integrated')
                else:
                    a=self.propose(f'round{i}_local',w,incumbent,'local')
                    b=self.propose(f'round{i}_coordination',w,incumbent,'coordination')
                    self.run_team(f'round{i}_local_probe',a);self.run_team(f'round{i}_coordination_probe',b)
                    extra={'local':{'workflow':a,'evidence':evidence(self.root/f'round{i}_local_probe',self.packet)},
                           'coordination':{'workflow':b,'evidence':evidence(self.root/f'round{i}_coordination_probe',self.packet)}}
                    next_w=self.propose(f'round{i}_composer',w,incumbent,'composer',extra)
                candidate=f'round{i}_successor';self.run_team(candidate,next_w)
                if self.compare(candidate,incumbent):incumbent=candidate;w=next_w
            result=json.loads((self.root/incumbent/'outcome.json').read_text())
            commit={'method':self.method,'selected_stage':incumbent,'program_sha256':result['program_sha256'],
                    'runnable':result['runnable'],'cost_usd':self.g.charged,'team_executions':self.probe_count,
                    'valid_edits':sum(x['valid'] for x in self.decisions),'total_edits':len(self.decisions),
                    'comparisons':len(self.history),'workflow':w}
            (self.root/'commit.json').write_text(json.dumps(commit,indent=2));return commit
        finally:self.g.close()
