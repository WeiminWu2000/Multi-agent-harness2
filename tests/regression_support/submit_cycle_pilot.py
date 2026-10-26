"""Audit completed integration, freeze the new study and start four Slurm workers."""
import argparse,datetime,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tests/regression_support'))
from report_cycle_pilot import cost

def retained_baseline_files(c):
 """Refuse historical reuse if the model, raw task, data or dollar cap differ."""
 names=[]
 for method,group in c.get('retained_methods',{}).items():
  if method!='mass_rhi' or c.get('input_profile')!='historical_task_only':
   raise RuntimeError('Retained baseline requires an explicit supported input audit')
  for task in c['tasks']:
   root=ROOT/'runs'/group/method/str(task)
   old=json.loads((root/'config.json').read_text());result=json.loads((root/'result.json').read_text())
   for key in ('model','provider_slug','reasoning','execution','task_environments','mass_commit','supports_seed'):
    if old.get(key)!=c.get(key):raise RuntimeError('Retained baseline differs: '+key)
   if old.get('public_context') or result['cap_usd']!=c['budget']['per_method_task_cap']:
    raise RuntimeError('Retained baseline context/budget mismatch')
   packet=json.loads((ROOT/f'private/tasks/{task}'/c['packet_name']).read_text())
   prompt=root/f'search/task_inputs/tasks/bare/query{1000+task}.txt'
   if not prompt.read_text().startswith(packet['task_inst']+'\n\n'):
    raise RuntimeError('Retained baseline task instruction differs')
   ready=json.loads((ROOT/c.get('readiness_manifest','provenance/task_readiness.json')).read_text())
   expected=next(r['input_manifest'] for r in ready['rows'] if r['task']==task)
   if json.loads((root/'input_manifest.json').read_text())!=expected:
    raise RuntimeError('Retained baseline public datasets differ')
   submission=Path(result['selected'])/'submission.py'
   if hashlib.sha256(submission.read_bytes()).hexdigest()!=result['program_sha256']:
    raise RuntimeError('Retained baseline submission changed')
   names.extend(str(p.relative_to(ROOT)) for p in (root/'config.json',root/'result.json',root/'input_manifest.json',prompt))
   names.append(str(Path('runs')/submission.resolve().relative_to((ROOT/'runs').resolve())))
  oldfreeze=json.loads((ROOT/f'provenance/{group}_freeze.json').read_text())
  if oldfreeze['source_hashes']['mah2/runtime.py']!=hashlib.sha256((ROOT/'mah2/runtime.py').read_bytes()).hexdigest():
   raise RuntimeError('Grading/replay runtime differs from retained baseline; audit required')
 return names

