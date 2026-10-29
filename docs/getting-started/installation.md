# Installation

**Time**: ~10 minutes, plus dataset download if you want to run real training.

---

## Prerequisites

- **Python 3.12+** (the repo pins `3.12`; the system `python3` on several lab
  machines is 3.8 and will fail)
- **[uv](https://docs.astral.sh/uv/)** package manager
- An **NVIDIA GPU with CUDA** — required for the supported real scientific
  training path, not for synthetic CPU examples or focused tests
- At least one LLM API key — OpenAI, Gemini and/or DeepSeek — for **real
  runs only**: the full unit suite runs with no key at all
- Optional: a Semantic Scholar key, only for the literature-review stage

## Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/yuema137/SIDERIUS.git && cd SIDERIUS
uv sync --group dev --frozen
source .venv/bin/activate
```

> Always use the project virtualenv (`.venv/bin/python`). Never the system
> `python` / `python3`.

### The one supported environment path

The reproducible form of the install — including the `dev` group with the
lint/type/test tools — is exactly what CI runs before every gate
(`.github/workflows/ci.yml`):

```bash
uv sync --group dev --frozen
```

`--frozen` installs from the committed `uv.lock` without re-resolving, so the
resulting environment is the one CI continuously verifies on every run. That
CI job is where the reproducibility claim is checked — we do not certify
ad-hoc variations (`pip install`, conda, unlocked `uv sync`). Use this form if
you plan to run the contributor gate (`make check`, see
[`CONTRIBUTING.md`](../../CONTRIBUTING.md)).

Supported interpreter and accelerator, today: **Python 3.12** (the version CI
installs) and **CUDA GPUs** for the supported real scientific training path.
Synthetic examples and focused tests can run on CPU. GPU discovery does not
restrict NVIDIA devices to a model-name list; the installed PyTorch build,
driver and selected execution path must actually support the device.

AMD/ROCm compatibility is experimental and has not been hardware-tested.
Discovery distinguishes ROCm from CUDA, but ROCm driver/process memory
accounting is not implemented, so paths requiring that resource protection
cannot run. The current frozen installation selects CUDA packages; it does not
install a ROCm environment. Do not disable required protection or replace
packages inside the frozen environment to bypass these limits. Intel GPU
execution is not currently supported. See the
[accelerator facts contract](../../src/core/accelerator-runtime.md) for the
difference between detected properties and a successful runtime check.

### Installed packages and checkout resources

The frozen sync installs the eight framework packages editably from `src/`.
Import names are unchanged (`core`, `agent`, `nodes`, `workflows`,
`execute_tools`, `ml_models`, `dashboard`, `tools`); do not prepend `src` or
inject source paths through `PYTHONPATH`.

A wheel contains these packages and their adjacent runtime resources. It does
not contain root launch scripts, examples, optional policy variants or machine
configuration. The required generic Health default is packaged: omit
`--health_checks_config`, or use
`execute_tools.health_checks.config.default_health_policy_path()` when a
library call needs its location. The old checkout path
`configs/health/health_checks.yaml` was removed. Nonempty missing/invalid explicit
overrides refuse without fallback; supply an external policy to customize
consequences, never edit site-packages. Task Health science remains external.
Library consumers supply explicit external task/config/data/workspace inputs;
the checkout remains necessary for the documented chain launcher. Installed
synthetic CPU execution is qualified separately from real scientific tasks or
accelerator support. See [source ownership and the installation witness](../../src/README.md).

## Generated Data Analysis programs

Runs that permit agent-generated analysis code require Linux user and network
namespaces, `bwrap` (the `bubblewrap` OS package), and `unshare` (the `util-linux`
OS package). Installing the Python environment alone does not provide them.
On Debian/Ubuntu execution hosts, install them before qualification:

```bash
sudo apt-get update
sudo apt-get install bubblewrap util-linux
```

The supported deployment readiness API is
`agent.data_analysis.analysis_code_sandbox.AnalysisCodeSandbox().probe()`.
Its `SandboxCapabilityReceipt` reports `available`, `protocol_id`, executable
paths and a refusal `reason`. It actually launches the namespace sandbox,
imports NumPy, tests the output mount and checks isolation; finding binaries
on `PATH` alone is insufficient. Run this check using the execution checkout's
`.venv/bin/python`, under the actual service user, environment and container or
systemd restrictions. Require `available=True` before starting a campaign that
permits generated analysis. Repeat after host/environment changes.

For a short execution qualification, from this exact checkout run:

```bash
REQUIRE_ANALYSIS_SANDBOX=1 .venv/bin/python -m pytest -q \
  tests/unit/agent/data_analysis/test_analysis_code_sandbox.py
```

This executes synthetic generated programs and tests authorized input reads,
output artifacts, isolation and resource failures, without task data, LLM calls
or GPU training. The flag turns sandbox-unavailable skips into failures; a
skipped sandbox test cannot qualify a deployment. Successful reference analysis
skills do not qualify generated code, which uses this separate execution path.
The runtime continues to refuse generated code if isolation is unavailable;
do not bypass it or grant generated programs broader host access.

## Machine-local configuration

Declare the physical dataset root with `--data_dir` and the run-output root
with `--workspace`. Both are caller-owned locations outside the checkout;
the framework does not recover them from a task-specific machine config.
Choose the task with `--task_composition`. See [Your first run](first-run.md)
for a complete Quickstart command.

Child training, inference and scoring processes inherit the operating system's
existing address-space limits by default. Infra does not add a machine-specific
memory cap. This does not mean unlimited memory or protection from physical-RAM
exhaustion. Optional `SIDERIUS_SUBPROCESS_RSS_GB` retains its historical name but
sets **virtual address space (`RLIMIT_AS`), not resident RAM (`RSS`)**. Choose a
cap only when you know the execution environment's requirements; CUDA mappings
alone can reserve substantial address space. Use one nonnegative integer for all
roles or a complete `training=N,inference=N,scoring=N` mapping. Explicit `0` adds
no cap and leaves inherited OS restrictions intact. Never infer a universal cap
from another machine's RAM/GPU size. Configuration and provenance are described
in the [execution contract](../../src/core/core-contract.md).

The optional dashboard has its own gitignored path configuration:

```bash
cp dashboard_config.example.yaml   dashboard_config.yaml
```

Task-specific scoring references, including TIDMAD anchor maps, belong to the external task package.

## API keys

Each entry point reads credentials from a different source. This table is the
single map; the linked procedures own the details.

| Entry point | Where keys are read from | Procedure |
| --- | --- | --- |
| Command-line chain and node CLIs (`scripts/launch/run_chain.sh`, `src/workflows/run_one_iteration.py`, node `main()`s) | Environment of the launching process. Recommended: a trusted external mode-`600` credential file sourced in that shell, or managed secret injection. Compatibility only: a gitignored `.env` in the checkout (see [Compatibility `.env` loading](#compatibility-env-loading)) | This section, below |
| Browser candidate console (`candidate_console`) | Only the `credential_file` named in the console configuration (owner-only mode `600`; a JSON object or a dotenv file, which may be the checkout `.env`), limited to the task's `candidate_environment_names`. Shell exports and a `.env` that `credential_file` does not name do not satisfy its readiness or Launch check | [Console credentials](../../src/tools/candidate_console/README.md#credentials), [configuration contract](../../src/tools/candidate_console/console-contract.md#configuration) |
| Detached candidate operations from code or CLI (`submit_operation`, `python -m tools.candidate_operations submit`) | Python: the `launch_environment` mapping the caller passes. CLI: the environment of the launching process. Only the request's declared provider names are checked and forwarded to the new process; an existing operation ID replays without reading values | [Operations contract](../../src/tools/candidate_operations/candidate-operations-contract.md#store-and-admission) |
| Resume of a paused research loop | The same source as its submit route above (code/CLI), or the console's `credential_file` for **Resume loop**; either way the names are the original launch request's, rechecked at Resume | [Loop control recipe](../../src/tools/candidate_operations/candidate-operations-contract.md#control-an-authored-loop-from-code-or-the-cli), [console Pause and Resume](../../src/tools/candidate_console/console-contract.md#pause-and-resume) |
| Paper resolver (Semantic Scholar) | `S2_API_KEY` in the calling process; source checkouts fall back to the checkout `.env` when the variable is absent | [Semantic Scholar key](#semantic-scholar-key) |

Supported provider identifiers and credential names are declared in
`src/agent/llm_settings.py` (`KNOWN_PROVIDERS` and `OPTIONAL_PROVIDERS`):

| Service / model family | `provider` | Credential variable |
| --- | --- | --- |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Google Gemini | `gemini` | `GEMINI_API_KEY` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` |
| Anthropic / Claude | `anthropic` | `ANTHROPIC_API_KEY` |
| Moonshot / Kimi | `moonshot` | `MOONSHOT_API_KEY` |
| Z.AI / GLM | `zai` | `ZAI_API_KEY` |

Anthropic, Moonshot and Z.AI require an explicit `model_id` and the
`pydantic-ai` extra. Follow the [additional-provider setup](../../src/agent/llm_transport/README.md)
and test the operations your selected model needs; an adapter does not establish
account access or support for every model operation.

Offline installation, focused tests and `--dry-run` need none of them.

### Command-line procedure

Real runs need credentials from the machine that launches that experiment.
Keep them in a trusted, machine-owned file outside this checkout (permission
`600`), or use your scheduler/secret manager to inject them into the launch
process. Never commit, upload, log, or shell-trace credential values. A new
shell does not inherit an earlier shell's setup: prepare and check credentials
in the same shell that starts the run.

The launch caller must require the variables for the providers enabled by its
reviewed routing configuration, using the provider table above. Do not require
keys for disabled providers. Presence is only a local binding check—it does not prove validity,
quota, or network reachability. For a trusted shell-compatible credentials
file, this complete pattern checks names only and then invokes the real launch
in the same shell (replace the required list and final command with the
experiment's reviewed values):

```bash
(
  set +x
  set -euo pipefail
  CREDENTIAL_FILE="/absolute/path/to/credential-file"
  if [[ ! -r "$CREDENTIAL_FILE" ]]; then
    echo "credential file is missing or unreadable" >&2
    exit 1
  fi
  set -a
  # The file must contain trusted shell-compatible variable assignments only.
  # shellcheck disable=SC1090
  source "$CREDENTIAL_FILE"
  set +a

  required_credentials=(OPENAI_API_KEY)  # match the selected routing
  .venv/bin/python - "${required_credentials[@]}" <<'PY'
import os
import sys

missing = [name for name in sys.argv[1:] if not os.environ.get(name, "").strip()]
if missing:
    print("missing or empty required credential(s): " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
PY

  bash scripts/launch/run_chain.sh \
    --mode lilab \
    --workspace /path/to/run-workspace \
    --run_name reviewed_run \
    --task_composition /path/to/task/composition.yaml \
    --data_dir /path/to/task/data \
    --llm_config configs/llm/openai_smoke_luna.json \
    --no-ml_lit_review_enabled \
    --healthgate_mode blocking \
    --result_authority diagnostic \
    --num_iterations 1 \
    --max_rounds 1
)
```

Managed injection is equivalent when the secret manager exports the reviewed
variables before this check and the launch command remains in this process.
Adapt `required_credentials` and the routing configuration when another
provider or optional service is enabled; disabled providers remain omitted.
Offline installation, focused tests, and `--dry-run` onboarding do not need an
API key.

### Compatibility `.env` loading

Command-line processes also load dotenv files. This is retained for
compatibility; it is not a reliable per-launch binding, so do not depend on it
for effectful runs:

- In a source checkout, `src/workflows/run_one_iteration.py` (which
  `run_chain.sh` invokes) loads `<checkout>/.env` when the module is imported.
- Every `LLMBridge` construction calls python-dotenv's default search
  (`find_dotenv()`, then `load_dotenv` on its result). It uses the nearest
  `.env` found by walking upward from `src/agent/` (from the current working
  directory in a REPL, a notebook or under a debugger/coverage tracer). In a
  source checkout this is normally `<checkout>/.env`, but if the checkout has
  none the search continues to its parent directories: a git worktree under
  another checkout picks up that checkout's `.env`, and an installed package
  can pick up a `.env` above its virtual environment or in the home directory.
- The paper resolver also loads the checkout's `.env` as a compatibility fallback
  when `S2_API_KEY` is absent. No loader overrides a variable that is
  already set; all add every missing variable in the file, not only keys.
  `PYTHON_DOTENV_DISABLED=1` disables all three loaders.
- The command-line and bridge loaders above (not the paper resolver) report
  what they load through one shared helper. Reporting adds log records only:
  the loaded file, precedence and exit status stay as described. When a non-empty
  file is actually read (even when every variable in it was already set and
  nothing was added), it logs once per process per file, at INFO on logger
  `agent.credential_environment`:
  `Compatibility dotenv loaded <resolved path> (variables already set in the environment take precedence).`
  It then emits a WARNING when the file is outside the SIDERIUS source
  checkout (`... is outside the SIDERIUS checkout <root>; it was found by
  searching parent directories. ...`), when no source checkout exists
  (`... was loaded but no SIDERIUS source checkout was detected; ...`), or
  when the file's mode grants any group/other permission (`... is accessible
  to group or other users (mode 644); restrict it with chmod 600.`). Nothing
  is logged when the file is absent, empty or `PYTHON_DOTENV_DISABLED=1`.
- When a provider's key variable (for example `GEMINI_API_KEY`) is set but
  empty or whitespace-only, the bridge logs a WARNING naming the variable and
  provider (`GEMINI_API_KEY is set but empty or whitespace-only; ...`) and
  continues as before; an unset variable behaves as before. No
  message contains a value.
- `.env` is ignored by the checkout's `.gitignore` (pattern `*.env`). Keeping
  values there still places secrets inside the source tree, which this
  procedure avoids.

The browser console does not accept this route: its readiness and Launch checks
read only `credential_file`, which may name a mode-`600` dotenv file such as this
`.env`. Its operation contract records that downstream
native processes may still call the bridge's loader; see
[candidate operations](../../src/tools/candidate_operations/candidate-operations-contract.md).

### Semantic Scholar key

For authenticated Semantic Scholar lookup, export `S2_API_KEY` in the process
that calls the paper resolver; an LLM key is not required for that standalone
operation. Source checkouts also support a compatibility fallback: when the
variable is absent, the resolver loads that checkout's `.env` before requesting
Semantic Scholar. This adds all missing variables from the file, not just the
key, and never overrides existing values. An explicitly empty `S2_API_KEY`
prevents fallback; `PYTHON_DOTENV_DISABLED=1` disables dotenv loading. Installed
packages without a source checkout use environment variables only. See the
[resolver contract](../../src/agent/skills/paper_resolver_skill/paper_resolver_skill.md#credentials-and-checkout-compatibility)
for lookup, error and cache behavior.

## Verify

```bash
.venv/bin/python -m pytest \
  tests/unit/examples/test_quickstart_pack.py::test_composition_authority_resolves_from_this_checkout \
  tests/unit/examples/test_quickstart_pack.py::test_shipped_manifest_composes_with_the_declared_values -q
```

These bounded checks verify checkout origin and the shipped synthetic manifest
without a provider, network, GPU, or training. For broader validation, run the
affected tests described in `CLAUDE.md` and `CONTRIBUTING.md`; formal PR CI is
the canonical final-head check. The provider diagnostic below is optional and
effectful, not part of offline installation verification.

If you choose to inspect configured providers, run the diagnostic explicitly;
it calls provider APIs and is not an installation or checkout test:

```bash
.venv/bin/python scripts/diagnostics/check_agent_environment.py
```

## Moving to a different machine or GPU

This is config-only — no code changes:

1. In this exact checkout, run `uv sync --group dev --frozen`.
2. Stage the task's inputs outside the checkout and pass their location via
   `--data_dir`; select a persistent external `--workspace`.
3. Supply the machine's API credentials without committing them.
4. Select the task composition and budgets explicitly for that experiment.

The GPU is detected at runtime; verify that the chosen experiment budgets fit
the new device rather than assuming a hardware move preserves its operating
envelope. On a multi-GPU node, select one externally with `CUDA_VISIBLE_DEVICES`.

---

## Next

- [Your first run](first-run.md)
- [What SIDERIUS is](../concepts/overview.md)
