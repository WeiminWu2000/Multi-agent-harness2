"""Validate and run the cached-candidate terminal-review extension."""
import argparse
import ast
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests/regression_support'))
from regression_support.terminal_review import collect_pool, review, continue_round
from mah2.dsstar.harness import initial
from mah2.dsstar import provider
from mah2.dsstar.sandbox import Sandbox
from mah2.runtime import hashes
from mah2.task_context import input_packet
from report_cycle_pilot import cost, lineage_cost, lineage
from submit_cycle_pilot import retained_baseline_files


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    names = [*ROOT.glob('mah2/**/*.py'), ROOT / 'scripts/review_cycle_candidates.py',
             ROOT / 'scripts/report_cycle_pilot.py', ROOT / 'scripts/run_cycle_pilot.py']
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(names)}


def total_cost(config, calibration_only=False):
    groups = config['shared_calibration_groups']
    if not calibration_only:
        groups = groups + config['shared_run_groups']
    return sum(cost(p)['total_upper_usd'] for group in set(groups)
               for p in (ROOT / 'runs' / group).glob('*/*') if p.is_dir())


def selection_only_change(old_sources, source_path):
    """Reuse generation validation only when all runtime changes are inside select()."""
    current = source_hashes()
    changed = {name for name in set(old_sources) | set(current) if old_sources.get(name) != current.get(name)}
    optimizer = 'mah2/dsstar/optimizer.py'
    if changed - {optimizer, 'scripts/review_cycle_candidates.py'}:
        raise RuntimeError('Generation source changed; a full new fixture is required')
    old = (ROOT/source_path).read_text()
    if hashlib.sha256(old.encode()).hexdigest() != old_sources[optimizer]:
        raise RuntimeError('Old optimizer source does not match its live validation')
    def without_selection(source):
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Experiment')
        cls.body = [n for n in cls.body if not isinstance(n, ast.FunctionDef) or n.name != 'select']
        return ast.dump(tree)
    if without_selection(old) != without_selection((ROOT / optimizer).read_text()):
        raise RuntimeError('Non-selection optimizer behavior changed')


def calibrate_selector(config, cap, label):
    """Combine unchanged live generation evidence with a fresh live selector check."""
    previous = ROOT / config['continuation_calibration_parent']
    validation = json.loads((previous / 'result.json').read_text())
    if not validation.get('new_team_replays_passed') or validation.get('budget_truncated'):
        raise RuntimeError('Prior generation fixture did not finish successfully')
    selection_only_change(validation['calibration_source_hashes'], config['generation_validation_source'])
    old_config = json.loads((previous / 'config.json').read_text())
    for key in ('dsstar','model','provider_slug','reasoning','input_profile','execution','task_environments'):
        if old_config.get(key) != config.get(key):raise RuntimeError('Generation fixture configuration changed: '+key)
    parent = ROOT / 'private' / (config['run_group'] + '_' + label + '_parent')
    parent.mkdir(exist_ok=False)
    data = Path(validation['parent']) / 'data'
    packet = json.loads((previous / 'input_packet.json').read_text())
    (parent / 'input_packet.json').write_text(json.dumps(packet))
    (parent / 'result.json').write_text('{}')
    generation_files = {str((previous/'result.json').relative_to(ROOT)):digest(previous/'result.json')}
    source = previous / 'optimization/round_3'
    entries = [(source/'previous', initial())]
    for name in ('reference','candidate_a','candidate_b','successor'):
        run = source/name
        if (run/'replay/pred_results/join.csv').read_text() != 'id,value,label\n1,10,A\n2,20,B\n':
            raise RuntimeError('A generated fixture program did not produce the correct output')
        entries.append((run,json.loads((source/f'{name}_harness.json').read_text())))
    for i,(run,harness) in enumerate(entries):
        target=parent/f'optimization/round_{i//4+1}'/('reference','candidate_a','candidate_b','successor')[i%4]
        target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(run.resolve(),target_is_directory=True)
        (target.parent/f'{target.name}_harness.json').write_text(json.dumps(harness))
        for name in ('submission.py','outcome.json','replay/pred_results/join.csv'):
            p=(run/name).resolve();generation_files[str(p.relative_to(ROOT))]=digest(p)
    (parent/'optimization/successor').symlink_to('round_1/reference',target_is_directory=True)
    (parent/'optimization/final_harness.json').write_text(json.dumps(initial()))
    destination=ROOT/'runs'/config['calibration_group']/'whole_team_harness2'/label
    def grade(task,selected,out,current_config):
        assert (destination/'commit.json').exists()
        return dict(official_success=int((selected/'replay/pred_results/join.csv').read_text()=='id,value,label\n1,10,A\n2,20,B\n'),status='public_fixture')
    result=review(parent,destination,config,'fixture',0.,cap,data=data,grader=grade,client_factory=provider.Client)
    result.update(fixture_passed=bool(result['grade']['official_success']==1 and result['selected_label']!='previous' and result['review_decision'].get('replacement_probe')),
                  new_team_replays_passed=True,calibration_source_hashes=source_hashes(),
                  validation_type='unchanged live generation components plus fresh live selector',generation_fixture_files=generation_files)
    (destination/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(fixture_passed=result['fixture_passed'],new_selector_cost_usd=result['review_cost_usd'])),flush=True)
    if not result['fixture_passed']:raise RuntimeError('Live selector fixture failed')


