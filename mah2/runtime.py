"""Qwen-code execution and official grading, with isolated files and network."""
import ast,hashlib,json,os,resource,shutil,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCIENCE=ROOT/'.venv-science'
PYTHON=SCIENCE/'bin/python'
BWRAP=shutil.which('bwrap')


def hashes(directory):
    return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(directory).rglob('*')) if p.is_file() and not p.is_symlink()}


def base_command(work,data,extra=(),science=SCIENCE):
    if BWRAP is None: raise RuntimeError('bubblewrap (bwrap) is required; unsandboxed execution is not supported')
    science=Path(science).expanduser().resolve()
    work=Path(work).absolute();work.mkdir(parents=True,exist_ok=True)
    (work/'pred_results').mkdir(exist_ok=True)
    cmd=[BWRAP,'--unshare-all','--die-with-parent','--new-session','--clearenv',
         '--proc','/proc','--dev','/dev','--tmpfs','/tmp']
    interpreter_root=(science/'bin/python').resolve().parents[1]
    link_root=interpreter_root
    for p in dict.fromkeys(['/usr','/bin','/lib','/lib64','/etc/ld.so.cache',sys.base_prefix,str(interpreter_root),str(link_root),str(science)]):
        if Path(p).exists():cmd+=['--ro-bind',p,p]
    cmd+=['--bind',str(work),'/work','--ro-bind',str(Path(data).resolve()),'/work/data',
          '--ro-bind',str(Path(data).resolve()),'/work/datasets','--chdir','/work']
    for k,v in {'PATH':str(science/'bin')+':/usr/bin:/bin','HOME':'/tmp','PYTHONNOUSERSITE':'1',
                'OMP_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4','MPLCONFIGDIR':'/tmp/mpl',
                'CUDA_VISIBLE_DEVICES':'','QWEN_TELEMETRY_ENABLED':'false',
                'QWEN_CODE_SUPPRESS_YOLO_WARNING':'1','NO_PROXY':'127.0.0.1,localhost'}.items():
        cmd+=['--setenv',k,v]
    return cmd+list(extra)


def run_process(cmd,logs,seconds):
    logs=Path(logs);logs.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE,(128*2**20,)*2)
        resource.setrlimit(resource.RLIMIT_CPU,(seconds*4+5,)*2)
    with (logs/'stdout.txt').open('w') as out,(logs/'stderr.txt').open('w') as err:
        p=subprocess.Popen(cmd,stdout=out,stderr=err,start_new_session=True,preexec_fn=limits)
        timeout=False
        try:p.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timeout=True;os.killpg(p.pid,signal.SIGKILL);p.wait()
    def excerpt(name):
        with (logs/name).open('rb') as f:return f.read(65536).decode(errors='replace')
    return {'returncode':p.returncode,'timeout':timeout,'seconds':time.monotonic()-start,
            'stdout':excerpt('stdout.txt'),'stderr':excerpt('stderr.txt')}


def render_workflow(w):
    return 'Create an agent team with following agent candidates to solve this problem:\n'+json.dumps(w,indent=2)


