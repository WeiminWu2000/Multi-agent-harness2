# Reproduction

## Three different kinds of reproduction

**Reporting reproduction** needs only Python and the committed `results/study.json`. `python scripts/report_results.py` recomputes denominators, strict success totals, observed GLM expenditure, and paired exact tests. These task outcomes are exported observations, not a rerun of private benchmark evaluations. The source report hash is preserved in the JSON.

**Algorithm regression** needs the pinned upstream prompt builders and, for the complete test suite, MASS. Run the installation and test commands in the README. The unit suite uses mock model responses; it does not prove that a current model endpoint returns the same responses as the study.

**Fresh live evaluation** needs API funding, a sandbox-capable Linux host, separately acquired benchmark data, scientific dependencies, and official graders. One new run is not expected to match the published outcomes exactly: the original endpoint did not support reproducible sampling seeds. Do not overwrite published results with a fresh run or merge incompatible settings under one denominator.

## Dependency ownership

`scripts/fetch_dependencies.py` fetches the exact DS-STAR and Harness² revisions recorded in NOTICE. The optional `--include-mass` retrieves MASS at its recorded revision. Existing checkouts are reused only when clean and pinned; the script does not overwrite local edits. All vendor directories are ignored and excluded from release archives. MASS's upstream NOTICE does not assign an open-source license to its code. Obtaining it separately does not make it part of this repository's Apache license.

For the MASS runtime, install Node and Qwen-code 0.20.0 into the ignored `.runtime` directory:

```bash
mkdir -p .runtime/node/bin
ln -s "$(command -v node)" .runtime/node/bin/node
npm install --prefix .runtime @qwen-code/qwen-code@0.20.0
```

Use a Node executable available inside the sandbox's system mounts (normally `/usr/bin/node`), or copy a suitable standalone installation into `.runtime/node`. Qwen-code is an execution client; GLM is the language model used in the reported MASS condition.

For the optional hybrid, configure `MAH2_CODEX_BINARY` and `MAH2_CODEX_AUTH_FILE` to existing local files. The observed experiment used Codex CLI 0.162.1, `gpt-6-astra`, medium reasoning, four calls per round, and a 180-second invocation limit. Model and CLI compatibility must be checked before a fresh run. The release does not install Codex, copy its authentication, or resume the stopped experiment.

## Benchmark input boundary

Acquire ScienceAgentBench and its data through the official project: https://github.com/OSU-NLP-Group/ScienceAgentBench. Preserve the upstream licenses and instructions. Neither its task dataset nor gold outputs are included here.

For each selected task, create a task JSON with `task_inst` and `output_fname`, and a separate directory containing only its public files. Required outputs must be beneath `pred_results/`. Do not put reference programs, graders, answer tables designated as private, credentials, or unrelated tasks into that directory. The CLI strips other packet fields, matching the task-instruction-only condition. The list of all 38 task IDs and their source groups is in `config/study.json`.

Install the task's scientific packages in the environment passed to `--science-env`. The original study used heterogeneous environments, including a dedicated MODNet environment for tasks 101 and 102. This release intentionally does not claim that one generic requirements file reproduces every scientific task. CPU-affinity and dependency differences can affect runtime and outcomes.

Run each method with a fresh output directory and its own allowance. The CLI pins the worker to four allocated CPU cores. Supply a 32-GiB memory limit through your scheduler or cgroup; the CLI does not implement a portable kernel memory controller. Use separate processes for parallel tasks because the provider binding and upstream MASS driver contain process-global state.

## Official evaluation

The CLI deliberately leaves `official_success` unset. Commit the final program first, then invoke the official task evaluator on its replay artifacts in a host-only workspace. Never pass the official score or targets back to the optimizer or select a different submission after seeing that score.

`mah2.runtime.official_grade` preserves the study adapter for independently prepared benchmark installations. It expects `private/task_registry.json`, `private/benchmark/eval_programs/gold_results`, and `private/tasks/<id>/data` relative to the checkout. A registry entry maps the string task ID to `folder` (the official dataset folder) and `grader` (the host-relative official grader path). It writes evaluator output beneath the host directory provided by the caller. Set the scientific environment appropriately before use; the original adapter's default grading environment is `.venv-science`.

That adapter retains the original bounded stdout parser. Long evaluator output can hide a terminal verdict outside the first 64 KiB. Inspect complete logs before labeling a wrapper error as a benchmark defect. The paper's task-22 audit found failures, not recovered successes. Task 29's official evaluator rejects its reference fixture; the primary results preserve that outcome, with a separately reported sensitivity analysis excluding task 29.

## Changes made for this release

The scientific editing prompts, ownership checks, recursion, selection, and budgeting logic come from the recorded `glm-coordination` revision. The release replaces one account-specific credential path with environment configuration, makes missing bubblewrap an explicit error, handles relative Python symlinks, and adds a portable CLI. Historical launch/review implementations are retained under test support only. The CLI is a new wrapper and was not used to generate the published benchmark outcomes.

The original Slurm jobs, environment directories, calibration artifacts, hidden datasets, full model traces, and private Git history are not distributed. The toy example and mock regression suite are not substitutes for the original live calibration. Validate the runtime and exact scientific environments before a new paid study. Record fresh code/config hashes and keep unsuccessful or interrupted runs in your accounting.

After preparing the private official benchmark installation, invoke the separate grader:

```bash
.venv/bin/python scripts/evaluate.py --run runs/task-1-harness2 \
  --task-id 1 --output private/evaluations/task-1-harness2 \
  --science-env .venv-science
```

The evaluation command checks the committed task ID and program hash, refuses to overwrite a verdict, and writes outside the optimization artifacts. It does not change candidate selection or invoke model inference.

## Environment and plots

`requirements-tested.txt` pins the Python packages used to validate this release's controller and regression suite on Python 3.12. It is not the original scientific-environment lockfile and does not supply every benchmark dependency. For an equivalent controller environment, install that file before `pip install --no-deps -e .`.

To regenerate numerical plots from the public results:

```bash
.venv/bin/python -m pip install -e '.[plots]'
.venv/bin/python scripts/plot_results.py
```

The generated PDF and PNG are placed in ignored `results/figures/`. The retention chart compares different task sets; a retained edit is not evidence of a causal scientific improvement.
