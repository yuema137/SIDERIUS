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

The optional dashboard has its own gitignored path configuration:

```bash
cp dashboard_config.example.yaml   dashboard_config.yaml
```

Task-specific scoring references, including TIDMAD anchor maps, belong to the external task package.

## API keys

Real runs need credentials from the machine that launches that experiment.
Keep them in a trusted, machine-owned file outside this checkout (permission
`600`), or use your scheduler/secret manager to inject them into the launch
process. Never commit, upload, log, or shell-trace credential values. A new
shell does not inherit an earlier shell's setup: prepare and check credentials
in the same shell that starts the run.

The launch caller must require the variables for the providers enabled by its
reviewed routing configuration. The bridge currently names `OPENAI_API_KEY`,
`GEMINI_API_KEY`, and `DEEPSEEK_API_KEY`; do not require keys for disabled
providers. Presence is only a local binding check—it does not prove validity,
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
    --llm_config configs/llm/openai_tiered_pro.json \
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
Do not rely on an implicit path search or on the bridge's existing dotenv
compatibility loading; that behavior is retained for compatibility, not a
reliable per-launch binding. Offline installation, focused tests, and
`--dry-run` onboarding do not need an API key.

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
