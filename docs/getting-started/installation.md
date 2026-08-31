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
uv sync && source .venv/bin/activate
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

## Machine-local configuration

Two config files are gitignored because they hold paths specific to your machine.
Copy the templates and edit them:

```bash
cp tidmad_data_config.example.yaml tidmad_data_config.yaml
cp dashboard_config.example.yaml   dashboard_config.yaml
```

`tidmad_data_config.yaml` holds two paths:

| key | meaning |
|---|---|
| `tidmad_data_dir` | where raw TIDMAD `.h5` files live |
| `siderius_data_dir` | where run outputs are written |

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
python env_validation/test_agent_env.py     # environment + API reachability
uv run pytest tests/unit/ -q                # no GPU, no API calls, mocked LLM
```

The unit suite is the CI gate: mocked LLM, no GPU, no network. If it passes, your
checkout is sound.

## Moving to a different machine or GPU

This is config-only — no code changes:

1. `uv sync`
2. set the two paths in `tidmad_data_config.yaml` and stage the data there
3. put your API keys in `.env`

The GPU is detected at runtime and the VRAM budget scales to it, so a different
card needs no configuration. On a multi-GPU node, select one externally with
`CUDA_VISIBLE_DEVICES`.

Optionally, per-server scoring wall-time calibration lives in
`core/server_configs/{hostname}.py`. An unknown host falls back to a default with
a one-time warning, and only the time *forecast* is affected.

---

## Next

- [Your first run](first-run.md)
- [What SIDERIUS is](../concepts/overview.md)
