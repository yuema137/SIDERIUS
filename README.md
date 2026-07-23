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

Task-specific framing (`task_description` + `forward_contract`) lives in one operator-visible
file, [`configs/task_config.yaml`](configs/task_config.example.yaml), and is injected into
every LLM prompt via `{TASK_DESCRIPTION}` / `{FORWARD_CONTRACT}` placeholders. Porting
SIDERIUS to a new task starts with editing that file — no grep-and-replace across Python
sources. See [`docs/design/enable_global_task_config.md`](docs/design/enable_global_task_config.md).

See [`docs/architecture.md`](docs/architecture.md) for the full design,
[`docs/design/agent_composition_architecture.md`](docs/design/agent_composition_architecture.md)
for the three-layer roadmap, and [`CLAUDE.md`](CLAUDE.md) for the coding standards every
contributor (human or LLM) must follow. New nodes follow
[`nodes/NODE_TEMPLATE.md`](nodes/NODE_TEMPLATE.md).

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
   │   (writes PyTorch model plugin + optional custom loss plugin + test skeleton + description.md)
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
- **Pluggable HealthGates** — YAML-configured check-and-route gates (`configs/health_checks.yaml`)
  fire at tuner round boundaries. Six shipped checks: three blocking
  (`output_diversity`, `output_std`, `amplitude_collapse` — catch mode-collapse before it burns
  compute) and three recording-only (`pearson_dispersion`, `spectral_peak_ratio`,
  `per_file_output_std`), routing to one of `continue` / `skip_iter` / `skip_to_formal` /
  `invalidate_round`. Two run-level inputs (not YAML): `--health_gate_enabled` and
  `--health_gate_files` (shared monitored-file list; the effective config is materialized per
  workspace and pinned by the run-invariants lock). Skills live under
  `execute_tools/health_checks/`. See
  [`docs/design/pluggable_health_checks.md`](docs/design/pluggable_health_checks.md).
- **Cross-iteration knowledge accumulation** — runtime vocab, key findings, per-model knowledge
  cache, negative feedback (physical rejections + gate exhaustions), and the previous iter's
  proposal are all carried forward by `sdsc_submission_scripts/run_one_iteration.py` and injected
  into the next iter's proposer / interpreter / tuner. See
  [`docs/Consistent_growing_vocab_list.md`](docs/Consistent_growing_vocab_list.md).

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

# 2b. (Only if you're changing tasks) copy the task-config template and set
#     task_description + forward_contract for your problem. The committed
#     configs/task_config.yaml already carries the SQUID/TIDMAD defaults.
cp configs/task_config.example.yaml configs/task_config.yaml
# edit only if your task differs from the committed defaults

# 3. API keys (.env)
cat > .env << 'EOF'
GEMINI_API_KEY=...
OPENAI_API_KEY=...        # optional
DEEPSEEK_API_KEY=...      # optional, for lit-review
S2_API_KEY=...            # optional, for lit-review
EOF

