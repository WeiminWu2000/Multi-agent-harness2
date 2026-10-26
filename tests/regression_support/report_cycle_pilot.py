"""Every preselected task/method, cycles, strict outcome and actual USD accounting."""
import argparse,csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))

def read(path,default=None):return json.loads(path.read_text()) if path.exists() else default

def cost(root):
    entries=[];pending=0.
    for p in root.glob('api/ledger.jsonl'):
        entries += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    for p in root.glob('api/*pending*.json'):
        r=read(p,{})
        pending+=r.get('reserved_usd',r.get('reserved',0))
    provider=sum(float(r.get('usage',{}).get('cost') or 0) for r in entries)
    charged=sum(r['charged_usd'] for r in entries)
    missing=sum(r.get('usage',{}).get('cost') is None for r in entries)
    return {'provider_reported_usd':provider,'provider_cost_missing_calls':missing,'charged_or_reserved_usd':charged,'inflight_upper_usd':pending,'total_upper_usd':charged+pending,'api_calls':len(entries),'api_errors':sum(r.get('status')=='failed' for r in entries)}

def lineage(root):
    """Each physical parent ledger exactly once, including cached review parents."""
    root=Path(root).resolve();seen=set()
    while True:
        if root in seen:raise ValueError('Cyclic experiment ancestry')
        seen.add(root);yield root
        config=read(root/'config.json',{})
        group=config.get('candidate_parent_group')
        if not group:break
        root=ROOT/'runs'/group/root.parent.name/root.name
        root=root.resolve()

