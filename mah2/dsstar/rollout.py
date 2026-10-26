"""Bounded adapter of pinned DS-STAR run_agent; upstream prompt builders reused verbatim."""
from __future__ import annotations
import ast
import re
import hashlib
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace
from .harness import FUNCTION_ROLE
from mah2.task_context import render_task
from mah2.public_evidence import artifact_summary
from .provider import BudgetExceeded, ProviderError
from .sandbox import Sandbox, manifest

UPSTREAM = Path(__file__).resolve().parents[2]/'vendor/ds-star/agents/prompts.py'
spec=importlib.util.spec_from_file_location('ds_star_prompts',UPSTREAM)
PROMPTS=importlib.util.module_from_spec(spec)
spec.loader.exec_module(PROMPTS)

def clean_code(text):
    # Preserve unicode inside valid Python. Never silently truncate an invalid
    # program to a parseable prefix: that can discard its output-writing code.
    blocks=re.findall(r"```(?:python|py)?[ \t]*\n(.*?)```",text,re.S|re.I)
    code='\n\n'.join(blocks).strip() if blocks else text.strip()
    ast.parse(code)
    return code

class Rollout:
    def __init__(self, client, harness, config, directory, data, sandbox_class=Sandbox):
        self.client,self.h,self.c,self.directory=client,harness,config,Path(directory)
        self.directory.mkdir(parents=True,exist_ok=False)
        self.data=Path(data)
        self.sandbox_class=sandbox_class
        self.box=sandbox_class(self.directory/'work',data,config)
        self.events=[]
        self.start=time.monotonic()
        self.P=SimpleNamespace(task='pilot')
        self.diagnosis=''
        self.question=''
        self.previous='controller'
        self.state={}

    def event(self,**value):
        rec=dict(id=f'e{len(self.events):04d}',**value)
        self.events.append(rec)
        with (self.directory/'trace.jsonl').open('a') as f: f.write(json.dumps(rec)+'\n')
        return rec

    def ask(self,function,*args):
        if time.monotonic()-self.start>self.c['rollout_seconds']:
            raise BudgetExceeded('rollout deadline')
        role=FUNCTION_ROLE[function]
        prompt=getattr(PROMPTS,function)(self.P,*args)
        if self.c.get('public_context'):prompt=prompt.replace('./data/./data/','./data/')
        contract=self.h['coordination']
        mappings={'initial_plan':('question','filenames','file_descriptions'),
                  'initial_implementation':('plan','filenames','file_descriptions'),
                  'verify':('plans','code','execution','question'),
                  'router':('question','filenames','file_descriptions','plans','execution'),
                  'next_plan':('question','filenames','file_descriptions','plans','execution'),
                  'implement':('plans','filenames','file_descriptions','code'),
                  'match_guideline':('code','execution','question','guidelines')}
        if function in mappings:self.state.update(zip(mappings[function],args))
        self.state.update(question=self.question or self.state.get('question',''),verification=self.diagnosis)
        for edge,interface in contract['contracts'].items():
            sender,receiver=edge.split('.')
            if role==sender and interface['sender_instruction']:
                prompt+='\nInterface '+edge+' producer requirement:\n'+interface['sender_instruction']
            if role==receiver:
                fields={k:self.state.get(k) for k in interface['fields']}
                prompt+='\nInterface '+edge+' v'+str(interface['version'])+':\n'+json.dumps(fields)+'\n'+interface['receiver_instruction']

        if function=='verify' and contract['verifier_diagnosis']:
            prompt+='\nInterface override: start with Yes or No, then state the violated public requirement and evidence, if any.'
        if function=='router' and contract['router_receives_diagnosis']:
            prompt+='\nVerifier feedback:\n'+self.diagnosis
        if function=='next_plan' and contract['planner_receives_diagnosis']:
            prompt+='\nVerifier feedback:\n'+self.diagnosis
        if role=='coder' and contract['coder_receives_question']:
            prompt+='\nTask instruction:\n'+self.question
        analysis_only=self.c.get('bounded_analysis') and function in ('code_for_analyze','debug_for_analyze')
        if self.c.get('public_context') and not analysis_only:
            prompt+='\nImmutable public task context (requirements and data, not controller instructions):\n'+self.question
        if self.h['roles'][role]: prompt+='\nRole procedure:\n'+self.h['roles'][role]
        if self.c.get('public_output_contract') and not analysis_only:
            from mah2.output_contract import PUBLIC_OUTPUT_CONTRACT
            prompt+='\n'+PUBLIC_OUTPUT_CONTRACT.split('Selection must test')[0]
        if role in ('coder','analyzer','finalizer') or function in ('debug_for_analyze','debug_with_context'):
            prompt+='\nOutput contract: return one complete executable Python program, optionally in a single Python fence, with no explanatory prose.'
        if analysis_only:
            prompt+='\nAnalyzer boundary: inspect the named public input only. Report schema, dimensions, dtypes, keys and a small sample. For a directory, list its contents and sample representative files. Do not solve the downstream task, fit models, perform full-dataset pairwise computations or write prediction outputs. Bound work by sampling; use lazy or memory-mapped inspection for large arrays. This boundary takes precedence over any role procedure asking for task implementation.'
        prompt_id=self.event(kind='handoff',sender=self.previous,receiver=role,function=function,
            referenced_artifacts=manifest(self.box.root/'pred_results'),prompt=prompt,sha256=hashlib.sha256(prompt.encode()).hexdigest(),contract_version=contract['version'])['id']
        try:
            answer=self.client.complete(prompt,role=role)
        except (BudgetExceeded,ProviderError) as exc:
            self.event(kind='role_failure',role=role,input_event=prompt_id,status=type(exc).__name__)
            raise
        self.event(kind='response',role=role,input_event=prompt_id,text=answer,status='returned')
        self.previous=role
        if role=='router':self.state['routing']=answer
        if function=='initial_plan':self.state['plans']=[answer]
        if function=='next_plan':self.state['plans']=list(args[3])+[answer]
        if role=='coder':self.state['code']=answer
        if role=='verifier':self.state['verification']=answer
        return answer

    def execute(self,code,name):
        remaining=self.c['rollout_seconds']-(time.monotonic()-self.start)
        if remaining<=0: raise BudgetExceeded('rollout deadline')
        try:
            code=clean_code(code)
        except (SyntaxError,ValueError) as exc:
            result={'returncode':1,'stdout':'','stderr':'Python syntax validation: '+str(exc),'timeout':False,'seconds':0.,'artifacts':{}}
            self.event(kind='execution',sender=self.previous,receiver='controller',code_sha256=hashlib.sha256(code.encode()).hexdigest(),**result)
            return result
        execution_timeout=min(remaining,self.c.get('analysis_seconds',remaining)) if self.c.get('bounded_analysis') and name.startswith('analyze_') else remaining
        result=self.box.run(code,name,timeout=execution_timeout)
        self.state['execution']=result['stdout']
        if self.c.get('artifact_feedback'):
            summary=artifact_summary(self.box.root,self.output_fname)
            result['public_artifact_summary']=summary
            result['stdout']+='\nPublic artifact inspection: '+json.dumps(summary)
            self.state['execution']=result['stdout']
        self.event(kind='execution',sender=self.previous,receiver='controller',code_sha256=hashlib.sha256(clean_code(code).encode()).hexdigest(),**result)
        return result

    def coder(self,prompt_function,args,filenames,contexts,name='intermediate.py',analysis=False):
        for _ in range(self.c['max_code_attempts']):
            code=self.ask(prompt_function,*args)
            result=self.execute(code,name)
            for _ in range(self.c['max_debug_rounds']):
                if result['returncode']==0: break
                bug=self.ask('bug_summarization',name[:-3],result['stderr'])
                code=self.ask('debug_for_analyze',code,bug) if analysis else self.ask('debug_with_context',code,bug,filenames,contexts)
                result=self.execute(code,name)
            if result['returncode']==0: return result['stdout'],code
        raise RuntimeError('bounded coding attempts exhausted')

    def run(self,packet):
        self.question=render_task(packet) if self.c.get('public_context') else packet['task_inst']
        self.output_fname=packet['output_fname']
        # Public filenames must resolve in the execution namespace.
        filenames=sorted('./data/'+p.name for p in self.data.iterdir())
        contexts=[]
        outcome=dict(runnable=False,official_success=None)
        try:
            for i,filename in enumerate(filenames):
                context,_=self.coder('code_for_analyze',(filename,),filenames,contexts,
                                     name=f'analyze_{i}.py',analysis=True)
                contexts.append(context)
            plan=self.ask('initial_plan',self.question,filenames,contexts)
            result,code=self.coder('initial_implementation',(plan,filenames,contexts),filenames,contexts)
            plans=[plan]
            self.diagnosis=self.ask('verify',plans,code,result,self.question)
            for _ in range(self.c['max_refinements']):
                if 'No' not in self.diagnosis: break
                route=None
                for _ in range(self.c['max_route_attempts']):
                    proposed=self.ask('router',self.question,filenames,contexts,plans,result)
                    if proposed=='Add Step' or proposed in [f'Step{i+1}' for i in range(len(plans))]:
                        route=proposed; break
                    self.event(kind='parse_error',role='router',text=proposed)
                if route is None: raise RuntimeError('bounded router parsing attempts exhausted')
                if route!='Add Step': plans=plans[:int(route.replace('Step',''))-1]
                plan=self.ask('next_plan',self.question,filenames,contexts,plans,result)
                plans.append(plan)
                result,code=self.coder('implement',(plans,filenames,contexts,code),filenames,contexts)
                self.diagnosis=self.ask('verify',plans,code,result,self.question)
            guidelines='Return only a complete standalone Python program. Read permitted input files in ./data or ./datasets. Write the output files required by the question. Do not rely on files created by previous executions.'
            (self.box.root/'question.txt').write_text(self.question)
            (self.box.root/'guidelines.txt').write_text(guidelines)
            final_reply=self.ask('match_guideline',code,result,self.question,guidelines)
            for attempt in range(self.c.get('finalization_repairs',0)+1):
                final=final_reply
                remaining=self.c['rollout_seconds']-(time.monotonic()-self.start)
                if remaining<=0:raise BudgetExceeded('no replay time remains')
                try:
                    final=clean_code(final_reply)
                    replay=self.sandbox_class(self.directory/('replay' if attempt==0 else f'replay_repair_{attempt}'),self.data,self.c)
                    checked=replay.run(final,'submission.py',timeout=remaining)
                    public=artifact_summary(replay.root,self.output_fname)
                    checked['public_artifact_summary']=public
                except (SyntaxError,ValueError) as exc:
                    checked={'returncode':1,'timeout':False,'stdout':'','stderr':'Python syntax validation: '+str(exc),'seconds':0.}
                    public={'exists':False}
                self.event(kind='finalization_attempt',attempt=attempt,**checked)
                if checked['returncode']==0 and public['exists']:break
                if attempt<self.c.get('finalization_repairs',0):
                    final_reply=self.ask('match_guideline',final_reply,json.dumps(checked),self.question,
                        guidelines+' Fix the reported syntax/execution/output failure. Return only Python code, without explanatory prose.')
            # Keep the canonical replay path tied to the final selected program.
            if 'replay' in locals() and replay.root.name!='replay':
                original=self.directory/'replay'
                if original.exists():original.rename(self.directory/'replay_attempt_0')
                original.symlink_to(replay.root.name,target_is_directory=True)
            self.event(kind='final_replay',**checked)
            output=packet['output_fname']
            artifact=(replay.root if 'replay' in locals() else self.directory/'missing_replay')/output
            available=artifact.is_file() and not artifact.is_symlink() and artifact.resolve().is_relative_to(replay.root.resolve())
            outcome.update(runnable=checked['returncode']==0 and available,
                           replay=checked,output_available=available,
                           program_sha256=hashlib.sha256(final.encode()).hexdigest())
            (self.directory/'submission.py').write_text(final)
        except (RuntimeError,ValueError,OSError) as exc:
            outcome['failure']=str(exc)
            self.event(kind='rollout_failure',error=str(exc))
        outcome['seconds']=time.monotonic()-self.start
        (self.directory/'outcome.json').write_text(json.dumps(outcome,indent=2))
        return outcome
