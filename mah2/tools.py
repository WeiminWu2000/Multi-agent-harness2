"""Setup, preflight and run inspection commands for users of the built-in team."""
import argparse,json,os,shutil,subprocess,sys,venv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def setup(argv=None):
 p=argparse.ArgumentParser(description='Install pinned prompt dependencies and create a scientific Python environment. No API calls.');p.add_argument('--include-mass',action='store_true');p.add_argument('--science-env',type=Path,default=ROOT/'.venv-science');a=p.parse_args(argv)
 import importlib.util
 spec=importlib.util.spec_from_file_location('mah2_dependency_setup',ROOT/'scripts/fetch_dependencies.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 saved=sys.argv
 try:
  sys.argv=['fetch_dependencies.py']+(['--include-mass'] if a.include_mass else []);module.main()
 finally:sys.argv=saved
 env=a.science_env.resolve()
 if env.exists() and not (env/'bin/python').is_file():p.error('Existing science environment is incomplete; inspect it manually')
 if not env.exists():venv.EnvBuilder(with_pip=True).create(env)
 elif subprocess.run([str(env/'bin/python'),'-m','pip','--version'],capture_output=True).returncode:
  subprocess.run([str(env/'bin/python'),'-m','ensurepip','--upgrade'],check=True)
 print('Scientific environment:',env)
 print('Next: mah2 check --offline; install task-specific packages into the science environment.')
 return 0

def check(argv=None):
 p=argparse.ArgumentParser(description='Check the local prerequisites without making model calls.');p.add_argument('--offline',action='store_true',help='Do not require a provider credential');p.add_argument('--method',choices=['base','harness2','mass','codex'],default='harness2');p.add_argument('--science-env',type=Path,default=ROOT/'.venv-science');a=p.parse_args(argv)
 checks={'Linux':sys.platform=='linux','bubblewrap':bool(shutil.which('bwrap')),'scientific Python':(a.science_env/'bin/python').is_file(),'DS-STAR prompts':(ROOT/'vendor/ds-star/agents/prompts.py').is_file(),'Harness2 prompts':(ROOT/'vendor/harness2/harness2/core/prompts.py').is_file()}
 if not a.offline:
  try:
   from .gateway import load_api_key
   load_api_key();checks['provider credential configured']=True
  except (RuntimeError,OSError):checks['provider credential configured']=False
 if a.method=='mass':checks.update({'MASS checkout':(ROOT/'vendor/mass/mass/pipeline.py').is_file(),'Qwen-code runtime':(ROOT/'.runtime/node_modules/@qwen-code/qwen-code/cli-entry.js').is_file(),'Node runtime':(ROOT/'.runtime/node/bin/node').is_file()})
 if a.method=='codex':checks.update({'Codex executable':bool(shutil.which(os.environ.get('MAH2_CODEX_BINARY','codex'))),'Codex auth file':Path(os.environ.get('MAH2_CODEX_AUTH_FILE','/nonexistent')).is_file()})
 for name,ok in checks.items():print(f'{"OK" if ok else "MISSING"}: {name}')
 print('No API request sent; endpoint access and live model behavior are not verified.')
 return 0 if all(checks.values()) else 1

def init(argv=None):
 p=argparse.ArgumentParser(description='Create a task packet and an empty public-data directory.');p.add_argument('directory',type=Path);a=p.parse_args(argv)
 if a.directory.exists():p.error('Directory exists; existing tasks are never overwritten')
 a.directory.mkdir(parents=True);(a.directory/'data').mkdir()
 task={'task_inst':'Describe the analysis to perform on the files in data/. Specify column meanings, scientific requirements, and the required output.','output_fname':'pred_results/result.csv'}
 (a.directory/'task.json').write_text(json.dumps(task,indent=2)+'\n')
 print('Edit',a.directory/'task.json','and put public input files in',a.directory/'data')
 return 0

def report(argv=None):
 p=argparse.ArgumentParser(description='Read a saved run without executing models or selecting a different program.');p.add_argument('--run',type=Path,required=True);a=p.parse_args(argv)
 root=a.run.resolve();f=root/'result.json'
 if not f.exists():p.error('No final result.json yet; the run is unfinished or failed before finalization')
 r=json.loads(f.read_text());print('Method:',r.get('method'));print('Status:',r.get('status'));print('Reported GLM cost: $'+format(r.get('provider_reported_usd',0),'.6f'));print('Evaluation:',r.get('evaluation','not_run'))
 if r.get('selected'):
  selected=(root/r['selected']).resolve()
  if not selected.is_relative_to(root):p.error('Selected artifact escapes this run')
  print('Program:',selected/'submission.py');print('Deliverables:',selected/'replay/pred_results')
 for rd in sorted((root/'optimization').glob('round_*')):
  selection=rd/'selection.json'
  if selection.exists():
   s=json.loads(selection.read_text());print(rd.name+':',s.get('selected_stage'),'; valid selection:',s.get('valid'))
 if r.get('codex_usage'):print('Codex usage (additional, USD unknown):',json.dumps(r['codex_usage']))
 return 0