def calibrate(config):
    cap = min(config.get('continuation_calibration_cap_usd',.04), config['budget']['calibration_cap'] - total_cost(config, True) - 1e-6,
              config['budget']['total_cap'] - total_cost(config) - 1e-6)
    if cap <= 0:
        raise RuntimeError('No authorized calibration allowance remains')
    attempt = config.get('review_calibration_attempt', 0)
    if type(attempt) is not int or attempt < 0:
        raise ValueError('Calibration attempt must be a nonnegative integer')
    label = 'fixture' if attempt == 0 else f'fixture_attempt{attempt}'
    if config.get('continuation_calibration_parent'):
        calibrate_selector(config,cap,label)
        return
    parent = ROOT / 'private' / (config['run_group'] + '_' + label + '_parent')
    parent.mkdir(exist_ok=False)
    data = parent / 'data'
    data.mkdir()
    (data / 'a.csv').write_text('id,value\n2,20\n1,10\n')
    (data / 'b.csv').write_text('id,label\n1,A\n2,B\n')
    packet = dict(task_inst='Join a.csv and b.csv on id. Sort by id; write pred_results/join.csv with columns id,value,label.',
                  output_fname='pred_results/join.csv')
    (parent / 'input_packet.json').write_text(json.dumps(packet))
    code = "import pandas as pd\nfrom pathlib import Path\nPath('pred_results').mkdir(exist_ok=True)\ndf=pd.read_csv('data/a.csv').merge(pd.read_csv('data/b.csv'),on='id').sort_values('id')\n"
    for candidate_label, suffix in [('reference', "df.iloc[:1].to_csv('pred_results/join.csv',index=False)\n"),
                          ('candidate_a', "df.to_csv('pred_results/join.csv',index=False)\n")]:
        run = parent / 'optimization/round_1' / candidate_label
        run.mkdir(parents=True)
        program = code + suffix
        (run / 'submission.py').write_text(program)
        dc = {**config['dsstar'], 'science_environment': '.venv-science'}
        replay = Sandbox(run / 'replay', data, dc).run(program, 'submission.py', timeout=60)
        if replay['returncode'] != 0:
            raise RuntimeError('Fixture execution failed')
        (run / 'outcome.json').write_text(json.dumps(dict(runnable=True, replay=replay)))
        (run / 'trace.jsonl').write_text(json.dumps(dict(id='e0000', kind='final_replay', runnable=True, replay=replay))+'\n')
        (run.parent / f'{candidate_label}_harness.json').write_text(json.dumps(initial()))
    (parent / 'optimization/successor').symlink_to('round_1/reference', target_is_directory=True)
    (parent / 'optimization/final_harness.json').write_text(json.dumps(initial()))
    (parent / 'commit.json').write_text(json.dumps(dict(status='completed', cycles_completed=0)))
    (parent / 'result.json').write_text(json.dumps(dict(fixture_parent=True)))
    destination = ROOT / 'runs' / config['calibration_group'] / 'whole_team_harness2' / label
    def grade_fixture(task, selected, out, current_config):
        assert (destination / 'commit.json').is_file()
        passed = (selected / 'replay/pred_results/join.csv').read_text() == 'id,value,label\n1,10,A\n2,20,B\n'
        return dict(status='public_fixture', official_success=int(passed))
    operation = continue_round if config.get('continuation_round') else review
    fixture_config = dict(config, fixture_stage_allowance_usd=config['terminal_review_cap_usd']) if config.get('continuation_round') else config
    result = operation(parent, destination, fixture_config, 'fixture', 0., cap, data=data, grader=grade_fixture)
    result['fixture_passed'] = bool(result['grade']['official_success'] == 1
                                    and result['selected_label'] != 'previous'
                                    and result['review_decision'].get('replacement_probe'))
    if config.get('continuation_round'):
        outcomes = [destination/'optimization/round_3'/name/'outcome.json'
                    for name in ('reference','candidate_a','candidate_b','successor')]
        result['new_team_replays_passed'] = all(p.exists() and json.loads(p.read_text())['runnable'] for p in outcomes)
        result['fixture_passed'] = bool(result['fixture_passed'] and result['new_team_replays_passed'] and not result['budget_truncated'])
    result['calibration_source_hashes'] = source_hashes()
    (destination / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(dict(fixture_passed=result['fixture_passed'], cost_usd=result['review_cost_usd'])), flush=True)
    if not result['fixture_passed']:
        raise RuntimeError('Terminal review fixture failed; benchmark review blocked')