# 4. Smoke test — the scoring anchor map ships committed at
#    reference_data/segment_anchors.json (a fixed artifact determined by the
#    TIDMAD data), so no per-machine precompute is needed.
python env_validation/test_agent_env.py
uv run pytest tests/unit/ -q
```

### Porting to a new server or GPU

Moving to a different server or GPU is **config-only — no code changes**:

1. `uv sync` to build the venv (step 1 above).
2. Set the two paths in `tidmad_data_config.yaml` (`tidmad_data_dir` = raw
   TIDMAD `.h5` files, `siderius_data_dir` = run outputs) and stage the `.h5`
   files at `tidmad_data_dir`. This gitignored file is the single server path
   profile.
3. Put your API keys in `.env`.

Everything else adapts automatically:

- **GPU** — `core/hardware_context.py` detects the active device at runtime and
  scales the VRAM budget to it (`0.80 ×` detected VRAM); device selection is
  `cuda:0` with CPU fallback. A different GPU needs no config. On a multi-GPU
  node, pick one with `CUDA_VISIBLE_DEVICES` (honored externally).
- **Scoring anchor map** — committed at `reference_data/segment_anchors.json`
  and used by default (resolved relative to the package, independent of the
  working directory). The run entry points always use the committed map;
  an `--anchor_map` override exists only on the reference-generation and
  standalone scoring scripts (`scripts/compute_ground_truth.py`,
  `scripts/compute_raw_baseline.py`, `execute_tools/denoising_score_single.py`).

Optional, not required to run:

- Per-server scoring wall-time calibration lives in
  `core/server_configs/{hostname}.py`; an unknown host falls back to a default
  (with a one-time warning) and only the time *forecast* is affected until a
  module is added. The per-GPU calibration cache location is overridable via
  `$SIDERIUS_CALIBRATION_DIR`.

---

## Common workflows

For full argument lists, run each entry point with `--help`. The agent-level descriptions
live in `nodes/<agent>/<agent>.md` (per the [`nodes/NODE_TEMPLATE.md`](nodes/NODE_TEMPLATE.md)
convention).

### Single-tuner run (most common)

One model, N rounds of hyperparameter tuning. The tuner CLI takes advice as a raw string via
`--human_advice`, not a file path — the JSON advice files under
[`advice/single_agent/`](advice/single_agent/) are meant for the chain runner. For an ad-hoc
single-tuner run, pass a short prompt inline:

```bash
python nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py \
    --force_model gated_fno \
    --is_trial --max_rounds 20 \
    --run_name gated_fno_smoke_v1
```

The planner/reflector split (`--reflect_provider` / `--reflect_model_id`) cuts top-tier LLM
quota use roughly in half. See [`docs/break_tuner_agent.md`](docs/break_tuner_agent.md).
Trial-mode details (sampling strategies, portions, time / VRAM budgets) are in
[`docs/small_sample_trial.md`](docs/small_sample_trial.md). Delta-based skip-formal and
bypass-time-budget gates suppress spurious formal promotions when a new plan's trial score
barely moves; their flags (`--skip_formal_min_delta`, `--bypass_formal_time_budget_min_delta`)
live on the CHAIN entry points (`run_chain.sh` / `run_one_iteration.py`), not on the
single-tuner CLI — see the `HyperparamTuningInput` schema docstring in
`agent/schemas/hyperparam_tuning.py` for semantics.

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

### Scoped run — restrict a chain to a file subset (DataScope)

`--data_scope` restricts everything a run touches — training, inference,
scoring, and HealthGate peeks — to a validation-file subset, enforced at the
sample-set builder and the sandbox I/O boundary (never by prompts). Both
`4-9` and `4,5,6,7,8,9` (and mixed `0-3,7`) spec forms canonicalize to one
sorted, deduplicated list. Partial scopes are snapshot-only and require an
explicit in-scope `--health_gate_files` monitored list when gates are on:

```bash
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    [... usual args ...] \
    --data_scope 4-9 --health_gate_files 4,7,9
```

To disable the HealthGate subsystem entirely (successful finite-score
records then count as valid candidates):

```bash
    --no-health_gate_enabled
