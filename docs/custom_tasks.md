# Use your own task

The built-in team produces a standalone Python program and a required file under `pred_results/`. It is suited to local scientific analyses and data transformations. It does not browse the web, install packages from inside the program sandbox, or adapt arbitrary external agents.

## Create an input packet

Run `mah2 init tasks/my-task`. Edit the generated `task.json` and place public input files in `tasks/my-task/data/`. The `tasks/` directory is ignored by Git because user data may be private.

A useful instruction states:

- what each file and relevant column represents;
- the scientific computation or transformation to perform;
- units, grouping keys, missing-value handling, and validation requirements;
- the output filename, schema, and ordering.

For example, ask the team to compute per-sample means from measurements and require columns `sample_id,mean_value`, sorted by `sample_id`. Supply the measurements yourself. Avoid asking the agent to infer a hidden target definition.

Use `task_inst` and `output_fname` in JSON. Additional fields are stripped by the task-only input policy. Alternatively, write the instruction in a `.txt` or `.md` file and supply `--output-file pred_results/summary.csv`.

## Choose a run

```bash
mah2 run --task tasks/my-task/task.json --data tasks/my-task/data \
  --output runs/my-task --rounds 3 --budget 1.0 --dry-run
```

The budget is a total GLM task allowance, not a per-round allowance. More rounds divide that allowance more finely and may lead to rejected proposals or truncated stages. Start with the default configuration and a small task. The public CLI refuses a budget larger than the configuration's per-task ceiling.

The dry run validates the packet, paths and configured allowance. `mah2 check` checks dependencies and credential presence. Use `scripts/check_runtime.py` for an actual no-model sandbox test. These checks do not call the provider; only `--execute` starts paid work.

## Inspect the result

```bash
mah2 report --run runs/my-task
```

Open the selected `submission.py` and `replay/pred_results/` directory printed by the report. Each optimization round includes proposals, validation decisions, candidate execution artifacts, public probes, and the selected harness. Inspect unsuccessful decisions too: a valid proposal may still fail scientific execution or lose selection.

A reference retained on a tie is expected behavior. `budget_truncated` means budget controls prevented additional work; a runnable retained artifact may still exist. `error` records a terminal failure. If the process was interrupted before it wrote `result.json`, the report identifies the run as unfinished. This release does not resume partial paid runs automatically; inspect the saved trace before choosing a new directory and another allowance.

## Keep inputs and evaluation separate

Only place files the agent is allowed to read in the public data directory. It is mounted read-only under both `data/` and `datasets/`. Symlinks are rejected by the public CLI. Credentials, official graders, and private target outputs must remain outside it.

The scientific environment is mounted read-only but should still contain only trusted packages and runtime files. The runtime hides host files and disables program network access. Use the configured sandbox and host resource controls when running generated code.

A clean replay demonstrates executability, not scientific correctness. Evaluate the committed program using your own appropriate checks. For benchmark experiments, official scoring occurs only after commitment and must never guide a new candidate choice. The included evaluation command enforces commitment hashes and writes outside the agent run directory.

For several independent tasks, use separate processes and separate run directories, allocating four cores and 32 GiB per worker. Process-global provider bindings and the upstream MASS driver are not designed for concurrent tasks in one Python process.