def prepare_freeze(config, config_path):
    attempt = config.get('review_calibration_attempt', 0)
    label = 'fixture' if attempt == 0 else f'fixture_attempt{attempt}'
    fixture = ROOT / 'runs' / config['calibration_group'] / 'whole_team_harness2' / label / 'result.json'
    validation = json.loads(fixture.read_text())
    if not validation.get('fixture_passed') or validation.get('calibration_source_hashes') != source_hashes():
        raise RuntimeError('Missing or stale terminal-review calibration')
    fixture_config = json.loads((fixture.parent / 'config.json').read_text())
    for key in ('model', 'provider_slug', 'reasoning', 'execution', 'dsstar', 'task_environments',
                'input_profile', 'budget', 'terminal_review_cap_usd', 'continuation_round'):
        if fixture_config.get(key) != config.get(key):
            raise RuntimeError('Calibration configuration differs: ' + key)
    if total_cost(config, True) > config['budget']['calibration_cap']:
        raise RuntimeError('Shared calibration cap exceeded')
    files = {**source_hashes(), str(config_path.relative_to(ROOT)): digest(config_path)}
    files[str(fixture.relative_to(ROOT))] = digest(fixture)
    files[str((fixture.parent / 'config.json').relative_to(ROOT))] = digest(fixture.parent / 'config.json')
    for name, sha in validation.get('generation_fixture_files',{}).items():
        if digest(ROOT/name)!=sha:raise RuntimeError('Validated generation fixture changed')
        files[name]=sha
    for name in retained_baseline_files(config):
        files[name] = digest(ROOT / name)
    ready = json.loads((ROOT / 'provenance/task_readiness.json').read_text())
    for task in config['tasks']:
        parent = ROOT / 'runs' / config['candidate_parent_group'] / 'whole_team_harness2' / str(task)
        if not (parent / 'result.json').is_file():
            raise RuntimeError('Wait for the entire parent run before reviewing any benchmark task')
        old = json.loads((parent / 'config.json').read_text())
        if old['budget']['per_method_task_cap'] != config['budget']['per_method_task_cap']:
            raise RuntimeError('Parent task cap differs')
        for key in ('model', 'provider_slug', 'reasoning', 'execution', 'task_environments', 'input_profile'):
            if old.get(key) != config.get(key):
                raise RuntimeError('Parent setting mismatch: ' + key)
        expected = next(r['input_manifest'] for r in ready['rows'] if r['task'] == task)
        if hashes((ROOT / f'private/tasks/{task}/data').resolve()) != expected:
            raise RuntimeError('Public input data changed')
        manifest_parent = next((p for p in lineage(parent) if (p / 'input_manifest.json').exists()), None)
        if manifest_parent is None or json.loads((manifest_parent / 'input_manifest.json').read_text()) != expected:
            raise RuntimeError('Parent input manifest differs')
        raw = json.loads((ROOT / f'private/tasks/{task}' / config['packet_name']).read_text())
        if json.loads((parent / 'input_packet.json').read_text()) != input_packet(raw, 'historical_task_only'):
            raise RuntimeError('Parent task packet differs from the matched public input boundary')
        paths = [p / name for p in lineage(parent) for name in ('config.json', 'commit.json', 'input_packet.json',
                  'input_manifest.json', 'api/ledger.jsonl', 'optimization/library_after.json') if (p/name).exists()]
        for _, run, _ in collect_pool(parent):
            paths += [run / 'submission.py', run / 'outcome.json']
            paths += [p for p in (run / 'replay/pred_results').rglob('*') if p.is_file() and not p.is_symlink()]
        for p in paths:
            files[str(p.relative_to(ROOT))] = digest(p)
    return files


