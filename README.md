# Multi-Agent Harness²

Recursive revision of scientific agent teams, with fixed model weights. A role editor and a coordination editor propose separate changes; candidate executions supply evidence for composition and program selection. The selected harness, runnable programs, and task-local lessons persist across three rounds and reset for the next task.

This repository contains the **scoped GLM implementation**, its optional Codex coordination transport, the MASS workflow-search adapter, and the base GLM team. It is a clean release of the experimental code, not the private experiment workspace.

## Results

On the 38 machine-graded ScienceAgentBench tasks:

| Method | Official passes | Reported GLM generation cost |
|---|---:|---:|
| Base GLM team | 11/38 | $0.68 |
| MASS workflow search, without training | 11/38 | $13.35 |
| Scoped GLM Harness² | 13/38 | $19.18 |

The Harness²–MASS paired exact test is **p = 0.754**. These single-run results do not establish reliable superiority. The final eighteen-task cohort favors MASS 5–4. The optional Codex experiment was stopped after 35 completed tasks: **14/35**, versus MASS **9/35** on those same tasks, with additional Codex usage. One interrupted and two unrun hybrid tasks are not failures or projected successes. The 64 visualization tasks are excluded.

`results/study.json` contains sanitized task-level outcomes, cohort counts, uncertainty, and retention diagnostics. Recompute the reported counts without credentials, downloads, or model calls:

```bash
python scripts/report_results.py
```

## Install and check an example

Use Python 3.11 or newer. Live execution requires Linux, bubblewrap, four allocated CPU cores, and a host/cgroup allocation of 32 GiB per worker. Use this repository as an editable checkout; upstream assets and configurations are resolved relative to it.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
python scripts/fetch_dependencies.py
.venv/bin/python -m mah2.cli \
  --task examples/join/task.json \
  --data examples/join/data \
  --output runs/join-check
```

The default command validates configuration only. It creates no run and makes no paid calls. The example uses two tiny CSV files created for this repository; it contains no benchmark data.

For actual execution, create a separate Python environment for scientific code and configure a credential in your shell:

```bash
python -m venv .venv-science
.venv/bin/python scripts/check_runtime.py
# Choose a private file containing your OpenRouter key; do not commit it.
export OPENROUTER_API_KEY_FILE=/path/to/private/openrouter.key
.venv/bin/python -m mah2.cli \
  --method harness2 \
  --task examples/join/task.json \
  --data examples/join/data \
  --output runs/join-execution \
  --budget 1.0 --execute
```

`--execute` explicitly enables paid model calls. `OPENROUTER_API_KEY` is also supported; no `.env` file is loaded automatically. The scientific environment must contain the packages needed by your task. The built-in join example can be solved with Python's standard library. Historical model identifiers, endpoint pinning, and cost estimates are in `config/study.json`; verify provider availability and rates before a new paid experiment.

Methods: `base`, `harness2`, `mass`, and `codex`. MASS and Codex require additional setup described in [reproduction](docs/reproduction.md). There is no silent fallback to unsandboxed execution or a different coordinator. Existing run directories are never overwritten.

## Code map

- `mah2/dsstar/`: role execution, scoped editing, public probing, selection, and recursion.
- `mah2/gateway.py`: host-only API transport and shared dollar accounting.
- `mah2/runtime.py`: isolated program execution, replay, and host-side evaluator adapter.
- `mah2/mass_rhi.py`: adapter to the separately obtained MASS implementation.
- `mah2/cli.py`: the single public run entry point.
- `config/study.json`: canonical scientific settings and task IDs; `workflow.json`: MASS's initial team.
- `examples/`: public toy inputs; `results/`: sanitized measured outcomes.
- `tests/`: regression coverage; `tests/regression_support/`: historical launcher and review helpers retained only for those tests.

The old whole-team workflow optimizer and terminal-review extension live only in regression-test support. They are not alternate public launchers. Private data, generated programs, model traces, credentials, vendor checkouts, runtime installations, and environments are excluded from Git and release archives.

## Tests and provenance

The complete historical regression suite includes the optional MASS adapter. Obtain it separately, subject to its upstream terms:

```bash
python scripts/fetch_dependencies.py --include-mass
.venv/bin/python -m unittest discover -s tests -v
python scripts/check_release.py
```

Tests use fixtures/mocks and make no model calls. [Reproduction](docs/reproduction.md) explains benchmark input preparation, evaluator separation, resource assumptions, and differences between the release wrapper and the measured experiment. [Architecture](docs/architecture.md) explains the recursive loop. `provenance/source.json` records the source revision and original file hashes.

## Attribution

The method adapts [Harness²](https://arxiv.org/abs/2610.14224); scientific execution uses prompt builders from [DS-STAR](https://arxiv.org/abs/2509.21825). The workflow-search comparison adapts [MASS](https://arxiv.org/abs/2610.12176) without its model-training stage. Tasks come from [ScienceAgentBench](https://arxiv.org/abs/2410.05080). Results are specific to these adaptations, input boundaries, and budgets.

Our code is provided under Apache-2.0. Dependencies retain their own terms; see [NOTICE](NOTICE). In particular, MASS is **not redistributed or relicensed** here. See [CONTRIBUTING.md](CONTRIBUTING.md) for changes and [SECURITY.md](SECURITY.md) for handling credentials and generated programs.
