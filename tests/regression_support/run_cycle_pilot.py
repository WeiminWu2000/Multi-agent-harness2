"""Canonical three-method, two-cycle ScienceAgentBench pilot worker."""
import argparse,copy,hashlib,json,os,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from mah2.gateway import Gateway,BudgetExceeded
from mah2.runtime import hashes,official_grade
from mah2.dsstar import provider
from mah2.dsstar.harness import initial
from mah2.dsstar.rollout import Rollout
from mah2.dsstar.recursion import run_recursive
from mah2.dsstar.optimizer import Experiment
from mah2.mass_rhi import run as mass_run
from mah2.task_context import input_packet
from mah2.public_evidence import has_public_check

class StudyGateway(Gateway):
    def request(self,payload):
        try:return super().request(payload)
        except BudgetExceeded as exc:
            with (self.directory/'budget_denials.jsonl').open('a') as f:
                f.write(json.dumps({'stage':self.stage,'error':str(exc)})+'\n')
            raise

def verify_freeze(c):
    d=json.loads((ROOT/f"provenance/{c['run_group']}_freeze.json").read_text())
    for name,sha in d['source_hashes'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha:raise RuntimeError('Frozen source changed: '+name)
    if not json.loads((ROOT/f"results/{c['calibration_group']}.json").read_text())['passed']:
        raise RuntimeError('Live integration gate has not passed')

def execute(method,task,c,calibrate=False,attempt=0):
    if c.get('candidate_parent_group'):
        raise ValueError('Use scripts/review_cycle_candidates.py for a cached candidate review')
    if not calibrate:verify_freeze(c)
    label=str(task)+(f'_attempt{attempt}' if attempt else '')
    root=(ROOT/'runs'/(c['calibration_group'] if calibrate else c['run_group'])/method/label).resolve()
    cap=c['calibration_caps'][method] if calibrate else c['budget']['per_method_task_cap']
    if attempt:
        if not calibrate:raise ValueError('Only integration fixtures can be repeated')
        from report_cycle_pilot import cost
        prior=list((ROOT/'runs'/c['calibration_group']).glob('*/*'))
        if any(not (p/'result.json').exists() for p in prior if p.is_dir()):raise RuntimeError('Wait for all prior calibration workers')
        cap=min(cap,round(c['budget']['calibration_cap']-sum(cost(p)['total_upper_usd'] for p in prior if p.is_dir())-0.000001,8))
        if cap<=0:raise RuntimeError('Combined calibration allowance exhausted')
    if calibrate and c.get('shared_calibration_groups'):
        from report_cycle_pilot import cost
        prior=[p for group in c['shared_calibration_groups'] for p in (ROOT/'runs'/group).glob('*/*') if p.is_dir()]
        if any(not (p/'result.json').exists() for p in prior):raise RuntimeError('Shared calibration still active')
        cap=min(cap,c['budget']['calibration_cap']-sum(cost(p)['total_upper_usd'] for p in prior)-.000001)
        if cap<=0:raise RuntimeError('Combined calibration allowance exhausted')
    root.mkdir(parents=True,exist_ok=False)
    if calibrate:
        data=ROOT/'private/cycles10_fixture';data.mkdir(parents=True,exist_ok=True)
        (data/'a.csv').write_text('id,value\n2,20\n1,10\n');(data/'b.csv').write_text('id,label\n1,A\n2,B\n')
        packet={'task_inst':'Join a.csv and b.csv on id. Sort by id; write pred_results/join.csv with columns id,value,label.','output_fname':'pred_results/join.csv'}
    else:
        data=ROOT/f'private/tasks/{task}/data';packet=json.loads((data.parent/c.get('packet_name','packet.json')).read_text())
        readiness=json.loads((ROOT/c.get('readiness_manifest','provenance/task_readiness.json')).read_text())
        expected=next(r['input_manifest'] for r in readiness['rows'] if r['task']==task)
        if hashes(data.resolve())!=expected:raise RuntimeError('Public input manifest changed')
    packet=input_packet(packet,c.get('input_profile'))
    (root/'input_packet.json').write_text(json.dumps(packet,indent=2))
    c=copy.deepcopy(c);c['science_environment']=c.get('task_environments',{}).get(str(task),'.venv-science')
    if calibrate:
        sources=list((ROOT/'mah2').rglob('*.py'))+[Path(__file__).resolve()]
        c['calibration_source_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (root/'config.json').write_text(json.dumps(c,indent=2));(root/'input_manifest.json').write_text(json.dumps(hashes(data.resolve()),indent=2))
    g=StudyGateway(root/'api',c,cap=cap).start();provider.ACTIVE_GATEWAY=g
    depth=c.get('outer_cycles',2)
    info={'task':task,'method':method,'cap_usd':cap,'cycles_requested':0 if method=='plain_ds_star' else (c['mass_rhi']['iterations'] if method=='mass_rhi' else depth),'cycles_attempted':0,'cycles_completed':0,'selected':None}
    try:
        if method=='mass_rhi':info.update(mass_run(g,c,packet,data,root/'search',task,c['budget']['per_method_task_cap'] if calibrate else cap))
        else:
            dc={**c['dsstar'],'science_environment':c['science_environment'],'allowance_usd':c['budget']['per_method_task_cap'] if calibrate else cap,'input_per_million':c['budget']['input_per_million'],'output_per_million':c['budget']['output_per_million']}
            if method=='plain_ds_star':
                client=provider.Client(dc,provider.Budget(cap),root/'ledger.jsonl')
                result=Rollout(client,initial(),dc,root/'rollout',data).run(packet)
                info.update(selected=str(root/'rollout'),team_executions=1)
            else:
                run_recursive(dc,root/'optimization','multi_agent' if method=='multi_agent_harness2' else 'whole_team',packet,data,[],depth)
                info.update(selected=str(root/'optimization/successor'),cycles_attempted=depth,cycles_completed=depth,team_executions=4*depth)
                for n in range(1,depth+1):
                    rd=root/f'optimization/round_{n}'
                    if n==2 and not dc.get('runnable_fallback'):
                        assert json.loads((rd/'reference_harness.json').read_text())==json.loads((root/'optimization/round_1/composer_decision.json').read_text())['harness']
    except Exception as exc:
        info.update(error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    finally:
        g.close();provider.ACTIVE_GATEWAY=None
    denials=root/'api/budget_denials.jsonl'
    denied=[json.loads(x) for x in denials.read_text().splitlines()] if denials.exists() else []
    info['budget_truncated']=bool(denied)
    if method in ('whole_team_harness2','multi_agent_harness2','codex_coordination_harness2'):
        attempted=[p for p in (root/'optimization').glob('round_*') if p.is_dir()]
        info['cycles_attempted']=len(attempted)
        info['cycle_details']=[]
        for rd in sorted(attempted):
            base=rd/'reference_harness.json';decision=rd/'composer_decision.json'
            base_h=json.loads(base.read_text()) if base.exists() else None
            next_h=json.loads(decision.read_text()).get('harness') if decision.exists() else None
            info['cycle_details'].append({'round':rd.name,'harness_changed':base_h!=next_h if next_h is not None else None,'charged_or_reserved_usd':sum(x['charged_usd'] for x in g.calls if x['stage'].startswith(rd.name+'/')),'successor_committed':(rd/'commit.json').exists()})
        info['cycles_completed']=sum((p/'commit.json').exists() and not any(r['stage'].startswith(p.name+'/') for r in denied) for p in attempted)
        info['valid_edits']=sum(json.loads(p.read_text()).get('valid',False) for p in (root/'optimization').glob('round_*/*_decision.json'))
        info['total_edits']=len(list((root/'optimization').glob('round_*/*_decision.json')))
    if method=='mass_rhi':
        info['cycles_attempted']=len(list((root/'search/search').glob('*/updated_queries/*-v*.txt')))
        if info.get('error'):
            # An evaluated v1 precedes the v2 proposal; never invent a completed v2 comparison.
            info['cycles_completed']=int(info['cycles_attempted']>=2)
        if denied:
            initial_denial=any(r['stage'].endswith(('_bare','_v0')) or r['stage']=='rhi_v0' for r in denied)
            bad_rounds=set()
            for r in denied:
                for n in (1,2):
                    if r['stage'].endswith(f'_v{n}') or r['stage']==f'rhi_v{n}':bad_rounds.add(n)
            info['cycles_completed']=0 if initial_denial else sum(n not in bad_rounds for n in range(1,info['cycles_completed']+1))
    if c['dsstar'].get('codex_coordination') and method=='codex_coordination_harness2':
        from mah2.dsstar.codex_editor import usage
        info['codex_usage']=usage(root)
        info['total_model_cost_usd']=None
        info['cost_note']='GLM dollars plus separately metered Codex usage; not equal-total-cost'
    info['charged_or_reserved_usd']=g.charged
    info['provider_reported_usd']=sum(float(r.get('usage',{}).get('cost') or 0) for r in g.calls)
    info['status']='budget_truncated' if denied else ('error' if info.get('error') else 'completed')
    selected=Path(info['selected']) if info['selected'] else None
    info['runnable']=bool(selected and json.loads((selected/'outcome.json').read_text())['runnable'])
    if info['runnable']:
        sha=hashlib.sha256((selected/'submission.py').read_bytes()).hexdigest()
        assert sha==json.loads((selected/'outcome.json').read_text())['program_sha256']
        info['program_sha256']=sha
    (root/'commit.json').write_text(json.dumps(info,indent=2))
    if calibrate:
        f=selected/'replay/pred_results/join.csv' if selected else None
        info['fixture_passed']=bool(info['status']=='completed' and info['runnable'] and f.read_text()=='id,value,label\n1,10,A\n2,20,B\n' and (method=='plain_ds_star' or info['cycles_completed']==info['cycles_requested']))
        if method in ('whole_team_harness2','multi_agent_harness2','codex_coordination_harness2') and dc.get('public_probes'):
            try:
                probe=Experiment(dc,root/'probe_integration');probe.data=data
                (probe.root/'selected').symlink_to(selected.resolve(),target_is_directory=True)
                code=("import pandas as pd\nfrom pathlib import Path\nimport json\n"
                    "expected=pd.read_csv('data/a.csv').merge(pd.read_csv('data/b.csv'),on='id').sort_values('id').reset_index(drop=True)\n"
                    "actual=pd.read_csv('outputs/P1/join.csv')\npd.testing.assert_frame_equal(actual,expected)\n"
                    "assert Path('programs/P1.py').is_file()\n"
                    +f"assert not Path({str(ROOT/'private/task_registry.json')!r}).exists()\n"
                    +"print('PUBLIC_PROBE_FIXTURE_PASS')\n"
                    +"print(json.dumps({'check':{'kind':'public_requirement','criterion':'exact joined output','protocol':'recompute the join from public inputs and compare all rows','observations':{'rows':len(actual),'equal':actual.equals(expected)}}},indent=2))\n")
                checked=probe.public_probe(code,'fixture',{'P1':'selected'})
                info['public_probe_fixture_passed']=has_public_check(checked) and 'PUBLIC_PROBE_FIXTURE_PASS' in checked['stdout']
            except (OSError,RuntimeError,ValueError,AttributeError) as exc:
                info['public_probe_fixture_passed']=False;info['public_probe_fixture_error']=str(exc)
            info['fixture_passed']=info['fixture_passed'] and info['public_probe_fixture_passed']
    if calibrate and method=='codex_coordination_harness2':
        u=info['codex_usage']
        info['codex_fixture_passed']=u['calls']>=depth and u['failed_calls']==0 and u['usage_missing_calls']==0
        info['fixture_passed']=info['fixture_passed'] and info['codex_fixture_passed']
    if not calibrate:
        grade=official_grade(task,selected,ROOT/'private'/c['evaluation_group']/method/str(task),c) if selected else {'status':'no_submission','official_success':0}
        info['grade']=grade
    (root/'result.json').write_text(json.dumps(info,indent=2));print(json.dumps(info),flush=True)
    return info

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='config/cycles10.json');p.add_argument('--index',type=int);p.add_argument('--calibrate',action='store_true');p.add_argument('--method');p.add_argument('--attempt',type=int,default=0);a=p.parse_args()
    if not os.environ.get('SLURM_JOB_ID') or int(os.environ.get('SLURM_CPUS_PER_TASK',0))!=4 or int(os.environ.get('SLURM_MEM_PER_NODE',0))<32768:raise RuntimeError('Requires 4 CPUs and 32GB Slurm allocation')
    c=json.loads((ROOT/a.config).read_text())
    if a.calibrate:
        if a.method not in c['methods']:p.error('Select calibration method')
        execute(a.method,999,c,True,a.attempt)
    else:
        if a.index is None or not 0<=a.index<len(c['tasks'])*len(c['methods']):p.error('Index outside configured task/method range')
        execute(c['methods'][a.index%len(c['methods'])],c['tasks'][a.index//len(c['methods'])],c)
if __name__=='__main__':main()
