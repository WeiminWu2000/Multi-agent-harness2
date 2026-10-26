"""Portable, explicit-cost entry point for the canonical scientific executor."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare(args):
    config = json.loads(Path(args.config).read_text())
    from .task_context import input_packet
    task_path = Path(args.task)
    raw = json.loads(task_path.read_text()) if task_path.suffix == '.json' else {'task_inst': task_path.read_text(), 'output_fname': args.output_file}
    packet = input_packet(raw, 'historical_task_only')
    if args.rounds is not None:
        if not 1 <= args.rounds <= 10:
            raise ValueError('--rounds must be between 1 and 10')
        config['outer_cycles'] = args.rounds
    if not isinstance(packet['task_inst'], str) or not packet['task_inst'].strip():
        raise ValueError('task_inst must be nonempty text')
    output_name = Path(packet['output_fname'])
    if output_name.is_absolute() or '..' in output_name.parts or output_name.parts[:1] != ('pred_results',):
        raise ValueError('output_fname must be a relative path inside pred_results/')
    data = Path(args.data).resolve(strict=True)
    output = Path(args.output).resolve()
    if not data.is_dir():
        raise ValueError('Public data must be a directory')
    if output.exists():
        raise ValueError('Output already exists; choose a new directory. Runs are never silently overwritten.')
    if output.is_relative_to(data) or data.is_relative_to(output):
        raise ValueError('Run directory and public data must be disjoint')
    if any(p.is_symlink() for p in data.rglob('*')):
        raise ValueError('Public data must contain real files, not symlinks to other locations')
    if not 0 < args.budget <= config['budget']['per_method_task_cap']:
        raise ValueError('Budget must be positive and no larger than the configured per-task ceiling')
    science = Path(args.science_env).expanduser().resolve()
    config['science_environment'] = str(science)
    ds = config['dsstar']
    ds.pop('codex_coordination', None)
    ds['scoped_glm_coordination'] = args.method == 'harness2'
    if args.method == 'codex':
        binary = os.environ.get('MAH2_CODEX_BINARY') or shutil.which('codex')
        auth = os.environ.get('MAH2_CODEX_AUTH_FILE')
        if not binary or not auth:
            raise ValueError('Codex requires MAH2_CODEX_BINARY (or PATH) and MAH2_CODEX_AUTH_FILE')
        ds['codex_coordination'] = dict(binary=binary, auth_file=auth, model='gpt-6-astra',
                                      reasoning_effort='medium', max_calls_per_round=4, timeout_seconds=180)
    return config, packet, data, output, science


def execute(args, prepared):
    config, packet, data, output, science = prepared
    if sys.platform != 'linux' or not shutil.which('bwrap'):
        raise RuntimeError('Execution requires Linux and bubblewrap; no unsandboxed fallback')
    if not (science / 'bin/python').is_file():
        raise RuntimeError('Create the science environment before execution')
    from .gateway import Gateway, load_api_key, BudgetExceeded
    load_api_key()  # Validate before creating a run directory.
    from .runtime import hashes
    from .dsstar import provider
    from .dsstar.harness import initial
    from .dsstar.rollout import Rollout
    from .dsstar.recursion import run_recursive
    if args.method == 'mass':
        from .mass_rhi import run as mass_run
        if not (ROOT / '.runtime/node/bin/node').exists():
            raise RuntimeError('MASS requires the separately installed Qwen-code runtime; see docs/reproduction.md')
    output.mkdir(parents=True, exist_ok=False)
    # Four cores per worker, as in the study. Memory limits are supplied by the host/cgroup.
    available = sorted(os.sched_getaffinity(0))
    if len(available) < 4:
        raise RuntimeError('At least four allocated CPU cores are required')
    os.sched_setaffinity(0, available[:4])
    (output / 'packet.json').write_text(json.dumps(packet, indent=2))
    (output / 'config.json').write_text(json.dumps(config, indent=2))
    (output / 'input_manifest.json').write_text(json.dumps(hashes(data), indent=2))
    sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (ROOT / 'mah2').rglob('*.py')}
    (output / 'source_hashes.json').write_text(json.dumps(sources, indent=2))
    dc = {**config['dsstar'], 'science_environment': str(science), 'allowance_usd': args.budget,
          'input_per_million': config['budget']['input_per_million'],
          'output_per_million': config['budget']['output_per_million']}
    gateway = Gateway(output / 'api', config, cap=args.budget).start()
    provider.ACTIVE_GATEWAY = gateway
    selected = None
    result = dict(method=args.method, task=args.task_id, budget_usd=args.budget,
                  status='completed', official_success=None, evaluation='not_run')
    try:
        if args.method == 'base':
            selected = output / 'rollout'
            client = provider.Client(dc, provider.Budget(args.budget), output / 'ledger.jsonl')
            Rollout(client, initial(), dc, selected, data).run(packet)
        elif args.method == 'mass':
            mass = mass_run(gateway, config, packet, data, output / 'search', args.task_id, args.budget)
            selected = Path(mass['selected'])
        else:
            run_recursive(dc, output / 'optimization', 'whole_team', packet, data, [], config['outer_cycles'])
            selected = output / 'optimization/successor'
    except BudgetExceeded as exc:
        result.update(status='budget_truncated', error=str(exc))
    except Exception as exc:
        result.update(status='error', error=f'{type(exc).__name__}: {exc}')
    finally:
        gateway.close()
        provider.ACTIVE_GATEWAY = None
    result.update(provider_reported_usd=sum(float(r.get('usage', {}).get('cost') or 0) for r in gateway.calls),
                  charged_or_reserved_usd=gateway.charged)
    if (output / 'api/budget_denials.jsonl').exists() and result['status'] == 'completed':
        result['status'] = 'budget_truncated'
    if selected and (selected / 'outcome.json').exists():
        outcome = json.loads((selected / 'outcome.json').read_text())
        result.update(selected=str(selected.relative_to(output)), runnable=outcome['runnable'],
                      program_sha256=outcome.get('program_sha256'))
    if args.method == 'codex':
        from .dsstar.codex_editor import usage
        result['codex_usage'] = usage(output)
    (output / 'commit.json').write_text(json.dumps(result, indent=2))
    (output / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 1 if result['status'] == 'error' else 0


def run_main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default=str(ROOT / 'config/study.json'))
    p.add_argument('--method', choices=['base', 'harness2', 'mass', 'codex'], default='harness2')
    p.add_argument('--task', required=True, help='Task JSON, or a plain-text/Markdown instruction file')
    p.add_argument('--output-file', default='pred_results/result.csv', help='Required output for a text task; JSON tasks specify this inside their packet')
    p.add_argument('--rounds', type=int, help='Sequential refinement rounds (default: 3); total task allowance is unchanged')
    p.add_argument('--data', required=True, help='Public input directory only')
    p.add_argument('--output', required=True, help='New run directory')
    p.add_argument('--task-id', type=int, default=999)
    p.add_argument('--science-env', default=str(ROOT / '.venv-science'))
    p.add_argument('--budget', type=float, default=1.0)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true', help='Make paid model calls; default is a free configuration check')
    mode.add_argument('--dry-run', action='store_true', help='Preview the task and configuration without model calls (default)')
    args = p.parse_args(argv)
    try:
        prepared = prepare(args)
        if not args.execute:
            print(json.dumps(dict(valid=True, method=args.method, budget_usd=args.budget,
                                  rounds=prepared[0]['outer_cycles'] if args.method in ('harness2', 'codex') else None,
                                  paid_calls=False, note='Configuration check only; runtime dependencies not exercised'), indent=2))
            return 0
        return execute(args, prepared)
    except (ValueError, OSError, KeyError, RuntimeError, ImportError) as exc:
        p.exit(2, f'{type(exc).__name__}: {exc}\n')

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ('demo', 'setup', 'check', 'init', 'report'):
        command = args.pop(0)
        if command == 'demo':
            from .demo import main as action
        else:
            from . import tools
            action = getattr(tools, command)
        try:
            return action(args)
        except (ValueError, OSError, RuntimeError) as exc:
            print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
            return 2
    if args and args[0] == 'run':
        args.pop(0)
    elif not args or args in (['--help'], ['-h']):
        print('Multi-Agent Harness²\n\nCommands:\n  demo    Run a no-credential toy example with real Python executions\n  setup   Fetch pinned prompt dependencies and create a science environment\n  check   Check local prerequisites without model calls\n  init    Create a task packet and public-data directory\n  run     Run the scientific team on your task (dry-run by default)\n  report  Inspect a saved run and find its deliverables\n\nUse mah2 <command> --help for options.')
        return 0
    return run_main(args)

if __name__ == '__main__':
    raise SystemExit(main())
