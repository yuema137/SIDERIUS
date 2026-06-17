# SIDERIUS

### **S**cientific **I**nquiry, **D**esign, **E**xploration, and **R**easoning **I**ntegrated **U**sing multi-agent **S**ystems

An autonomous research platform that closes the loop on scientific discovery — hypothesis,
implementation, training, scoring, reflection, repeat. Inspired by Galileo's *Sidereus Nuncius*,
SIDERIUS uses a multi-agent architecture as a "digital telescope" for extracting physical
laws from noisy data. Current target: **denoising the TIDMAD SQUID time-series dataset** in
search of axion dark-matter signals.

> *"All truths are easy to understand once they are discovered; the point is to discover them."*
> — Galileo Galilei

---

## Architecture at a glance

SIDERIUS is **a typed, directed graph**. Every component is a node with a Pydantic input
schema and output schema; every edge is a typed `protocol` function; every LLM call routes
through `agent/llm_bridge.LLMBridge` (the single source of truth for retry policy and provider
routing — enforced by `tests/unit/agent/test_llm_bridge_singleton.py`).

See [`docs/architecture.md`](docs/architecture.md) for the full design and
[`CLAUDE.md`](CLAUDE.md) for the coding standards every contributor (human or LLM) must follow.
New nodes follow [`nodes/NODE_TEMPLATE.md`](nodes/NODE_TEMPLATE.md).

### The model-exploration loop (6 agents)

`workflows/model_exploration.py` implements the closed-loop iteration:

```
   ┌─────────────────────────── result_interpretation_agent
   │   (synthesizes records across models, surfaces bottlenecks)
   ▼
ml_literature_review                              ← gated by --ml_lit_review_enabled
   │   (S2 dynamic search → paper extraction → synthesis to ExpertContextItem findings)
   ▼
ml_model_proposal_agent
   │   (LLM proposes architecture, consumes lit-review findings as soft priors)
   ▼
ml_model_implementor
   │   (writes PyTorch plugin file + test skeleton + description.md)
   ▼
ml_code_validator_agent
   │   (7 checks: load, pytest, description, config, instantiation, gradient flow, LLM review)
   ▼
ml_hyperparameter_tune_agent
   │   (N rounds: plan → train → infer → score → reflect; planner / reflector use independent models)
   └────────► back to result_interpretation_agent
```

**Stop conditions**: `max_iterations` count or `target_score` threshold. Validation failures
trigger automatic retry with error feedback.

**Reliability guardrails** (full design in the linked docs):

- **Pre-flight resource gating** — the proposer must justify VRAM + wall-time estimates against
  trial / formal budgets. Over-budget proposals get up to 3 revision rounds. See
  [`docs/reliable_resource_proposer.md`](docs/reliable_resource_proposer.md).
- **Per-round attempt budget** — `--attempts_per_round` caps retries inside one planner round;
  `--max_fail_rounds` triggers a clean abort on a streak of fails. See
  [`docs/resource_estimator_implement.md`](docs/resource_estimator_implement.md).
- **Cumulative negative feedback** — architectural patterns that gate-exhausted in earlier
  iterations are tagged and forwarded as `disallowed_architectural_patterns`. The proposer
  won't re-propose them. See [`docs/adaptive_new_model_proposer.md`](docs/adaptive_new_model_proposer.md).

---

## Quick start

### Prerequisites