def run(config, config_path, shard=(0, 1), prepare_only=False):
    index, count = shard
    if count < 1 or not 0 <= index < count:
        raise ValueError('Invalid worker shard')
    files = prepare_freeze(config, config_path)
    remaining = [task for task in config['tasks'] if not (ROOT / 'runs' / config['run_group'] / 'whole_team_harness2' / str(task) / 'result.json').exists()]
    if total_cost(config) + len(remaining) * config['terminal_review_cap_usd'] > config['budget']['total_cap']:
        raise RuntimeError('Review reservation exceeds cumulative authorized allowance')
    frozen = ROOT / 'provenance' / (config['run_group'] + '_freeze.json')
    if not frozen.exists():
        subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'unittest', 'discover', '-s', 'tests'], cwd=ROOT, check=True)
    if frozen.exists():
        if json.loads(frozen.read_text())['source_and_parent_hashes'] != files:
            raise RuntimeError('Review source or parent evidence changed')
    else:
        with frozen.open('x') as f:
            json.dump(dict(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           source_and_parent_hashes=files, evaluation_type='adaptive third recursive round' if config.get('continuation_round') else 'cached-candidate terminal public-contract review'), f, indent=2)
    if prepare_only:
        print(json.dumps(dict(prepared=str(frozen))), flush=True)
        return
    for task in remaining:
        if config['tasks'].index(task) % count != index:
            continue
        if any(digest(ROOT / name) != sha for name, sha in files.items()):
            raise RuntimeError('Frozen evidence changed before review')
        parent = ROOT / 'runs' / config['candidate_parent_group'] / 'whole_team_harness2' / str(task)
        destination = ROOT / 'runs' / config['run_group'] / 'whole_team_harness2' / str(task)
        operation = continue_round if config.get('continuation_round') else review
        result = operation(parent, destination, config, task, lineage_cost(parent)['total_upper_usd'], config['terminal_review_cap_usd'])
        print(json.dumps(dict(task=task, official_success=result['grade'].get('official_success'),
                              combined_task_cost_usd=result['total_cost_usd'], review_cost_usd=result['review_cost_usd'])), flush=True)
        subprocess.run([str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/report_cycle_pilot.py'),
                        '--config', str(config_path.relative_to(ROOT))], check=True, stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config/cycles10_no_knowledge.json')
    parser.add_argument('--calibrate', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--shard', nargs=2, type=int, default=(0, 1))
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    config = json.loads(config_path.read_text())
    if not config.get('candidate_parent_group') or config.get('input_profile') != 'historical_task_only':
        raise RuntimeError('An explicit historical-task-only cached review configuration is required')
    if not os.environ.get('SLURM_JOB_ID') or len(os.sched_getaffinity(0)) != 4:
        raise RuntimeError('Run in a Slurm step pinned to exactly four CPUs')
    if args.calibrate:
        calibrate(config)
    else:
        run(config, config_path, args.shard, args.prepare_only)


if __name__ == '__main__':
    main()
