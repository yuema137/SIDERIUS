# Installation

**Time**: ~10 minutes, plus dataset download if you want to run real training.

---

## Prerequisites

- **Python 3.12+** (the repo pins `3.12`; the system `python3` on several lab
  machines is 3.8 and will fail)
- **[uv](https://docs.astral.sh/uv/)** package manager
- An **NVIDIA GPU with CUDA** — required for real training, not for the test
  suite
- At least one LLM API key: OpenAI, Gemini and/or DeepSeek
- Optional: a Semantic Scholar key, only for the literature-review stage

## Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone git@github.com:Galileo-Sandbox/SIDERIUS.git && cd SIDERIUS
uv sync && source .venv/bin/activate
```

> Always use the project virtualenv (`.venv/bin/python`). Never the system
> `python` / `python3`.

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

You do **not** need to precompute a scoring anchor map — it ships committed at
`reference_data/segment_anchors.json`.

## API keys

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
