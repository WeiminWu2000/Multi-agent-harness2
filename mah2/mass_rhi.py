"""Released MASS search driver, with benchmark paths and budgeted transport adapters."""
import contextlib,json,sys
from pathlib import Path
from types import SimpleNamespace
from .runtime import ROOT,episode,render_workflow
from .task_context import render_task
sys.path.insert(0,str(ROOT/'vendor/mass'))
from mass import pipeline
from harness_improvement import iterate_multi_agent_prompt as rhi
from harness_improvement.llm_backend import _extract_json_object

FOOTER='''Use uv for all Python workflows only if needed; the supplied Python environment already contains dependencies. Network and package installation are unavailable. Read public inputs in ./data or ./datasets. Produce standalone submission.py that regenerates the required outputs in pred_results from those inputs in a fresh workspace. Execute the proposed team using real agent tool calls. Keep logs.txt documenting actual delegation, checks and unresolved issues. Do not access private graders or hidden targets. Finalize within the supplied execution and API budget.\n'''
BARE_FOOTER=FOOTER.replace('Execute the proposed team using real agent tool calls.','Solve this task without creating a multi-agent team.')

def run(gateway,config,packet,data,root,task,cap):
    if config.get('public_context'):
        packet={**packet,'task_inst':render_task(packet)}
    task=1000+task # Avoid MASS's synthetic-domain persona bands for benchmark IDs.
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    task_root=root/'task_inputs'
    for name in ('bare','initial'):(task_root/'tasks'/name).mkdir(parents=True)
    (task_root/f'tasks/bare/query{task}.txt').write_text(packet['task_inst']+'\n\n'+BARE_FOOTER)
    design=render_workflow(json.loads((ROOT/'config/workflow.json').read_text()))
    (task_root/f'tasks/initial/query{task}_ourTeam.txt').write_text(packet['task_inst']+'\n\n'+design+'\n\n'+FOOTER)
    # Only search is called. No collection, ranking, training or export stage.
    cfg={'run_dir':str(root),'model_id':config['model'],'endpoint':'http://127.0.0.1:8001/v1','proxy_port':9001,'search':{'iterations':config['mass_rhi']['iterations'],'seed_base':20261023}}
    episodes={}
    released_share=0.
    start_charge=gateway.charged
    def set_stage(name,share):
        nonlocal released_share
        released_share+=share
        allowance=cap*share
        if config['mass_rhi'].get('budget_policy')=='carry_forward':
            allowance=max(0.,cap*released_share-(gateway.charged-start_charge))
        gateway.set_stage(name,allowance)
    class Backend:
        def __init__(self,**kwargs):pass
        def verify_model(self):pass # Gateway pins the authenticated provider and model.
        def invoke(self,system_prompt,user_prompt,structured):
            before=gateway.charged
            payload={'messages':[{'role':'system','content':system_prompt},{'role':'user','content':user_prompt}],'max_tokens':8192}
            if structured:payload['response_format']={'type':'json_object'}
            result=gateway.request(payload);raw=result['choices'][0]['message'].get('content') or ''
            return SimpleNamespace(payload=_extract_json_object(raw) if structured else {},raw_text=raw,metrics={'estimated_cost_usd':gateway.charged-before,'usage':result.get('usage',{})})
        def call_json(self,*,system_prompt,user_prompt):return self.invoke(system_prompt,user_prompt,True)
        def call_text(self,*,system_prompt,user_prompt):return self.invoke(system_prompt,user_prompt,False)
    def execute(c,prompt,workspace,logs,seed,condition):
        set_stage(condition,config['mass_rhi']['episode_share'])
        stage=root/'episodes'/condition
        result=episode(gateway,{},packet,data,stage,config,prompt_override=Path(prompt).read_text())
        workspace=Path(workspace);workspace.parent.mkdir(parents=True,exist_ok=True)
        workspace.symlink_to(stage/'work',target_is_directory=True)
        logs=Path(logs);logs.mkdir(parents=True,exist_ok=False)
        (logs/'prompt.txt').write_text(Path(prompt).read_text())
        status={'exit_code':result['agent']['returncode'],'trace_has_success_result':result['runnable'],'public_replay_runnable':result['runnable']}
        (logs/'run_status.json').write_text(json.dumps(status))
        episodes[condition]={'directory':str(stage),'outcome':result}
        (root/'episodes.json').write_text(json.dumps(episodes,indent=2))
    def invoke(command,env=None):
        args=[str(x) for x in command[3:]]
        k=int(args[args.index('--current-version')+1])
        # Preserve iteration logic and prompts; bound context/output for this pilot.
        args.remove('--require-local-vllm') # Transport is explicitly OpenRouter, not a local inference server.
        args[args.index('--max-output-tokens')+1]=str(config['execution']['max_output_tokens'])
        set_stage(f'rhi_v{k}',config['mass_rhi']['rhi_stage_shares'][k])
        saved=sys.argv;sys.argv=['mass-rhi',*args]
        try:
            with (root/f'rhi_v{k}.log').open('w') as log,contextlib.redirect_stdout(log):
                code=rhi.main()
            if code:raise RuntimeError(f'Released RHI exited {code}')
        finally:sys.argv=saved
    original=(pipeline.ROOT,pipeline.episode,pipeline.run,rhi.JsonLLMBackend)
    pipeline.ROOT,pipeline.episode,pipeline.run,rhi.JsonLLMBackend=task_root,execute,invoke,Backend
    try:pipeline.search(cfg,[task])
    finally:pipeline.ROOT,pipeline.episode,pipeline.run,rhi.JsonLLMBackend=original
    retained=json.loads((root/f'search/query{task}_ourTeam/retained_workflow.json').read_text())
    version=retained['version']
    key=f't{task}_bare' if version is None else f't{task}_v{version}'
    return {'selected':episodes[key]['directory'],'cycles_attempted':2,'cycles_completed':2,'retained':retained,'team_executions':len(episodes)}