```

The resolved scope + gate policy are pinned per workspace by
`run_invariants_lock.json` — re-running or resuming a workspace with a
different scope or gate config fails at startup, and aggregate scalars are
only comparable within one scope. Full design:
[`docs/design/enable_partial_file_list.md`](docs/design/enable_partial_file_list.md).

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
# one architecture per invocation (--model is single-valued)
python scripts/run_comparison.py --model punet --is_trial

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
├── workflows/             # deterministic graph traversals (model_exploration.py, llm_config.py, task_config.py)
├── core/                  # sandbox executor, hardware context, resume, server calibration
├── execute_tools/         # training / inference / scoring subprocess entry points
│   └── health_checks/     # pluggable HealthGate skills (output_diversity, amplitude_collapse, …)
├── ml_models/             # built-in models + LossConfig + plugin loader
├── agent_generated/       # LLM-written plugins (gitignored) — models AND custom losses;
│                          # runtime-extended MODEL_REGISTRY + LOSS_REGISTRY via CapabilityRegistry
├── dashboard/             # FastAPI + Plotly result browser
├── scripts/               # standalone runners (run_comparison, checkpoint_s_runner, baselines, …)
├── sdsc_submission_scripts/  # Slurm wrappers + chain runner (--mode lilab|sdsc)
├── advice/                # human-written advice JSON (single_agent/, workflow/ — incl. v15/v16 explorer configs)
├── llm_configs/           # per-stage LLM routing JSON (consumed by --llm_config)
├── configs/               # operator-visible YAML — task_config, lit_review_config, health_checks
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
- [`docs/design/agent_composition_architecture.md`](docs/design/agent_composition_architecture.md) — three-layer roadmap (nodes → protocols → orchestrators; Run Monitor vision)
- [`docs/external_agents_architecture.md`](docs/external_agents_architecture.md) — external-agent design vision
- [`CLAUDE.md`](CLAUDE.md) — coding standards every contributor must follow
- [`nodes/NODE_TEMPLATE.md`](nodes/NODE_TEMPLATE.md) — node-directory contract

**Workflow + agents**
- [`docs/full_loop_5_agents.md`](docs/full_loop_5_agents.md) — core 5-agent workflow (lit-review is the 6th)
- [`docs/external_agents_for_proposer.md`](docs/external_agents_for_proposer.md) — lit-review spec
- [`docs/commit_plan_ml_literature_review.md`](docs/commit_plan_ml_literature_review.md) — lit-review execution log
- [`docs/search_quality_validation.md`](docs/search_quality_validation.md) — Checkpoint S sign-off
- [`docs/running_chain_test.md`](docs/running_chain_test.md) — operational runbook (lilab + SDSC)
- [`docs/Consistent_growing_vocab_list.md`](docs/Consistent_growing_vocab_list.md) — cross-iteration knowledge carry-over (vocab, findings, cache, negatives, previous proposal)

**Custom-loss inventory + task config (recent)**
- [`docs/design/enable_loss_inventory.md`](docs/design/enable_loss_inventory.md) — proposer proposes custom loss plugins symmetric with model plugins; `LOSS_REGISTRY` + promotion contract
- [`docs/checkpoint_l_sign_off.md`](docs/checkpoint_l_sign_off.md) — Checkpoint L (loss inventory) Gate 2 + Gate 3 sign-off
- [`docs/design/enable_global_task_config.md`](docs/design/enable_global_task_config.md) — `configs/task_config.yaml` de-hardcodes `task_description` + `forward_contract` across implementor / proposer / tuner / lit-review
- [`docs/checkpoint_t_sign_off.md`](docs/checkpoint_t_sign_off.md) — Checkpoint T (task config) sign-off

**HealthGate + tuner controls**
- [`docs/design/pluggable_health_checks.md`](docs/design/pluggable_health_checks.md) — HealthGate skills + `configs/health_checks.yaml`
- [`docs/break_tuner_agent.md`](docs/break_tuner_agent.md) — planner/reflector split
- [`docs/small_sample_trial.md`](docs/small_sample_trial.md) — multi-fidelity trial/formal mode
- [`docs/hyperparameter_tuner_features.md`](docs/hyperparameter_tuner_features.md) — tuner prompt features
- [`docs/refactor_formal_round_strategy.md`](docs/refactor_formal_round_strategy.md) — strategy-based formal-round dispatch

**Scoring**
- [`docs/align_denoising_score.md`](docs/align_denoising_score.md) — canonical: ruler derivation + legacy-parity proof
- [`reference_data/raw_and_ground_score.md`](reference_data/raw_and_ground_score.md) — per-file raw + ceiling table

**Reliability**
- [`docs/reliable_resource_proposer.md`](docs/reliable_resource_proposer.md) — pre-flight + revision loop
- [`docs/adaptive_new_model_proposer.md`](docs/adaptive_new_model_proposer.md) — cumulative negative feedback
- [`docs/run_scoped_plugins.md`](docs/run_scoped_plugins.md) — per-run plugin isolation

**Test infra + gates**
- [`docs/pseudo_test_infra.md`](docs/pseudo_test_infra.md) — dual-mode pseudo/real tests
- [`docs/gates/gate_testing_standard.md`](docs/gates/gate_testing_standard.md) — canonical Gate testing standard (params + pass criteria)

Per-developer memories live under `docs/memories/` (gitignored). See `docs/memories/README.md`.

---

## License

(To be added.)