- Python 3.12+, NVIDIA GPU with CUDA, ~50 GB for TIDMAD raw data
- [uv](https://docs.astral.sh/uv/) package manager
- Gemini, OpenAI, and/or DeepSeek API key
- Optional (for lit-review): Semantic Scholar API key

### Install + configure

```bash
# 1. Clone + install
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone git@github.com:Galileo-Sandbox/SIDERIUS.git && cd SIDERIUS
uv sync && source .venv/bin/activate

# 2. Copy machine-specific config templates (the real files are gitignored)
cp tidmad_data_config.example.yaml tidmad_data_config.yaml
cp dashboard_config.example.yaml   dashboard_config.yaml
# edit each for your machine's paths

# 3. API keys (.env)
cat > .env << 'EOF'
GEMINI_API_KEY=...
OPENAI_API_KEY=...        # optional
DEEPSEEK_API_KEY=...      # optional, for lit-review
S2_API_KEY=...            # optional, for lit-review
EOF

# 4. Pre-compute the scoring anchor map (one-time, ~30 min)
python execute_tools/build_anchor_map.py --parallel -n 8

# 5. Smoke test
python env_validation/test_agent_env.py
uv run pytest tests/unit/ -q
```

---

## Common workflows

For full argument lists, run each entry point with `--help`. The agent-level descriptions
live in `nodes/<agent>/<agent>.md` (per the [`nodes/NODE_TEMPLATE.md`](nodes/NODE_TEMPLATE.md)
convention).

### Single-tuner run (most common)

One model, N rounds of hyperparameter tuning.

```bash
python nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py \
    --force_model gated_fno \
    --is_trial --max_rounds 20 \
    --human_advice_file advice/single_agent/gated_fno_freq_band_aware_v1.json \
    --run_name gated_fno_freq_band_aware_v1
```

The planner/reflector split (`--reflect_model_id`) cuts top-tier LLM quota use roughly in
half. See [`docs/break_tuner_agent.md`](docs/break_tuner_agent.md). Trial-mode details are in
[`docs/small_sample_trial.md`](docs/small_sample_trial.md).

### Multi-iteration exploration chain

The 6-agent loop, run N times in sequence. `run_chain.sh --mode {lilab,sdsc}` dispatches
to foreground (lilab) or Slurm `afterany` chain (SDSC).

```bash
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/exploration_chain_v1 \
    --run_name exploration_chain_v1 \
    --num_iterations 5 \
    --seed_paths /path/to/seed_records.json \
    --max_rounds 5 --max_epochs 5 \
    --human_advice_file advice/workflow/human_advice_chain_test.json \
    --llm_config llm_configs/openai_tiered_v1.json
```

Operational runbook (workspace conventions, restart from failed iter, SDSC memory rule):
[`docs/running_chain_test.md`](docs/running_chain_test.md).

### Literature-review-augmented chain

Add `--ml_lit_review_enabled` to enable the literature-review agent. It runs once per
iteration, between interpretation and proposal, surfacing recent papers as soft-prior
findings the proposer consumes.

```bash
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    [... usual args ...] \
    --ml_lit_review_enabled \
    --ml_lit_review_config configs/lit_review_config.yaml
```

Operator-visible knobs (root papers, S2 search budget, confidence rubric, task description)
live in [`configs/lit_review_config.yaml`](configs/lit_review_config.yaml). Behavioral
validation: [`docs/search_quality_validation.md`](docs/search_quality_validation.md)
(Checkpoint S sign-off; 0.90 max confidence, 4 v=1 findings across 5 runs).

### Baseline comparison + dashboard

```bash
# Baseline comparison across built-in models (raw / model / ceiling)
python scripts/run_comparison.py --models punet,wavenet,fcnet --is_trial

# Dashboard (Plotly + FastAPI)
cp dashboard_config.example.yaml dashboard_config.yaml   # then edit root_data_dir
python dashboard/main.py                                  # http://localhost:8000
```

For SSH-tunneling SDSC runs: `ssh -L 8000:localhost:8000 sdsc_expanse`.

---

## Project layout

```
SIDERIUS/
├── agent/                 # LLM transport + schemas + atomic skills
│   ├── llm_bridge.py      # ⭐ universal API gateway (single LLM call site)
│   ├── prompt_templates/  # per-stage prompt fragments (proposal + literature_review)
│   ├── schemas/           # Pydantic schemas + typed protocols/
│   ├── skills/            # atomic tools (training, inference, scoring, paper_resolver_skill, …)
│   └── utils/             # architectural-pattern tagger + proposer pre-flight helpers
│
├── nodes/                 # the agent implementations (one directory per node)
│   ├── NODE_TEMPLATE.md   # ⭐ contract every new node must follow
│   ├── result_interpretation_agent/
│   ├── ml_literature_review/
│   ├── ml_model_proposal_agent/
│   ├── ml_model_implementor/
│   ├── ml_code_validator_agent/
│   └── ml_hyperparameter_tune_agent/
│
├── workflows/             # deterministic graph traversals (model_exploration.py, llm_config.py)
├── core/                  # sandbox executor, hardware context, resume, server calibration
├── execute_tools/         # training / inference / scoring subprocess entry points
├── ml_models/             # built-in models + LossConfig + plugin loader
├── agent_generated/       # LLM-written plugins (gitignored; runtime-extended MODEL_REGISTRY)
├── dashboard/             # FastAPI + Plotly result browser
├── scripts/               # standalone runners (run_comparison, checkpoint_s_runner, baselines, …)
├── sdsc_submission_scripts/  # Slurm wrappers + chain runner (--mode lilab|sdsc)
├── advice/                # human-written advice JSON (single_agent/, workflow/)
├── llm_configs/           # per-stage LLM routing JSON (consumed by --llm_config)
├── configs/               # operator-visible YAML (lit_review_config.yaml)
├── reference_data/        # in-repo scoring baselines, signal frequencies, paper caches
├── docs/                  # design docs (see Documentation map below)
└── tests/{unit,integration}/   # 5-tier pyramid — see Testing
```

---

## Key invariants (must-read before contributing)

1. **Pydantic at every boundary**: LLM output → schema → execution. Never pass raw LLM
   output to a training/inference call.
2. **No hidden inter-node communication**: schemas + protocols + per-node storage are the
   *only* channels. No reading peer files by convention.
3. **`LLMBridge` is the single API gateway**: every agent goes through it. Direct
   `OpenAI()` constructors are CI-banned outside `agent/llm_bridge.py`.
4. **Plugins are pluggable + run-scoped**: agent-generated models extend `MODEL_REGISTRY`
   at runtime; each run stages its plugin into `{workspace}/plugins/{run_name}/`. See
   [`docs/run_scoped_plugins.md`](docs/run_scoped_plugins.md).
5. **One scoring ruler (Option B, global `s_max`)**: model output, raw-baseline, and
   perfect-denoiser ceiling all share the same FFT path and `log_{5.27}` step. See
   [`docs/align_denoising_score.md`](docs/align_denoising_score.md).
6. **`docs/commit_plan_*.md` is the live execution doc** for any multi-commit feature.
   Update the design doc and the code together; never let them drift.

---

## Testing

The pyramid has five tiers, distinguished by *how many nodes* a test exercises and
*whether it hits real LLM APIs / real training*. Full design in
[`docs/pseudo_test_infra.md`](docs/pseudo_test_infra.md).

```bash
# Always (CI gate)
uv run pytest tests/unit/ -q                    # mocked LLM, no GPU
uv run pytest tests/integration/ -q             # Tier 0 dual-mode (pseudo, ms)

# On demand — opt in via flag or marker
uv run pytest tests/integration/ --real-api-call --real-training -v   # real Tier 0
uv run pytest tests/integration/nodes/ -m real_run -v                 # Tier 1
uv run pytest tests/integration/protocols/ -m real_run -v             # Tier 2
uv run pytest tests/integration/workflows/ -m real_run -v             # Tier 3
```

`real_run`-marked tests skip automatically when the required API key is absent — they
never run in CI.

---

## Documentation map

The full set lives under [`docs/`](docs/). The curated start:

**Design + invariants**
- [`docs/architecture.md`](docs/architecture.md) — full system design (graph, nodes, protocols, skills)
- [`docs/external_agents_architecture.md`](docs/external_agents_architecture.md) — external-agent design vision
- [`CLAUDE.md`](CLAUDE.md) — coding standards every contributor must follow
- [`nodes/NODE_TEMPLATE.md`](nodes/NODE_TEMPLATE.md) — node-directory contract

**Workflow + agents**
- [`docs/full_loop_5_agents.md`](docs/full_loop_5_agents.md) — core 5-agent workflow (lit-review is the 6th)
- [`docs/external_agents_for_proposer.md`](docs/external_agents_for_proposer.md) — lit-review spec
- [`docs/commit_plan_ml_literature_review.md`](docs/commit_plan_ml_literature_review.md) — lit-review execution log
- [`docs/search_quality_validation.md`](docs/search_quality_validation.md) — Checkpoint S sign-off
- [`docs/running_chain_test.md`](docs/running_chain_test.md) — operational runbook (lilab + SDSC)

**Tuner + LLM infrastructure**
- [`docs/break_tuner_agent.md`](docs/break_tuner_agent.md) — planner/reflector split
- [`docs/small_sample_trial.md`](docs/small_sample_trial.md) — multi-fidelity trial/formal mode
- [`docs/hyperparameter_tuner_features.md`](docs/hyperparameter_tuner_features.md) — tuner prompt features

**Scoring**
- [`docs/align_denoising_score.md`](docs/align_denoising_score.md) — canonical: ruler derivation + legacy-parity proof
- [`reference_data/raw_and_ground_score.md`](reference_data/raw_and_ground_score.md) — per-file raw + ceiling table

**Reliability**
- [`docs/reliable_resource_proposer.md`](docs/reliable_resource_proposer.md) — pre-flight + revision loop
- [`docs/adaptive_new_model_proposer.md`](docs/adaptive_new_model_proposer.md) — cumulative negative feedback
- [`docs/run_scoped_plugins.md`](docs/run_scoped_plugins.md) — per-run plugin isolation

**Test infra**
- [`docs/pseudo_test_infra.md`](docs/pseudo_test_infra.md) — dual-mode pseudo/real tests

Per-developer memories live under `docs/memories/` (gitignored). See `docs/memories/README.md`.

---

## License

(To be added.)
