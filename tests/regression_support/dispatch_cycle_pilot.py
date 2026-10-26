"""Atomic work claims; one active task per Slurm rank, no restart of partial runs."""
import argparse,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def worker_cpu_mask(allowed,rank,workers,cpus=4):
 """Handle either per-rank CPU masks or the cluster's shared step mask."""
 allowed=sorted(allowed)
 if not 0<=rank<workers:raise RuntimeError('Worker rank outside configured concurrency')
 if len(allowed)==cpus:return allowed
 if len(allowed)>=cpus*workers:return allowed[rank*cpus:(rank+1)*cpus]
 raise RuntimeError('Insufficient CPU mask for isolated workers')

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',default='config/cycles10.json');a=p.parse_args()
 rank=int(os.environ['SLURM_PROCID']);c=json.loads((ROOT/a.config).read_text())
 before=sorted(os.sched_getaffinity(0))
 masks=c.get('worker_cpu_masks')
 selected=masks[rank] if masks else worker_cpu_mask(before,rank,c['concurrency'])
 if not set(selected)<=set(before):raise RuntimeError('Configured CPU mask is outside allocated CPUs')
 os.sched_setaffinity(0,selected)
 if sorted(os.sched_getaffinity(0))!=selected:raise RuntimeError('Worker CPU binding failed')
 if len(selected)!=4:raise RuntimeError('Worker must have exactly four assigned CPUs')
 os.environ['SLURM_CPUS_PER_TASK']='4'
 claims=ROOT/f"private/{c['run_group']}_dispatch";claims.mkdir(exist_ok=True)
 (claims/f'rank_{rank}_affinity.json').write_text(json.dumps({'rank':rank,'before':before,'after':selected}))
 for index in range(len(c['tasks'])*len(c['methods'])):
  if (claims/'stop_new_work.json').exists():break
  if rank>=2 and (claims/'rate_limit_throttle.json').exists():break
  task=c['tasks'][index//len(c['methods'])];method=c['methods'][index%len(c['methods'])]
  if (ROOT/'runs'/c['run_group']/method/str(task)).exists():continue
  try:log=(claims/f'{index}.log').open('x')
  except FileExistsError:continue
  with log:
   print(json.dumps({'rank':rank,'index':index,'task':task,'method':method,'event':'start'}),flush=True)
   r=subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_cycle_pilot.py'),'--config',a.config,'--index',str(index)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
  runroot=ROOT/'runs'/c['run_group']/method/str(task)
  runroot.mkdir(parents=True,exist_ok=True)
  (runroot/'worker_exit.json').write_text(json.dumps({'returncode':r.returncode}))
  ledger=runroot/'api/ledger.jsonl'
  if ledger.exists() and any(json.loads(x).get('http_status')==429 for x in ledger.read_text().splitlines() if x):
   (claims/'rate_limit_throttle.json').write_text(json.dumps({'reason':'HTTP 429 observed; ranks 2 and 3 stop taking new work after their active run','index':index}))
  print(json.dumps({'rank':rank,'index':index,'exit_code':r.returncode}),flush=True)
  # One writer updates the report at a time.
  import fcntl
  with (claims/'report.lock').open('w') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/report_cycle_pilot.py'),'--config',a.config],cwd=ROOT,stdout=subprocess.DEVNULL)

if __name__=='__main__':main()
