# Setup

## Local demo

The demo needs Linux, Python 3.11+, and bubblewrap. On Debian or Ubuntu, install bubblewrap using your usual system package workflow (`sudo apt install bubblewrap`). Other distributions provide their own packages. Some managed machines disable user namespaces; the sandbox check must work before running generated programs.

Install this checkout in editable mode and run `mah2 demo --output runs/demo`. The demo creates a minimal Python environment inside its output directory, uses only synthetic CSV inputs, and makes no model calls. It requires no upstream prompt checkouts. Its editors and scoring rules are scripted for teaching; it does not measure LLM capability.

## Live GLM tasks

`mah2 setup` obtains the pinned DS-STAR and Harness² revisions and creates `.venv-science`. It is idempotent for clean, pinned checkouts and a valid existing environment. It does not overwrite edits. Dependency downloads use the network; setup does not contact a model API.

Install each task's Python packages into `.venv-science`. The agent cannot install packages or download missing datasets from inside its program sandbox. Prefer supplying the necessary input files in advance.

Set either `OPENROUTER_API_KEY` or `OPENROUTER_API_KEY_FILE` in the launching shell. A key file must contain the key alone. No `.env` file is loaded automatically. `mah2 check` verifies local prerequisites and credential presence without printing credentials or making API calls. It does not verify account funding or endpoint responses. `mah2 check --offline` omits the credential requirement.

For a real sandbox smoke check with no model calls:

```bash
python scripts/check_runtime.py --science-env .venv-science
```

Allocate four CPU cores and 32 GiB memory per live worker using your scheduler or cgroup. The CLI pins execution to four available cores; memory allocation remains the host's responsibility. The demo's small standard-library programs do not require the study's full memory allocation.

## Models and budgets

`config/study.json` preserves the measured GLM model identifier, provider pin, reasoning settings, token limits, and estimated input/output prices. Current service availability and pricing can change. To use another model, copy this configuration locally and update the model/provider fields, supported options, and price estimates together; pass that file with `mah2 run --config ...`.

The gateway uses provider-reported costs when available and conservative reservations otherwise. Incorrect price estimates or provider accounting can affect budget enforcement. Codex usage is outside this GLM allowance and is never described as free. A new configuration is a new experimental setting, not a reproduction of the published results.

## Optional Codex coordination

Set `MAH2_CODEX_BINARY` to the Codex executable (or make `codex` available on PATH), and `MAH2_CODEX_AUTH_FILE` to your existing local authentication file. The compatibility target is the measured CLI 0.162.1 and `gpt-6-astra` configuration. The project does not install Codex or create/copy your login.

```bash
mah2 check --method codex
mah2 run --method codex --task task.json --data data \
  --output runs/hybrid --budget 1.0 --execute
```

Only coordination uses Codex. Native tools are disabled and public evidence requests are mediated by the same adapter. The separate Codex account usage appears in the run report. The release validation uses mocks rather than making new Codex requests.

## Optional MASS workflow search

Run `mah2 setup --include-mass` to obtain the pinned MASS source separately. Its upstream notice does not assign an open-source license; it is not bundled in this repository. Install the Node/Qwen-code runtime described in [reproduction](reproduction.md#dependency-ownership), then run `mah2 check --method mass`.

`mah2 run --method mass ... --execute` runs workflow search only. Qwen-code is the execution client; GLM remains the model in the default configuration. No language-model training occurs.
