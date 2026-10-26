"""Repeated team self-improvement with a fixed total method-task allowance."""
from __future__ import annotations
import copy,json
from pathlib import Path
from .harness import initial


def run_recursive(config,root,method,packet,data,library,depth,experiment_class=None):
    if experiment_class is None:
        from .optimizer import Experiment
        experiment_class = Experiment
    if type(depth) is not int or depth<1:raise ValueError('depth must be a positive integer')
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    c=copy.deepcopy(config);c['allowance_usd']=config['allowance_usd']/depth
    c['recursion_depth']=depth
    current=initial();rounds=[];retained=None;archive=[]
    for t in range(1,depth+1):
        directory=root/f'round_{t}'
        experiment=experiment_class(c,directory)
        if c.get('public_selection') and retained:
            prior_round,prior_stage,_=retained
            (directory/'previous').symlink_to(f'../round_{prior_round}/{prior_stage}',target_is_directory=True)
        extra={'retained_candidates':archive} if c.get('retain_candidate_archive') else {}
        committed=experiment.run(method,packet,data,library,starting_harness=current,
                                 round_index=t,round_count=depth,**extra)
        if c.get('retain_candidate_archive'):
            for label,harness_file in [('reference','reference_harness.json'),('candidate_a','proposal_a_decision.json'),('candidate_b','proposal_b_decision.json'),('successor','composer_decision.json')]:
                path=directory/label
                outcome=json.loads((path/'outcome.json').read_text())
                if outcome['runnable']:
                    h=json.loads((directory/harness_file).read_text())
                    archive.append((f'archive_{len(archive)}',path,h if label=='reference' else h['harness']))
        # Carry executable role/contract state, not a candidate's answer or workspace.
        chosen=directory/'selected_harness.json'
        proposed=json.loads(chosen.read_text()) if chosen.exists() else json.loads((directory/'composer_decision.json').read_text())['harness']
        if c.get('runnable_fallback'):
            if committed['runnable']:
                current=proposed;retained=(t,committed['selected_stage'],committed)
            # If every execution failed, keep the last runnable harness/program.
        else:current=proposed
        rounds.append(dict(round=t,commit=committed))
    selected_round,selected_stage,selected_commit=retained if retained else (depth,'successor',rounds[-1]['commit'])
    final=copy.deepcopy(selected_commit)
    final.update(recursion_depth=depth,selected_round=selected_round,total_allowance_usd=config['allowance_usd'])
    (root/'successor').symlink_to(f'round_{selected_round}/{selected_stage}',target_is_directory=True)
    (root/'commit.json').write_text(json.dumps(final,indent=2))
    (root/'rounds.json').write_text(json.dumps(rounds,indent=2))
    (root/'library_after.json').write_text(json.dumps(library,indent=2))
    (root/'final_harness.json').write_text(json.dumps(current,indent=2))
    return final
