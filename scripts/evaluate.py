"""Invoke the host-only official grader after verifying a committed submission."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--task-id',type=int,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--science-env',type=Path,default=ROOT/'.venv-science');a=p.parse_args()
 root=a.run.resolve();commit=json.loads((root/'commit.json').read_text())
 if commit.get('task')!=a.task_id:raise ValueError('Task ID differs from committed run')
 selected=(root/commit['selected']).resolve()
 if not selected.is_relative_to(root):raise ValueError('Selected program escapes run directory')
 digest=hashlib.sha256((selected/'submission.py').read_bytes()).hexdigest()
 if digest!=commit.get('program_sha256'):raise ValueError('Committed program hash mismatch')
 if a.output.exists():raise ValueError('Evaluation output exists; never overwrite an official verdict')
 if a.output.resolve().is_relative_to(root):raise ValueError('Official grading must be outside the agent run directory')
 from mah2 import runtime
 runtime.SCIENCE=a.science_env.resolve();runtime.PYTHON=runtime.SCIENCE/'bin/python'
 # base_command's default captures the original environment; pass the grading env explicitly.
 original=runtime.base_command
 runtime.base_command=lambda work,data,extra=(),science=None: original(work,data,extra,science or runtime.SCIENCE)
 result=runtime.official_grade(a.task_id,selected,a.output,{'science_environment':str(runtime.SCIENCE)})
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
