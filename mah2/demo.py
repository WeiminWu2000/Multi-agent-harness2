"""A deterministic teaching demo using real programs and the shared recursive controller."""
import argparse,copy,csv,hashlib,json,sys,venv
from pathlib import Path
from .dsstar.harness import initial,validate
from .dsstar.recursion import run_recursive
from .runtime import base_command,run_process,hashes

ROLE_RULE='Sort output rows by numeric id before writing.'
CONTRACT='Pass the join key id explicitly; match labels by id rather than row position.'

class DemoExperiment:
    def __init__(self,config,path):
        self.c=config;self.path=Path(path);self.path.mkdir()

    def execute(self,harness,label,data):
        stage=self.path/label;stage.mkdir();work=stage/'replay';work.mkdir()
        join_by_id='planner.coder' in harness['coordination']['contracts']
        sort_rows=harness['roles']['coder']==ROLE_RULE
        code=f'''import csv
from pathlib import Path
with open('data/values.csv') as f: values=list(csv.DictReader(f))
with open('data/labels.csv') as f: labels=list(csv.DictReader(f))
if {join_by_id!r}:
    lookup={{r['id']:r['label'] for r in labels}}
    rows=[[r['id'],r['value'],lookup[r['id']]] for r in values]
else:
    rows=[[v['id'],v['value'],l['label']] for v,l in zip(values,labels)]
if {sort_rows!r}: rows.sort(key=lambda row:int(row[0]))
Path('pred_results').mkdir(exist_ok=True)
with open('pred_results/join.csv','w',newline='') as f:
    w=csv.writer(f);w.writerow(['id','value','label']);w.writerows(rows)
'''
        (stage/'submission.py').write_text(code);(work/'submission.py').write_text(code)
        science=Path(self.c['science_environment'])
        execution=run_process(base_command(work,data,science=science)+[str(science/'bin/python'),'submission.py'],stage/'logs',30)
        if execution['returncode']!=0:raise RuntimeError('Demo sandbox failed: '+execution['stderr'])
        with (work/'pred_results/join.csv').open() as f:rows=list(csv.DictReader(f))
        with (data/'labels.csv').open() as f:labels={r['id']:r['label'] for r in csv.DictReader(f)}
        with (data/'values.csv').open() as f:values={r['id']:r['value'] for r in csv.DictReader(f)}
        checks={'join_values_match_public_inputs':len(rows)==len(values) and all(r['id'] in values and r['value']==values[r['id']] and r['label']==labels[r['id']] for r in rows),
                'rows_sorted_by_id':[int(r['id']) for r in rows]==sorted(int(r['id']) for r in rows)}
        outcome={'runnable':True,'program_sha256':hashlib.sha256(code.encode()).hexdigest(),'artifacts':hashes(work/'pred_results')}
        (stage/'outcome.json').write_text(json.dumps(outcome,indent=2));(stage/'public_checks.json').write_text(json.dumps(checks,indent=2))
        return sum(checks.values()),outcome

    def run(self,method,packet,data,library,starting_harness,round_index,round_count,retained_candidates=()):
        base=copy.deepcopy(starting_harness);local=copy.deepcopy(base);coord=copy.deepcopy(base)
        local['roles']['coder']=ROLE_RULE;validate(local,base,'local')
        if 'planner.coder' not in coord['coordination']['contracts']:
            coord['coordination']['version']+=1
            coord['coordination']['contracts']['planner.coder']={'version':coord['coordination']['version'],'fields':['question','plans'],'sender_instruction':CONTRACT,'receiver_instruction':CONTRACT}
        validate(coord,base,'coordination');assert coord['roles']==base['roles']
        (self.path/'reference_harness.json').write_text(json.dumps(base,indent=2))
        for label,h in [('proposal_a',local),('proposal_b',coord)]:
            (self.path/(label+'_decision.json')).write_text(json.dumps({'valid':True,'harness':h,'editor':'scripted_demo'},indent=2))
        harnesses={'reference':base,'candidate_a':local,'candidate_b':coord};scores={};outcomes={}
        for label,h in harnesses.items():scores[label],outcomes[label]=self.execute(h,label,data)
        composed=copy.deepcopy(base)
        if scores['candidate_a']>scores['reference']:composed['roles']=local['roles']
        if scores['candidate_b']>scores['reference']:composed['coordination']=coord['coordination']
        harnesses['successor']=composed
        (self.path/'composer_decision.json').write_text(json.dumps({'valid':True,'harness':composed,'editor':'scripted_demo'},indent=2))
        scores['successor'],outcomes['successor']=self.execute(composed,'successor',data)
        selected=max(scores,key=scores.get) # Ordered candidates retain the reference on ties.
        commit={'method':'deterministic_demo','runnable':True,'selected_stage':selected,
                'program_sha256':outcomes[selected]['program_sha256'],'official_success':None}
        (self.path/'selected_harness.json').write_text(json.dumps(harnesses[selected],indent=2))
        (self.path/'commit.json').write_text(json.dumps(commit,indent=2))
        (self.path/'selection.json').write_text(json.dumps({'valid':True,'selected_stage':selected,'public_check_counts':scores,'checks_total':2},indent=2))
        library.append({'round':round_index,'lesson':'Match identifiers explicitly and preserve requested output ordering.'})
        print(f'Round {round_index}: reference {scores["reference"]}/2 | role {scores["candidate_a"]}/2 | coordination {scores["candidate_b"]}/2 | composed {scores["successor"]}/2 -> {selected}')
        return commit


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=Path('runs/demo'));p.add_argument('--rounds',type=int,default=2);p.add_argument('--science-env',type=Path);a=p.parse_args(argv)
    if not 1<=a.rounds<=10:p.error('--rounds must be between 1 and 10')
    root=a.output.resolve()
    if root.exists():p.error('Output exists; choose a new --output directory')
    root.mkdir(parents=True)
    science=a.science_env.resolve() if a.science_env else root/'.science-env'
    if a.science_env is None:venv.EnvBuilder(with_pip=False).create(science)
    data=root/'data';data.mkdir();(data/'values.csv').write_text('id,value\n2,20\n1,10\n');(data/'labels.csv').write_text('id,label\n1,A\n2,B\n')
    config={'allowance_usd':0.,'science_environment':str(science),'runnable_fallback':True,'public_selection':True,'retain_candidate_archive':True}
    print('Scripted editors + real sandboxed Python executions. No model calls. Demo checks are public toy requirements, not benchmark scores.')
    final=run_recursive(config,root/'optimization','whole_team',{},data,[],a.rounds,DemoExperiment)
    record={'method':'deterministic_demo','status':'completed','official_success':None,'evaluation':'public_toy_checks_only','paid_calls':False,'provider_reported_usd':0.,'selected':'optimization/successor','rounds':a.rounds,'program_sha256':final['program_sha256']}
    (root/'result.json').write_text(json.dumps(record,indent=2));(root/'commit.json').write_text(json.dumps(record,indent=2))
    print('Inspect:',root/'optimization/successor/replay/pred_results/join.csv')
    return 0
if __name__=='__main__':raise SystemExit(main())