def episode(gateway,workflow,packet,data,directory,config,prompt_override=None):
    science=ROOT/config.get('science_environment','.venv-science');python=science/'bin/python'
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    work=directory/'work';work.mkdir()
    prompt=(packet['task_inst']+'\n\n'+render_workflow(workflow)+'''
Execution requirements: execute every listed role through a real agent tool call (general-purpose subagent), in foreground order. Do not simulate roles. The orchestrator delegates, checks and integrates. Use the provided Python environment; dependencies are already installed. Public input is in ./data, also aliased as ./datasets. Network is unavailable except the model gateway. Produce a complete standalone submission.py that recreates all required outputs in pred_results from public inputs in a clean workspace. Keep logs.txt with actual delegation and checks. Do not depend on files from previous executions. Do not access private graders or fabricate results. This is a small inference budget: inspect inputs concisely, make concrete progress and finalize promptly.\n''')
    if prompt_override is not None:prompt=prompt_override
    (directory/'prompt.txt').write_text(prompt)
    (directory/'workflow.json').write_text(json.dumps(workflow,indent=2))
    (directory/'input_manifest.json').write_text(json.dumps(hashes(Path(data).resolve()),indent=2))
    settings={'$version':4,'env':{'VLLM_API_KEY':gateway.token},'modelProviders':{'openai':[{
        'id':config['model'],'envKey':'VLLM_API_KEY','baseUrl':'http://127.0.0.1:8001/v1',
        'generationConfig':{'timeout':180000,'maxRetries':0,'contextWindowSize':262144,
                            'samplingParams':{'temperature':0.6,'top_p':0.95,'max_tokens':8192}}}]},
        'security':{'auth':{'selectedType':'openai'}},'model':{'name':config['model']},
        'tools':{'shell':{'defaultTimeoutMs':180000}},'telemetry':{'enabled':False}}
    (directory/'settings.json').write_text(json.dumps(settings))
    extra=['--ro-bind',str(ROOT/'.runtime'),'/opt/qwen','--ro-bind',str(ROOT/'mah2/relay.py'),'/opt/relay.py',
           '--ro-bind',str(gateway.socket_path),'/gateway.sock','--ro-bind',str(directory/'settings.json'),'/settings.json',
           '--ro-bind',str(directory/'prompt.txt'),'/prompt.txt','--setenv','QWEN_HOME','/tmp/qwen_home',
           '--setenv','VLLM_API_KEY',gateway.token,
           '--setenv','PATH',str(science/'bin')+':/opt/qwen/node/bin:/opt/qwen/node_modules/.bin:/usr/bin:/bin']
    command=base_command(work,data,extra,science)+[str(python),'/opt/relay.py','/opt/qwen/node/bin/node',
             '/opt/qwen/node_modules/@qwen-code/qwen-code/cli-entry.js','--model',config['model'],
             '--approval-mode','yolo','--output-format','stream-json']
    outcome=run_process(command,directory/'logs',config['execution']['rollout_seconds'])
    replay={'returncode':None,'stderr':'No standalone submission.py'}
    source=work/'submission.py'
    if source.is_file() and not source.is_symlink():
        code=source.read_text();(directory/'submission.py').write_text(code)
        replay_dir=directory/'replay';replay_dir.mkdir();(replay_dir/'submission.py').write_text(code)
        try:
            ast.parse(code)
            replay=run_process(base_command(replay_dir,data,science=science)+[str(python),'submission.py'],
                               directory/'replay_logs',config['execution']['replay_seconds'])
        except SyntaxError as exc:replay={'returncode':1,'stderr':str(exc)}
    artifact=directory/'replay'/packet['output_fname']
    runnable=(replay['returncode']==0 and artifact.is_file() and not artifact.is_symlink()
              and artifact.resolve().is_relative_to((directory/'replay').resolve()))
    record={'agent':outcome,'replay':replay,'runnable':runnable,
            'program_sha256':hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() and not source.is_symlink() else None,
            'artifacts':hashes(directory/'replay/pred_results') if (directory/'replay/pred_results').exists() else {}}
    (directory/'outcome.json').write_text(json.dumps(record,indent=2))
    return record


def official_grade(task,selected,out,config):
    """Called only after commitment; gold targets never enter optimizer evidence."""
    selected=Path(selected);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    record=json.loads((selected/'outcome.json').read_text())
    if not record['runnable']:result={'status':'no_submission','official_success':0}
    else:
        registry=json.loads((ROOT/'private/task_registry.json').read_text())[str(task)]
        data=out/'grade_data';(data/'eval_programs').mkdir(parents=True)
        shutil.copytree(ROOT/'private/benchmark/eval_programs/gold_results',data/'eval_programs/gold_results')
        (data/'datasets'/registry['folder']).mkdir(parents=True)
        work=out/'work';work.mkdir()
        (work/'pred_results').mkdir()
        for source in (selected/'replay/pred_results').rglob('*'):
            if source.is_file() and not source.is_symlink() and source.resolve().is_relative_to((selected/'replay/pred_results').resolve()):
                dest=work/'pred_results'/source.relative_to(selected/'replay/pred_results')
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        (work/'benchmark').symlink_to('/work/data',target_is_directory=True)
        (work/'grader.py').write_bytes((ROOT/registry['grader']).read_bytes())
        public=ROOT/f'private/tasks/{task}/data'
        extra=['--ro-bind',str(public.resolve()),'/work/data/datasets/'+registry['folder']]
        execution=run_process(base_command(work,data,extra)+[str(PYTHON),'grader.py'],out/'logs',180)
        verdict=None
        if execution['returncode']==0:
            try:
                v=ast.literal_eval(execution['stdout'].strip().splitlines()[-1])
                if isinstance(v,tuple) and len(v)==2 and type(v[0]) in (bool,int) and v[0] in (0,1):verdict=int(v[0])
            except (ValueError,SyntaxError,IndexError):pass
        result={'status':'graded' if verdict is not None else 'grader_error','official_success':verdict,'execution':execution}
    (out/'evaluation.json').write_text(json.dumps(result,indent=2));return result
