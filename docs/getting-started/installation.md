# Installation

**Time**: ~10 minutes, plus dataset download if you want to run real training.

---

## Prerequisites

- **Python 3.12+** (the repo pins `3.12`; the system `python3` on several lab
  machines is 3.8 and will fail)
- **[uv](https://docs.astral.sh/uv/)** package manager
- An **NVIDIA GPU with CUDA** — required for real training, not for the test
  suite
- At least one LLM API key — OpenAI, Gemini and/or DeepSeek — for **real
  runs only**: the full unit suite runs with no key at all
- Optional: a Semantic Scholar key, only for the literature-review stage

## Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone git@github.com:Galileo-Sandbox/SIDERIUS.git && cd SIDERIUS
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
installs) and **CUDA GPUs only** for real training. The broader accelerator
matrix (CPU-only training, ROCm, MPS) is tracked in issue #291 — that issue,
not this page, owns the deeper answer.

### Installed packages and checkout resources

The frozen sync installs the eight framework packages editably from `src/`.
Import names are unchanged (`core`, `agent`, `nodes`, `workflows`,
`execute_tools`, `ml_models`, `dashboard`, `tools`); do not prepend `src` or
inject source paths through `PYTHONPATH`.

A wheel contains these packages and their adjacent runtime resources. It does
not contain root launch scripts, examples, policy YAML or machine configuration.
Library consumers supply explicit external task/config/data/workspace inputs;
the checkout remains necessary for the documented chain launcher. Installed
synthetic CPU execution is qualified separately from real scientific tasks or
accelerator support. See [source ownership and the installation witness](../../src/README.md).

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

Needed for real runs, not for the test suite — you can defer this until you
launch [a real run](first-run.md). Keys live in a gitignored `.env` at the
repository root; the LLM bridge loads it automatically:

```bash
cat > .env << 'EOF'
OPENAI_API_KEY=...
GEMINI_API_KEY=...       # optional
DEEPSEEK_API_KEY=...     # optional
S2_API_KEY=...           # optional, literature review only
EOF
```

## Verify

```bash
.venv/bin/python scripts/diagnostics/check_agent_environment.py  # opt-in; calls provider APIs
.venv/bin/python -m pytest tests/unit/ -q    # no GPU, no API calls, mocked LLM
```

The unit suite is the CI gate: mocked LLM, no GPU, no network. If it passes, your
checkout is sound.

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

Optionally, per-server scoring wall-time calibration lives in
`core/server_configs/{hostname}.py`. An unknown host falls back to a default with
a one-time warning, and only the time *forecast* is affected.

---

## Next

- [Your first run](first-run.md)
- [What SIDERIUS is](../concepts/overview.md)
