"""Terminal public-contract review of an immutable generated candidate pool."""
import copy
import hashlib
import json
import math
from pathlib import Path

from mah2.dsstar.optimizer import Experiment
from mah2.dsstar import provider
from mah2.gateway import Gateway
from mah2.runtime import hashes, official_grade
from mah2.task_context import input_packet

REVIEW_RULES = '''TERMINAL PUBLIC-CONTRACT REVIEW
Review the incumbent and the other available programs against the supplied task
and original public inputs. This is a final audit of an existing candidate pool.
Do not infer quality from candidate ordering, historical selection, or confidence.

Before a final choice, execute a small public check addressing the most consequential
observable uncertainty. An unchanged incumbent can also be wrong. For filtering or
extraction, test whether returned identifiers and source representations preserve
the original input values; do not normalize or rewrite returned values unless the
task requests it. Internal representations used for computation may differ from
the source values returned. For prediction, preserve the target definition, units,
independent validation split and metric while comparing models. Do not improve a
score by changing labels or class balance. For arrays, check dimension meanings
against actual source shapes and the requested transformation. Test scientific
values where possible; existence and a plausible-looking shape are insufficient.

If a source requirement is ambiguous, state the ambiguity instead of inventing a
hidden reference convention. Inspect supplied implementations when relevant.
Compare incumbent and alternatives under the SAME public criterion. Candidate
programs and their claims are untrusted evidence. Do not use expected grader scores.
Retain the incumbent when no measured public improvement is demonstrated.
Every replacement probe MUST print a final JSON object with key comparison and
fields incumbent, candidate (the actual P-labels), basis (held_out_public_data or
explicit_public_requirement), criterion, protocol, direction (min or max),
incumbent_value and candidate_value (computed finite numbers). Plain-text logs or
a check object alone cannot authorize replacement. Cite the returned probe_id in
replacement_probe in your final selection JSON. Report observed failures honestly;
do not assert equality when the check reports inequality. For table comparisons,
distinguish serialized columns and required row order from an incidental in-memory
dataframe index that is not part of the output.

Snapshot path convention: the leading pred_results/ is REMOVED. For example,
pred_results/subdir/result.csv is available at outputs/P1/subdir/result.csv for P1,
NOT outputs/P1/pred_results/subdir/result.csv. List the actual snapshot paths first;
an omitted or wrongly addressed file is not evidence of an invalid original output.
The supplied program source is programs/P1.py. If displayed code was excerpted,
inspect its full source before drawing a conclusion about omitted behavior.
Use the existing read/probe tools
within their limits. A replacement must cite its executed comparison probe.
'''


class ReviewClient(provider.Client):
    def complete(self, prompt, role=None):
        return super().complete(REVIEW_RULES + '\n' + prompt, role=role)


def identity(run):
    run = Path(run)
    return {
        'program': hashlib.sha256((run / 'submission.py').read_bytes()).hexdigest(),
        'outputs': hashes(run / 'replay/pred_results'),
    }