def safe_fixture_rejections(root,depth):
 """Audit known model-limit fallbacks without accepting a changed invalid harness."""
 allowed={'GLM coordination call limit reached',
          "Harness changes must cite this stage's executed structured public check as public_check_probe"}
 valid_coordination=0
 for index in range(1,depth+1):
  directory=root/'optimization'/f'round_{index}'
  base=json.loads((directory/'reference_harness.json').read_text())
  for stage in ('proposal_a','proposal_b','composer'):
   decision=json.loads((directory/(stage+'_decision.json')).read_text())
   if decision.get('valid'):
    if stage=='proposal_b':valid_coordination+=1
   elif decision.get('error') not in allowed or decision.get('harness')!=base:
    return False
 return valid_coordination>0

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',default='config/cycles10.json');p.add_argument('--calibrate-missing',action='store_true');a=p.parse_args()
 c=json.loads((ROOT/a.config).read_text())
 if c.get('candidate_parent_group'):
  raise RuntimeError('Cached review configuration: use scripts/review_cycle_candidates.py; do not regenerate its paid parent pool')
 if a.calibrate_missing:
  for method in c['methods']:
   attempts=sorted((ROOT/'runs'/c.get('calibration_groups',{}).get(method,c['calibration_group'])/method).glob('*'))
   if attempts:
    if not all((r/'result.json').exists() for r in attempts):raise RuntimeError('A calibration is still active; wait before launch')
    if not json.loads((attempts[-1]/'result.json').read_text()).get('fixture_passed'):raise RuntimeError('Existing live fixture failed; benchmark not launched')
    continue
   subprocess.run(['srun',f"--jobid={c.get('slurm_job_id','9623694')}",'--overlap','--exact','-N1','-n1','-c4','--mem=32G','--gres=none','--cpu-bind=cores',str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_cycle_pilot.py'),'--config',a.config,'--calibrate','--method',method],cwd=ROOT,check=True)
 rows=[]
 for method in c['methods']:
  attempts=sorted((ROOT/'runs'/c.get('calibration_groups',{}).get(method,c['calibration_group'])/method).glob('*'))
  if not attempts:raise RuntimeError('Missing live calibration for '+method+'; benchmark not launched')
  root=attempts[-1]
  r=json.loads((root/'result.json').read_text());checks=[]
  for p in root.rglob('outcome.json'):
   f=p.parent/'replay/pred_results/join.csv'
   checks.append(f.exists() and f.read_text()=='id,value,label\n1,10,A\n2,20,B\n')
  depth=c.get('outer_cycles',2)
  expected={'plain_ds_star':1,'whole_team_harness2':4*depth,'multi_agent_harness2':4*depth,'mass_rhi':4,'codex_coordination_harness2':4*depth}[method]
  passed=r['fixture_passed'] and len(checks)==expected and all(checks)
  fixture_config=json.loads((root/'config.json').read_text())
  if c.get('require_calibration_hashes'):
   hashes=fixture_config.get('calibration_source_hashes',{})
   passed=passed and bool(hashes) and all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in hashes.items())
  passed=passed and all(fixture_config.get(key)==c.get(key) for key in (('mass_rhi' if method=='mass_rhi' else 'dsstar'),'model','provider_slug','reasoning','execution','initial_workflow','public_context','packet_name','input_profile'))
  if method in ('whole_team_harness2','multi_agent_harness2','codex_coordination_harness2'):
   edits_ok=r['valid_edits']==r['total_edits']==3*depth
   if c.get('allow_safe_fixture_rejections'):
    if not c['dsstar'].get('scoped_glm_coordination'):raise RuntimeError('Safe-fallback fixture audit is scoped to the prospective GLM control')
    edits_ok=r['total_edits']==3*depth and safe_fixture_rejections(root,depth)
   passed=passed and edits_ok
  if method in ('whole_team_harness2','multi_agent_harness2','codex_coordination_harness2') and c['dsstar'].get('public_probes'):passed=passed and r.get('public_probe_fixture_passed',False)
  rows.append({'method':method,'passed':passed,'replay_checks':checks,'cost':{k:sum(cost(p)[k] for p in attempts) for k in cost(root)},'cycles_completed':r['cycles_completed']})
 passed=all(r['passed'] for r in rows) and sum(cost(p)['total_upper_usd'] for group in c.get('shared_calibration_groups',[c['calibration_group']]) for p in (ROOT/'runs'/group).glob('*/*') if p.is_dir())<=c['budget']['calibration_cap']
 audit={'passed':passed,'rows':rows};(ROOT/f"results/{c['calibration_group']}.json").write_text(json.dumps(audit,indent=2)+'\n')
 if not passed:raise RuntimeError('Calibration failed; benchmark not launched')
 subprocess.run([str(ROOT/'.venv/bin/python'),'-m','unittest','discover','-s','tests'],cwd=ROOT,check=True)
 if not json.loads((ROOT/c.get('readiness_manifest','provenance/task_readiness.json')).read_text())['passed']:raise RuntimeError('Task readiness failed')
 names=[a.config,'config/workflow.json',c.get('readiness_manifest','provenance/task_readiness.json')]+retained_baseline_files(c)
 for directory in ('mah2','scripts','tests','vendor/mass','vendor/harness2/harness2','vendor/ds-star'):
  names.extend(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*.py'))
 registry=json.loads((ROOT/'private/task_registry.json').read_text())
 names.append('private/task_registry.json')
 names.extend(registry[str(task)]['grader'] for task in c['tasks'])
 if c.get('selection_manifest'):names.append(c['selection_manifest'])
 if c['dsstar'].get('codex_coordination'):names.append(c['dsstar']['codex_coordination']['binary'])
 names.extend(['.runtime/node/bin/node','.runtime/node_modules/@qwen-code/qwen-code/cli-entry.js','.runtime/package-lock.json'])
 names.extend(str(p.relative_to(ROOT)) for p in (ROOT/'private/tasks').glob('*/packet*.json'))
 names.extend(str(p.relative_to(ROOT)) for p in (ROOT/'provenance').glob('*requirements.txt'))
 existing=sum(cost(p)['total_upper_usd'] for group in c.get('shared_run_groups',[c['run_group']])+c.get('shared_calibration_groups',[c['calibration_group']]) for p in (ROOT/'runs'/group).glob('*/*') if p.is_dir())
 if existing+len(c['tasks'])*len(c['methods'])*c['budget']['per_method_task_cap']>c['budget']['total_cap']:raise RuntimeError('Launch would exceed configured total dollar ceiling')
 freeze={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_hashes':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in sorted(set(names))},'budget_usd':c['budget']['total_cap'],'calibration':audit,'mass_commit':c['mass_commit'],'harness2_commit':'1cfe254e8d25b15f37048c3730134686abe60335','dsstar_commit':'6c05b01e30f01489af12708e99eda932e44d10ba','old_adapter_commit':c['dsstar']['recovered_commit']}
 p=ROOT/f"provenance/{c['run_group']}_freeze.json"
 with p.open('x') as f:json.dump(freeze,f,indent=2)
 command=['srun',f"--jobid={c.get('slurm_job_id','9623694')}",'--overlap','--exact','-N1',f"-n{c['concurrency']}",f"-c{c.get('slurm_cpus_per_worker',4)}",f"--mem={32*c['concurrency']}G",'--gres=none','--cpu-bind=cores',c.get('slurm_time','--time=07:00:00'),str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/dispatch_cycle_pilot.py'),'--config',a.config]
 jobs={'allocation':str(c.get('slurm_job_id','9623694')),'concurrency':c['concurrency'],'command':command,'order':[{'index':i,'task':t,'method':m} for i,(t,m) in enumerate((t,m) for t in c['tasks'] for m in c['methods'])]}
 (ROOT/f"provenance/{c['run_group']}_jobs.json").write_text(json.dumps(jobs,indent=2)+'\n')
 subprocess.run(command,cwd=ROOT,check=True)
if __name__=='__main__':main()