def lineage_cost(root):
    result=cost(root)
    for parent in list(lineage(root))[1:]:
        inherited=cost(parent)
        result={k:v+inherited[k] for k,v in result.items()}
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='config/cycles10.json');a=p.parse_args()
    c=read(ROOT/a.config);rows=[]
    retained=c.get('retained_methods',{})
    methods=list(retained)+c['methods']
    for task in c['tasks']:
        for method in methods:
            group=retained.get(method,c['run_group'])
            root=ROOT/'runs'/group/method/str(task);r=read(root/'result.json',{})
            worker=read(root/'worker_exit.json',{})
            if not r and worker.get('returncode',0)!=0:
                r={'status':'worker_error','grade':{'status':'worker_error','official_success':0}}
            grade=r.get('grade',{})
            accounting=cost(root);review_cost=0.;inherited_cost=0.
            if c.get('candidate_parent_group') and group==c['run_group']:
                parent=ROOT/'runs'/c['candidate_parent_group']/method/str(task)
                inherited=lineage_cost(parent);review_cost=accounting['total_upper_usd'];inherited_cost=inherited['total_upper_usd']
                accounting={k:v+inherited[k] for k,v in accounting.items()}
            rows.append({'task':task,'method':method,'source_run_group':group,'status':r.get('status','started_unfinished' if root.exists() else 'not_started'),'cycles_requested':r.get('cycles_requested',0 if method=='plain_ds_star' else (c.get('outer_cycles',2) if group==c['run_group'] else 2)),'cycles_attempted':r.get('cycles_attempted'),'cycles_completed':r.get('cycles_completed'),'strict_success':int(grade.get('official_success')==1) if r else None,'grading_status':grade.get('status'),'runnable':r.get('runnable'),'budget_truncated':r.get('budget_truncated'),'valid_edits':r.get('valid_edits'),'total_edits':r.get('total_edits'),**accounting})
            if c.get('candidate_parent_group'):
                rows[-1].update(inherited_generation_upper_usd=inherited_cost,new_review_upper_usd=review_cost)
    totals={}
    for method in methods:
        subset=[r for r in rows if r['method']==method]
        totals[method]={'completed_runs':sum(r['strict_success'] is not None for r in subset),'successes':sum(r['strict_success']==1 for r in subset),'planned_tasks':len(c['tasks']),**{k:sum(r[k] for r in subset) for k in ('provider_reported_usd','charged_or_reserved_usd','inflight_upper_usd','total_upper_usd','api_calls','api_errors')}}
    calibration={str(p.relative_to(ROOT/'runs'/c['calibration_group'])):cost(p) for p in (ROOT/'runs'/c['calibration_group']).glob('*/*') if p.is_dir()}
    total=sum(r['total_upper_usd'] for r in rows)+sum(r['total_upper_usd'] for r in calibration.values())
    result={'complete':all(r['strict_success'] is not None for r in rows),'interpretation':c['comparison'],'rows':rows,'totals':totals,'calibration':calibration,'study_including_calibration_upper_usd':total,'authorized_cap_usd':c.get('budget',{}).get('total_cap',31),'previous_stopped_study_upper_usd':read(ROOT/'results/pilot10.json',{}).get('combined_upper_usd'),'cost_note':'Provider cost is reported only where supplied. Charged totals retain conservative reservations for unknown usage; inflight amounts are upper bounds, not confirmed bills.'}
    if c.get('candidate_parent_group'):
        result['cost_note']+=' Whole-Team totals include the full cached generation cost plus new review calls; cumulative study spending counts each physical API ledger once.'
    if c.get('shared_run_groups'):
        groups=c['shared_run_groups']+c.get('shared_calibration_groups',[])
        result['cumulative_study_upper_usd']=sum(cost(p)['total_upper_usd'] for group in groups for p in (ROOT/'runs'/group).glob('*/*') if p.is_dir())
        result['preserved_baseline_totals']=read(ROOT/'results/cycles10.json',{}).get('totals')
    (ROOT/f"results/{c['run_group']}.json").write_text(json.dumps(result,indent=2)+'\n')
    with (ROOT/f"results/{c['run_group']}.csv").open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    if c.get('combined_cohorts'):
        combined=[]
        for cohort in c['combined_cohorts']:
            old=read(ROOT/cohort['report'])
            if not old or not old['complete']:raise RuntimeError('Historical cohort must be complete')
            combined.extend(dict(r,cohort=cohort['label']) for r in old['rows'])
        combined.extend(dict(r,cohort='new') for r in rows)
        pairs={}
        for row in combined:
            key=(row['task'],row['method'])
            if key in pairs:raise RuntimeError('Duplicate task/method in pooled comparison')
            pairs[key]=row
        def summary(subset):
            totals={m:dict(successes=sum(r['strict_success']==1 for r in subset if r['method']==m),completed=sum(r['strict_success'] is not None for r in subset if r['method']==m),planned=sum(r['method']==m for r in subset),cost_upper_usd=sum(r['total_upper_usd'] for r in subset if r['method']==m)) for m in methods}
            counts={'both_pass':0,'harness_only':0,'mass_only':0,'both_fail':0,'pending':0}
            for task in sorted({r['task'] for r in subset}):
                pair={r['method']:r['strict_success'] for r in subset if r['task']==task}
                h=pair.get('whole_team_harness2');m=pair.get('mass_rhi')
                label='pending' if h is None or m is None else ('both_pass' if h and m else 'harness_only' if h else 'mass_only' if m else 'both_fail')
                counts[label]+=1
            return dict(totals=totals,paired=counts)
        pooled=dict(complete=all(r['strict_success'] is not None for r in combined),interpretation='Primary comparison is the frozen new ten. Pooled twenty mix adaptively developed old tasks and frozen new tasks; they are not twenty unseen evaluations. Old Harness2 had an adaptive review/third-round schedule; new Harness2 starts with current repairs and three rounds.',cohorts={label:summary([r for r in combined if r['cohort']==label]) for label in sorted({r['cohort'] for r in combined})},pooled=summary(combined),rows=combined)
        (ROOT/'results/combined20.json').write_text(json.dumps(pooled,indent=2)+'\n')
        with (ROOT/'results/combined20.csv').open('w') as f:
            fields=list(dict.fromkeys(k for r in combined for k in r))
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(combined)
    if c.get('reference_reports'):
        from mah2.dsstar.codex_editor import usage
        combined=[]
        for name in c['reference_reports']:
            reference=read(Path(name))
            if reference:combined.extend(reference['rows'])
        for row in rows:
            row=dict(row)
            runroot=ROOT/'runs'/row['source_run_group']/row['method']/str(row['task'])
            row['codex_usage']=usage(runroot)
            audit=[]
            for rd in sorted((runroot/'optimization').glob('round_*')):
                base=read(rd/'reference_harness.json',{})
                proposed=read(rd/'proposal_b_decision.json',{})
                selected=read(rd/'selected_harness.json',{})
                changed=bool(proposed.get('valid') and proposed.get('harness',{}).get('coordination')!=base.get('coordination'))
                audit.append(dict(round=rd.name,proposal_valid=proposed.get('valid'),proposal_changed_coordination=changed,selected_changed_coordination=bool(selected and selected.get('coordination')!=base.get('coordination')),selected_matches_current_codex_proposal=bool(changed and selected.get('coordination')==proposed['harness']['coordination']),proposal_error=proposed.get('error')))
            row['coordination_audit']=audit
            row['total_model_cost_usd']=None
            combined.append(row)
        keys=[(r['task'],r['method']) for r in combined]
        if len(keys)!=len(set(keys)):raise RuntimeError('Duplicate method/task in three-condition report')
        condition_totals={}
        for method in sorted({r['method'] for r in combined}):
            subset=[r for r in combined if r['method']==method]
            condition_totals[method]=dict(successes=sum(r['strict_success']==1 for r in subset),completed=sum(r['strict_success'] is not None for r in subset),planned=len(subset),glm_upper_usd=sum(r['total_upper_usd'] for r in subset),codex_calls=sum(r.get('codex_usage',{}).get('calls',0) for r in subset))
        merged=dict(complete=len(combined)==3*len({r['task'] for r in combined}) and all(r['strict_success'] is not None for r in combined),interpretation=c['comparison'],cost_note='Hybrid totals show GLM API dollars only; Codex ChatGPT usage is separate and its dollar cost is unknown. This is not an equal-total-dollar ablation. Hybrid also separates role and coordination edit scopes.',totals=condition_totals,rows=combined)
        (ROOT/'results'/c['comparison_report']).write_text(json.dumps(merged,indent=2)+'\n')
    print(json.dumps({'complete':result['complete'],'total_upper_usd':total,'totals':totals},indent=2))
if __name__=='__main__':main()