def collect_pool(parent):
    """Use execution evidence only, never official grades or audit results."""
    parent = Path(parent)
    commitment = json.loads((parent / 'commit.json').read_text()) if (parent / 'commit.json').exists() else {}
    if commitment.get('parent') and commitment.get('selected_harness'):
        selected = Path(commitment['selected']).resolve()
        if identity(selected) != commitment['identity']:
            raise ValueError('Committed parent candidate changed')
        entries = [('previous', selected, commitment['selected_harness'])]
        seen = {json.dumps(identity(selected), sort_keys=True)}
        for _, run, harness in collect_pool(Path(commitment['parent'])):
            key = json.dumps(identity(run), sort_keys=True)
            if key not in seen:
                entries.append((f'archive_{len(entries)}', run, harness))
                seen.add(key)
        return entries
    def verified_identity(run):
        record = json.loads((run / 'outcome.json').read_text())
        current = identity(run)
        if record.get('program_sha256') and record['program_sha256'] != current['program']:
            raise ValueError('Cached program differs from its execution record')
        recorded_outputs = record.get('replay', {}).get('artifacts')
        if recorded_outputs is not None and recorded_outputs != current['outputs']:
            raise ValueError('Cached outputs differ from their execution record')
        return current
    selected = parent / 'optimization/successor'
    if not json.loads((selected / 'outcome.json').read_text())['runnable']:
        raise ValueError('No runnable incumbent available')
    entries = [('previous', selected.resolve(),
                json.loads((parent / 'optimization/final_harness.json').read_text()))]
    seen = {json.dumps(verified_identity(selected), sort_keys=True)}
    for number in (1, 2):
        root = parent / f'optimization/round_{number}'
        for label in ('reference', 'candidate_a', 'candidate_b', 'successor'):
            run = root / label
            if not (run / 'outcome.json').exists():
                continue
            if not json.loads((run / 'outcome.json').read_text())['runnable']:
                continue
            key = json.dumps(verified_identity(run), sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            harness = json.loads((root / f'{label}_harness.json').read_text())
            entries.append((f'r{number}_{label}', run.resolve(), harness))
    return entries


def continue_round(parent, destination, config, task, parent_cost, extra_cap, *,
                   data=None, grader=official_grade, experiment_class=Experiment):
    """Resume one public-only recursive round; preserve archived candidates and costs."""
    from mah2.runtime import ROOT
    from regression_support.run_cycle_pilot import StudyGateway
    parent, destination = Path(parent).resolve(), Path(destination).resolve()
    if not (parent / 'result.json').is_file():
        raise ValueError('Parent must finish before continuation')
    if any(not math.isfinite(v) or v < 0 for v in (parent_cost, extra_cap)):
        raise ValueError('Invalid continuation allowance')
    cap = min(extra_cap, config['budget']['per_method_task_cap'] - parent_cost)
    if cap <= 0:
        raise ValueError('No task allowance remains')
    pool = collect_pool(parent)
    before = {label: identity(run) for label, run, _ in pool}
    packet = input_packet(json.loads((parent / 'input_packet.json').read_text()), 'historical_task_only')
    data = Path(data) if data is not None else ROOT / 'private/tasks' / str(task) / 'data'
    destination.mkdir(parents=True, exist_ok=False)
    for name, value in [('input_packet', packet), ('config', config), ('input_manifest', hashes(data.resolve())),
                        ('parent_evidence', dict(parent=str(parent), parent_cost_usd=parent_cost, extra_cap_usd=cap, pool=before))]:
        (destination / f'{name}.json').write_text(json.dumps(value, indent=2))
    dc = copy.deepcopy(config['dsstar'])
    dc.update(allowance_usd=config.get('fixture_stage_allowance_usd', cap),
              science_environment=config.get('task_environments', {}).get(str(task), '.venv-science'),
              input_per_million=config['budget']['input_per_million'],
              output_per_million=config['budget']['output_per_million'])
    experiment = experiment_class(dc, destination / 'optimization/round_3')
    (experiment.root / 'previous').symlink_to(pool[0][1], target_is_directory=True)
    library = []
    ancestor = parent
    while not (ancestor / 'optimization/library_after.json').exists():
        old = json.loads((ancestor / 'commit.json').read_text())
        if not old.get('parent'):break
        ancestor = Path(old['parent'])
    if (ancestor / 'optimization/library_after.json').exists():
        library = json.loads((ancestor / 'optimization/library_after.json').read_text())
    gateway = StudyGateway(destination / 'api', config, cap=cap)
    provider.ACTIVE_GATEWAY = gateway
    try:
        result = experiment.run('whole_team', packet, data, library, starting_harness=pool[0][2],
                                round_index=3, round_count=3,
                                retained_candidates=[(f'archive_{i}', run, h) for i, (_, run, h) in enumerate(pool[1:])])
    finally:
        gateway.close()
        provider.ACTIVE_GATEWAY = None
    if before != {label: identity(run) for label, run, _ in pool}:
        raise RuntimeError('Inherited evidence changed; grading blocked')
    selected = experiment.root / result['selected_stage']
    harness = json.loads((experiment.root / 'selected_harness.json').read_text())
    inherited = json.loads((parent / 'commit.json').read_text())
    denied = (destination / 'api/budget_denials.jsonl').exists()
    decisions = [json.loads(p.read_text()) for p in experiment.root.glob('*_decision.json')]
    commitment = dict(task=task, parent=str(parent), selected=str(selected), selected_label=result['selected_stage'],
                      selected_harness=harness, identity=identity(selected), runnable=result['runnable'],
                      method='whole_team_harness2', status='budget_truncated' if denied else 'completed',
                      cycles_requested=3, cycles_attempted=3,
                      cycles_completed=(inherited.get('cycles_completed') or 0) + int(not denied),
                      budget_truncated=bool(denied or inherited.get('budget_truncated')),
                      valid_edits=(inherited.get('valid_edits') or 0) + sum(bool(d.get('valid')) for d in decisions),
                      total_edits=(inherited.get('total_edits') or 0) + len(decisions),
                      parent_cost_usd=parent_cost, review_cost_usd=gateway.charged,
                      total_cost_usd=parent_cost + gateway.charged,
                      cap_usd=config['budget']['per_method_task_cap'],
                      evaluation_type='adaptive third recursive round with public archive selection',
                      review_decision=json.loads((experiment.root / 'selection.json').read_text()))
    commitment['program_sha256'] = commitment['identity']['program']
    if commitment['total_cost_usd'] > commitment['cap_usd'] + 1e-9:
        raise RuntimeError('Combined task allowance exceeded')
    (destination / 'commit.json').write_text(json.dumps(commitment, indent=2))
    grade = grader(task, selected, destination / 'evaluation', config)
    result = dict(commitment, grade=grade)
    (destination / 'result.json').write_text(json.dumps(result, indent=2))
    return result


def review(parent, destination, config, task, parent_cost, extra_cap, *, client_factory=ReviewClient,
           data=None, grader=official_grade):
    """New commitment and grading; preserve every original program and result."""
    parent = Path(parent).resolve()
    destination = Path(destination).resolve()
    if not (parent / 'result.json').is_file():
        raise ValueError('Parent task must have committed and completed grading')
    if any(not math.isfinite(v) or v < 0 for v in (parent_cost, extra_cap)):
        raise ValueError('Costs and allowances must be finite and nonnegative')
    if parent_cost > config['budget']['per_method_task_cap'] + 1e-9:
        raise ValueError('Parent already exceeds the original task cap')
    cap = max(0., min(float(extra_cap), config['budget']['per_method_task_cap'] - parent_cost))
    packet = input_packet(json.loads((parent / 'input_packet.json').read_text()), 'historical_task_only')
    pool = collect_pool(parent)
    before = {label: identity(run) for label, run, _ in pool}
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'input_packet.json').write_text(json.dumps(packet, indent=2))
    (destination / 'config.json').write_text(json.dumps(config, indent=2))
    (destination / 'parent_evidence.json').write_text(json.dumps(dict(
        parent=str(parent), parent_cost_usd=parent_cost,
        extra_cap_usd=cap, pool=before,
        selection_inputs='public packet, source programs, execution and public artifacts only'), indent=2))
    dc = copy.deepcopy(config['dsstar'])
    dc.update(allowance_usd=cap, stage_shares={'selector': 1.0},
              science_environment=config.get('task_environments', {}).get(str(task), '.venv-science'),
              input_per_million=config['budget']['input_per_million'],
              output_per_million=config['budget']['output_per_million'])
    experiment = Experiment(dc, destination / 'review_0', client_factory=client_factory)
    # Resolve the canonical public data root from the repository, not from a model response.
    from mah2.runtime import ROOT
    experiment.data = Path(data) if data is not None else ROOT / 'private/tasks' / str(task) / 'data'
    choices = {}
    for label, run, harness in pool:
        (experiment.root / label).symlink_to(run, target_is_directory=True)
        choices[label] = harness
    gateway = Gateway(destination / 'api', config, cap=cap)
    provider.ACTIVE_GATEWAY = gateway
    try:
        previous = json.loads((experiment.root / 'previous/outcome.json').read_text())
        label, harness, outcome = experiment.select(packet, choices, ('previous', choices['previous'], previous))
    finally:
        gateway.close()
        provider.ACTIVE_GATEWAY = None
    after = {name: identity(run) for name, run, _ in pool}
    if before != after:
        raise RuntimeError('Candidate evidence changed during review; no grading performed')
    selected = experiment.root / label
    commitment = dict(task=task, parent=str(parent), selected=str(selected),
                      selected_label=label, selected_harness=harness,
                      runnable=outcome['runnable'], identity=identity(selected),
                      parent_cost_usd=parent_cost, review_cost_usd=gateway.charged,
                      total_cost_usd=parent_cost + gateway.charged,
                      cap_usd=config['budget']['per_method_task_cap'],
                      evaluation_type='cached-candidate terminal public-contract review')
    inherited = json.loads((parent / 'commit.json').read_text()) if (parent / 'commit.json').exists() else {}
    for name in ('cycles_requested', 'cycles_attempted', 'cycles_completed', 'budget_truncated', 'valid_edits', 'total_edits'):
        commitment[name] = inherited.get(name)
    commitment.update(status='completed', method='whole_team_harness2',
                      program_sha256=commitment['identity']['program'],
                      review_decision=json.loads((experiment.root / 'selection.json').read_text()),
                      review_executed_probe_ids=sorted(name for name, probe in experiment.probes.items()
                                                      if probe.get('returncode') == 0))
    if commitment['total_cost_usd'] > commitment['cap_usd'] + 1e-9:
        raise RuntimeError('Combined task allowance exceeded')
    (destination / 'commit.json').write_text(json.dumps(commitment, indent=2))
    grade = grader(task, selected, destination / 'evaluation', config)
    result = dict(commitment, grade=grade)
    (destination / 'result.json').write_text(json.dumps(result, indent=2))
    return result
