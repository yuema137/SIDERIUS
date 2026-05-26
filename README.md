# SIDERIUS

### **S**cientific **I**nquiry, **D**esign, **E**xploration, and **R**easoning **I**ntegrated **U**sing multi-agent **S**ystems

**SIDERIUS** is an autonomous research platform designed to automate the full-loop scientific discovery process — from hypothesis formulation to experimental validation. Inspired by Galileo Galilei's *Sidereus Nuncius*, the project uses a multi-agent architecture to act as a "digital telescope," extracting fundamental physical laws from complex data.

The current target task is **denoising the TIDMAD SQUID time-series dataset** in search of axion dark-matter signals.

---

> *"All truths are easy to understand once they are discovered; the point is to discover them."*
> <p align="left"><b>—Galileo Galilei</b></p>

---

## Table of Contents

1. [Architecture at a glance](#architecture-at-a-glance)
2. [Project structure](#project-structure)
3. [Quick start](#quick-start)
4. [Usage recipes](#usage-recipes)
   - [Single-tuner run](#a-single-tuner-run-most-common)
   - [Multi-iteration exploration chain](#b-multi-iteration-exploration-chain)
   - [Dashboard](#c-dashboard)
5. [Built-in models, losses, and plugins](#built-in-models-losses-and-plugins)
6. [Scoring convention](#scoring-convention)
7. [Configuration files](#configuration-files)
8. [Testing](#testing)
9. [Server migration](#server-migration)
10. [Documentation index](#documentation-index)

---

## Architecture at a glance

SIDERIUS is built on a single unifying idea: **the whole system is a typed, directed graph**.

- Every component is a **node** — it has a validated input schema (`BaseModel`) and a validated output schema, and exposes a `run(input) -> output` method.
- **Edges** are typed **protocol** functions that map one node's output to the next node's input. No node communicates with another except through a protocol.
- **Workflows** execute pre-designed, deterministic paths through the graph. **Orchestrators** are LLM-powered agents that pursue a goal autonomously by selecting from a skill registry. Both expose the same `run(input) -> output` contract.
- **All LLM calls** in the entire system route through `agent/llm_bridge.LLMBridge`, which is the single source of truth for retry policy, timeouts, and provider routing. The architectural invariant is enforced by `tests/unit/agent/test_llm_bridge_singleton.py`.

See [`docs/architecture.md`](docs/architecture.md) for the full design and [`CLAUDE.md`](CLAUDE.md) for the coding standards every contributor (human or LLM) must follow.

### The model exploration loop

The first production workflow (`workflows/model_exploration.py`) implements an iterative closed-loop exploration:

```
   ┌───────────────────────── result_interpretation_agent
   │   (synthesizes records across models, surfaces bottlenecks)
   ▼
ml_model_proposal_agent
   │   (LLM proposes a new architecture + expert advice for the tuner)
   ▼
ml_model_implementor
   │   (writes PyTorch plugin file, test skeleton, description.md)
   ▼
ml_code_validator_agent
   │   (7 checks: load, pytest, description, config, instantiation,
   │    gradient flow, LLM code review)
   ▼
ml_hyperparameter_tune_agent
   │   (N rounds of plan → train → infer → score → reflect;
   │    planner and reflector use independent LLM models)
   └───────► back to result_interpretation_agent
```

Stop conditions: `max_iterations` count or `target_score` threshold. Validation failures trigger automatic retry with error feedback. Per-node LLM configuration via `WorkflowLLMConfig` (planner/reflector split for the tuner — see [`docs/break_tuner_agent.md`](docs/break_tuner_agent.md)).

### Guardrails on each iteration

Three reliability mechanisms sit on top of the raw 5-agent loop. They gate what the proposer is allowed to emit, cap what the tuner is allowed to spend, and thread earlier failures forward so successive iterations are monotonically better-informed.

- **Pre-flight resource gating.** Before training starts the proposer estimates per-trial VRAM and wall-time via static formulas (`agent/skills/evaluate_time_skill`, `agent/skills/evaluate_vram_skill`) and must justify itself against the trial/formal budgets (`--trial_time_budget_minutes`, `--trial_vram_budget_gb`, and their formal counterparts). An over-budget proposal gets up to 3 revision rounds before the iteration aborts cleanly. See [`docs/reliable_resource_proposer.md`](docs/reliable_resource_proposer.md) and [`docs/resource_estimator_implement.md`](docs/resource_estimator_implement.md).
- **Per-round attempt budget.** `--attempts_per_round N` caps retries inside one planner round; `--max_fail_rounds M` caps consecutive failed rounds before **Trigger A** (round budget exhausted) or **Trigger B** (streak of failed rounds) aborts the iteration. Prevents runaway cost from pathological planners.
- **Cumulative negative feedback.** Architectural patterns that gate-exhausted in earlier iterations are tagged (architectural-pattern tagger) and threaded forward via `disallowed_architectural_patterns` on `GateExhaustionInfo`; the proposer renders them as a `[DISALLOWED PATTERNS]` sub-block so iteration N+1 cannot re-propose the same failure mode. See [`docs/adaptive_new_model_proposer.md`](docs/adaptive_new_model_proposer.md).

### Key design invariants (must read before contributing)

1. **Pydantic at every boundary**: LLM output → schema → execution. Never pass raw LLM output to a training/inference call.
2. **No hidden inter-node communication**: schemas + protocols + per-node storage are the *only* channels. No reading peer files by convention, no shared state.
3. **`LLMBridge` is the single API gateway**: every agent goes through it. Direct `OpenAI()` constructors are CI-banned outside `agent/llm_bridge.py`.
4. **Plugins are pluggable**: agent-generated models extend `MODEL_REGISTRY` at runtime. Core code is read-only to agents.
5. **Trial vs. formal mode**: tuner rounds can run on a sparse multi-file subsample (`--is_trial`) for fast iteration, then graduate to the full 20-file evaluation. See [`docs/small_sample_trial.md`](docs/small_sample_trial.md).
6. **One scoring ruler (Option B, global `s_max`)**: model, raw-baseline, and ground-truth ceiling scores are all computed on the global `s_max` from `segment_anchors.json`, using float64-upcast FFTs and the TIDMAD `round(·, 2) + 1e-10` step before `log_{5.27}`. Any file-local or per-run normalization would make scores non-comparable across nodes. See [`docs/align_denoising_score.md`](docs/align_denoising_score.md) and the [Scoring convention](#scoring-convention) section below.

---

## Project structure

```
SIDERIUS/
├── agent/                            # LLM transport + per-node schemas + skill loader
│   ├── llm_bridge.py                 # ⭐ Universal API gateway. Retry policy, planner/reflector split.
│   ├── prompts.py                    # System prompts for planner/reflector/proposal/etc.
│   ├── tools_schema.py               # Skill loader
│   ├── schemas/                      # Pydantic schemas for every node
│   │   ├── storage.py                # StorageConfig
│   │   ├── hyperparam_tuning.py      # HyperparamTuningInput/Output, ExperimentPlan, TrialConfig
│   │   ├── interpretation.py         # InterpretationInput/Output
│   │   ├── proposal.py               # ProposalInput/Output
│   │   ├── implementor.py            # ImplementorInput/Output
│   │   ├── validator.py              # ValidatorInput/Output
│   │   ├── run_metadata.py           # TunerRunMetadata (audit trail)
│   │   └── protocols/                # Typed edge functions (NodeAOutput → NodeBInput)
│   └── skills/                       # Atomic research tools (training, inference, scoring, resource check)
│
├── nodes/                            # Runnable node implementations
│   ├── ml_hyperparameter_tune_agent.py
│   ├── result_interpretation_agent.py
│   ├── ml_model_proposal_agent.py
│   ├── ml_model_implementor.py
│   └── ml_code_validator_agent.py
│
├── workflows/                        # Pre-designed graph traversals (deterministic)
│   ├── model_exploration.py          # Iterative closed-loop exploration workflow
│   └── llm_config.py                 # WorkflowLLMConfig + TunerLLMConfig (planner/reflector split)
│
├── core/
│   └── sandbox_executor.py           # TidmadSandbox: config validation, subprocess dispatch
│
├── execute_tools/                    # Physical execution scripts (called as subprocesses)
│   ├── train_engine_sandbox.py       # Training loop (streaming + legacy modes)
│   ├── inference_single.py           # Inference over validation set
│   ├── scoring_utils.py              # Anchor-normalized scoring
│   ├── build_anchor_map.py           # One-time pre-computation of segment SNR anchors
│   ├── sample_set_builder.py         # SampleSet builder for trial/formal strategies
│   ├── dataset_config.py             # Physical constants (TIDMAD defaults)
│   └── data_paths.py                 # Reads tidmad_data_config.yaml
│
├── ml_models/                        # Built-in model definitions and Pydantic config schemas
│   ├── models_sandbox.py             # Network architectures + MODEL_REGISTRY
│   ├── models_format_sandbox.py      # *Config Pydantic schemas
│   ├── loss_models_sandbox.py        # Loss functions + get_criterion factory
│   ├── plugin_loader.py              # Loads agent_generated/models/ into MODEL_REGISTRY
│   ├── model_descriptions.py         # Loads ml_models/{model_type}/description.md
│   └── {punet,fcnet,wavenet,rnn,transformer,gated_fno}/description.md
│
├── agent_generated/                  # LLM-generated plugins (gitignored *.py)
│   ├── models/                       # Agent-written model plugins (+ description.md per plugin)
│   └── tests/                        # Agent-written model tests
│
├── dashboard/                        # FastAPI + uvicorn web dashboard
│   ├── main.py                       # Entry point
│   ├── api/                          # REST API routes and response models
│   ├── data_sources/                 # Local JSON and Postgres backends
│   └── static/                       # Frontend (vanilla JS + Plotly)
│
├── sdsc_submission_scripts/          # Slurm wrappers for SDSC Expanse + lilab chain runner
│   ├── submit_hpt_agent.slurm        # Single-tuner job
│   ├── run_iteration_chain.sh        # SDSC chain orchestrator (chains via afterany)
│   ├── run_iteration_chain_lilab.sh  # Lilab chain orchestrator (foreground subprocess)
│   ├── _chain_common.sh              # Shared bash framework
│   ├── run_one_iteration.py          # Per-iteration runner (called by both orchestrators)
│   └── submit_one_iteration.slurm    # Slurm wrapper for one chain iteration
│
├── advice/                           # Human-written JSON advice files
│   ├── single_agent/                 # One-key JSON, targets one agent (e.g. tuner-only static_v exploration)
│   └── workflow/                     # Multi-key JSON, full chain (e.g. human_advice_chain_test.json)
│
├── scripts/                          # Standalone runners (no longer at repo root)
│   ├── run_comparison.py             # Baseline-vs-agent comparison for a single model
│   ├── run_exploration.py            # 5-agent exploration workflow launcher
│   ├── compute_raw_baseline.py       # Raw (undenoised) reference score per file (Option B, global s_max)
│   ├── compute_ground_truth.py       # Perfect-denoiser ceiling per file + scalar (anchor-only, no HDF5 read)
│   ├── run_all_models{,_trial}.sh    # Lilab multi-model launchers (parallel/sequential)
│   └── inspect_run_state.py          # Resume / inspect chain-iter state
│
├── tidmad_data_config.yaml           # Machine-specific data paths (edit when migrating)
├── dashboard_config.yaml             # Dashboard config (root path, models, port)
├── pyproject.toml + uv.lock          # Dependencies (managed by uv)
│
├── CLAUDE.md                         # ⭐ Coding standards and architectural rules
├── README.md                         # This file
│
├── reference_data/                   # In-repo reference artefacts (scoring baselines, signal tables)
│   ├── raw_and_ground_score.md       # Per-file raw baseline + ceiling table (Option B, global s_max)
│   └── tidmad_signal_frequencies.txt # 309 injected signal frequencies
│
├── docs/                             # Design docs — see "Documentation index" below for the full list
│   ├── architecture.md               # Full system design
│   ├── align_denoising_score.md      # Scoring-ruler derivation + legacy-parity proof (Option B)
│   ├── reliable_resource_proposer.md # Pre-flight cost-check + up-to-3 revision loop
│   ├── adaptive_new_model_proposer.md # Cumulative negative-feedback design
│   ├── pseudo_test_infra.md          # Dual-mode pseudo/real test infrastructure
│   ├── running_chain_test.md         # ⭐ Operational runbook for chain runs (lilab + SDSC)
│   ├── break_tuner_agent.md          # Planner/reflector LLM split
│   ├── small_sample_trial.md         # Multi-fidelity trial/formal tuning
│   ├── ... (more below)
│   └── memories/                     # Per-developer shared memories (gitignored, see README inside)
│
├── tests/
│   ├── unit/                         # Mocked LLM, no GPU, runs in CI
│   │   ├── agent/                    # Per-node schema and tool tests
│   │   ├── core/                     # Sandbox executor and plugin loader tests
│   │   ├── workflows/                # WorkflowLLMConfig tests
│   │   ├── dashboard/                # Dashboard route tests
│   │   └── ml_models/                # Model and loss function tests
│   └── integration/
│       ├── nodes/                    # Tier 1 — single node, real API
│       ├── protocols/                # Tier 2 — one graph edge, real API
│       ├── workflows/                # Tier 3 — multi-hop workflow, real API + GPU
│       ├── dashboard/                # Dashboard API integration tests
│       └── execute_tools/            # Training loop integration tests
│
└── env_validation/
    └── test_agent_env.py             # Validate Gemini / OpenAI API keys
```

---

## Quick start

### Prerequisites

- Python 3.12+
- NVIDIA GPU with CUDA (training and inference require GPU)
- ~50 GB disk for TIDMAD raw data, ~100 GB for run outputs
- [uv](https://docs.astral.sh/uv/) package manager
- Gemini and/or OpenAI API key

### 1. Install

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

git clone git@github.com:Galileo-Sandbox/SIDERIUS.git
cd SIDERIUS
uv sync                     # installs all dependencies from uv.lock
source .venv/bin/activate
```

### 2. Configure data paths — `tidmad_data_config.yaml`

The repo only tracks `tidmad_data_config.example.yaml`. On first checkout, copy it and fill in the paths for your machine:

```bash
cp tidmad_data_config.example.yaml tidmad_data_config.yaml
# then edit:
#   tidmad_data_dir:   /your/path/to/TIDMAD/         (raw HDF5 files)
#   siderius_data_dir: /your/path/to/SIDEREIS_DATA/  (run outputs)
```

The real `tidmad_data_config.yaml` is gitignored, so `git pull` will never clobber your machine-specific paths.

### 3. Configure API keys — `.env`

```
GEMINI_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key    # optional
```

Validate connectivity:

```bash
python env_validation/test_agent_env.py
```

### 4. Pre-compute the anchor map (one-time, ~30 min)

Required for trial/formal scoring. Reads from `tidmad_data_dir`, writes `segment_anchors.json` into the same directory.

```bash
python execute_tools/build_anchor_map.py --parallel -n 8
```

### 5. Run unit tests as a smoke check

```bash
uv run pytest tests/unit/ -q
```

If all 700+ tests pass, the install is good.

---

## Usage recipes

### A. Single-tuner run (most common)

Tunes hyperparameters of one model over N rounds. Each round = plan → train → infer → score → reflect.

```bash
# Minimal — Gemini, 1 round, agent picks model
python nodes/ml_hyperparameter_tune_agent.py --max_rounds 1 --run_name first_run

# Trial mode — sparse multi-file sampling, ideal for quick iteration
python nodes/ml_hyperparameter_tune_agent.py \
    --is_trial \
    --force_model punet \
    --max_rounds 20 \
    --run_name punet_trial_v1

# With per-experiment advice (recommended for serious runs)
python nodes/ml_hyperparameter_tune_agent.py \
    --force_model gated_fno \
    --is_trial \
    --max_rounds 20 \
    --human_advice_file advice/single_agent/gated_fno_freq_band_aware_v1.json \
    --run_name gated_fno_freq_band_aware_v1

# Planner/reflector model split (gemini quota optimization)
python scripts/run_comparison.py \
    --model punet \
    --run_name punet_split_v1 \
    --provider gemini \
    --model_id gemini-3.1-pro-preview \
    --reflect_model_id gemini-2.5-flash \
    --max_rounds 10
```

The `--reflect_model_id` flag routes the tuner's reflection sub-call to a cheaper model with unlimited daily quota, cutting `gemini-3.1-pro-preview` usage by ~50% per round. See [`docs/break_tuner_agent.md`](docs/break_tuner_agent.md) for the full design.

#### Tuner CLI reference

Grouped by role — the tuner has a lot of knobs, so the full list is split into five sections.

**Core run identity + LLM routing**

| Argument | Default | Description |
|---|---|---|
| `--provider` | `gemini` | LLM backend (`gemini` or `openai`) |
| `--model_id` | `gemini-3.1-flash-lite-preview` | Planner LLM model ID |
| `--reflect_provider` | (planner provider) | Optional cross-provider reflector routing |
| `--reflect_model_id` | (planner model) | Optional reflector model ID — defaults to `gemini-2.5-flash` for the gemini provider |
| `--max_rounds` | `10` | Maximum completed experiment rounds |
| `--force_model` | `auto` | Lock the architecture or let the agent choose |
| `--seed_plugin_path` | None | Pre-existing plugin `.py` to resume from (used by the exploration chain) |
| `--run_name` | `test_run` | Run identifier — scopes all saved files |
| `--workspace` | from yaml | Root directory for all agent outputs |
| `--progress_bar` | off | Stream live tqdm progress bars from training/inference |

**Trial / formal sampling**

| Argument | Default | Description |
|---|---|---|
| `--is_trial` | off | Enable trial-explore mode (multi-file sparse sampling) |
| `--trial_strategy` | `snapshot` | Trial training sampling: `snapshot`, `anchors`, or `target` |
| `--trial_portion` | `0.1` | Fraction of segments per file for trial training scope |
| `--eval_strategy` | `snapshot` | Trial validation sampling strategy |
| `--eval_portion` | `0.1` | Fraction of segments per file for trial validation |
| `--train_portion` | `0.1` | Per-epoch subsample from the trial training scope |
| `--formal_strategy` | `snapshot` | Formal-mode training sampling (graduates from trial) |
| `--formal_portion` | `1.0` | Formal-mode segment fraction per file |
| `--formal_train_portion` | `1.0` | Formal-mode per-epoch subsample |

**Resource budgets (pre-flight gate)**

| Argument | Default | Description |
|---|---|---|
| `--trial_time_budget_minutes` | see `--help` | Wall-time budget for one trial attempt |
| `--formal_time_budget_minutes` | see `--help` | Wall-time budget for one formal attempt |
| `--trial_vram_budget_gb` | see `--help` | VRAM budget for trial attempts |
| `--formal_vram_budget_gb` | see `--help` | VRAM budget for formal attempts |
| `--data_dir` | from yaml | TIDMAD directory used by the time-budget estimator |

**Per-round attempt budget**

| Argument | Default | Description |
|---|---|---|
| `--attempts_per_round` | see `--help` | Max retries inside one planner round before a round-fail |
| `--attempts_per_formal_round` | see `--help` | Same, for formal-mode rounds |
| `--max_fail_rounds` | see `--help` | Max consecutive failed rounds before Trigger A/B aborts |

**Advice and cleanup**

| Argument | Default | Description |
|---|---|---|
| `--human_advice` | None | Inline string OR path to a JSON file with per-agent advice |
| `--expert_advice` | None | Inline advice string for the planner (single-agent override) |
| `--cleanup_denoised` | off | Delete intermediate `.h5` files after scoring |

#### Per-tuner output layout

```
{workspace}/{model}/{run_name}/agent/
├── tuner_run_metadata.json           # audit trail (git, env, llm config, advice)
├── summary_{run_name}_agent.json     # all experiment records (research memory)
├── run_output_{run_name}_agent.json  # validated HyperparamTuningOutput
├── run_config_{run_name}_agent.json  # startup config snapshot
├── configs/{run_name}_agent/
│   ├── trial_config_{exp_id}.json    # trial/formal params + seeds (Pydantic-validated)
│   ├── train_sample_set_{exp_id}.json
│   ├── eval_sample_set_{exp_id}.json
│   ├── model_config_{exp_id}.json
│   ├── train_config_{exp_id}.json
│   └── loss_config_{exp_id}.json
├── records/{run_name}_agent/          # per-experiment training results
└── cached_models/                     # trained model checkpoints (.pth)
```

### B. Multi-iteration exploration chain

Each iteration runs the **full 5-agent loop** (interpret → propose → implement → validate → tune) and produces a new model. Iteration N+1 reads iteration N's output via a manifest file.

#### On lilab (foreground, no slurm)

```bash
bash sdsc_submission_scripts/run_iteration_chain_lilab.sh \
    --workspace /home/klz/Data/SIDEREIS_DATA/exploration_chain_v1 \
    --num_iterations 5 \
    --seed_paths /home/klz/Data/SIDEREIS_DATA/punet/hpt_full_v1/agent/run_output_hpt_full_v1_agent.json \
                 /home/klz/Data/SIDEREIS_DATA/wavenet/hpt_full_v1/agent/run_output_hpt_full_v1_agent.json \
    --max_rounds 5 \
    --max_epochs 5 \
    --human_advice_file advice/workflow/human_advice_chain_test.json \
    --reflect_model_id gemini-2.5-flash
```

#### On SDSC (slurm, chained via `afterany`)

```bash
bash sdsc_submission_scripts/run_iteration_chain.sh \
    --workspace /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_v1 \
    --num_iterations 10 \
    --seed_paths /expanse/.../run_output_hpt_full_v2_agent.json \
    --max_rounds 5 \
    --max_epochs 5 \
    --human_advice_file advice/workflow/human_advice_chain_test.json \
    --reflect_model_id gemini-2.5-flash \
    --partition gpu-shared \
    --time 04:00:00 \
    --mem 48G
```

**Key operational notes** (more in [`docs/running_chain_test.md`](docs/running_chain_test.md)):

- Use a fresh `_v{N}` workspace per submission. Reusing names confuses manifest resolution.
- The chain uses `--dependency=afterany` and `--mem 48G` by default on SDSC. Don't lower memory.
- An iteration that produces `score=None` writes `manifest.status=failed`; downstream iterations refuse to chain off it.
- The 5 agents all route through `LLMBridge`, which retries 5x with 2.5s/5s/10s/20s/40s backoff on transient API failures.

### C. Dashboard

Browse experiment results in a web UI. Supports both **standard tuner runs** and **chain exploration runs** in two layouts.

```bash
# 1. On first checkout, copy the template and edit:
cp dashboard_config.example.yaml dashboard_config.yaml
# then edit root_data_dir for your machine
# (lilab: /home/klz/Data/SIDEREIS_DATA, SDSC: /expanse/.../siderius_workspace)
# The real dashboard_config.yaml is gitignored.

# 2. Start the server
python dashboard/main.py
# or, in development with auto-reload:
uvicorn dashboard.main:app --reload
```

Open `http://localhost:8000`. Key config:

```yaml
data_source:
  type: local                # "local" or "postgres"
  local:
    root_data_dir: /path/to/SIDEREIS_DATA
    models: []               # [] = auto-discover; or list explicitly
server:
  port: 8000
```

To browse SDSC runs from your laptop, set up an SSH tunnel: `ssh -L 8000:localhost:8000 sdsc_expanse`.

---

## Built-in models, losses, and plugins

### Models

All models take SQUID time-series data (ADC values 0–255) and produce `[B, 256, T]` per-timestep class distributions.

| Key | Class | Description |
|---|---|---|
| `punet` | `PositionalUNet` | 1D convolutional U-Net with sinusoidal positional encoding |
| `fcnet` | `AE` | Fully connected autoencoder with configurable hidden dimensions |
| `transformer` | `TransformerModel` | Transformer encoder. Keep `segmentation_size ≤ 20000` |
| `wavenet` | `SimpleWaveNet` | WaveNet-style dilated causal convolutions |
| `rnn` | `RNNSeq2Seq` | LSTM encoder-decoder with teacher forcing |
| `gated_fno` | `GatedFNO` | Full-spectrum gated Fourier Neural Operator with manual frequency-band gating (`static_v`) |

### Loss functions

| Key | Class | Notes |
|---|---|---|
| `focal` | `FocalLoss1D` | Tunable `alpha` and `gamma` |
| `focal_cw` | `FocalLoss1DCW` | Class-weighted focal loss |
| `ce` | `nn.CrossEntropyLoss` | Baseline classification loss |
| `smooth_l1` | `nn.SmoothL1Loss` | Regression mode — `fcnet` only |

### Agent-generated plugins

The exploration loop writes new models to `agent_generated/models/`. Each plugin must define:

- `PLUGIN_MODEL_TYPE: str` — unique model type key
- `PLUGIN_CONFIG_CLASS: BaseModel` — Pydantic config schema
- `PLUGIN_MODEL_CLASS: nn.Module` — model with forward contract `[B, T] int64 → [B, 256, T] float32`
- `description.md` — plain-English + math description (required by the interpretation agent)

`ml_models/plugin_loader.py` scans `agent_generated/models/` at import time and extends `MODEL_REGISTRY` and `PLUGIN_CONFIG_REGISTRY` in-place. **Core code is never modified by agents.**

Plugins are **run-scoped**: each tuner run stages its validated plugin into `{workspace}/plugins/{run_name}/` and sets `SIDERIUS_PLUGIN_DIRS` so training subprocesses see only that run's plugin. The exploration chain can seed a new iteration from an earlier run's plugin with `--seed_plugin_path`. See [`docs/run_scoped_plugins.md`](docs/run_scoped_plugins.md).

---

## Scoring convention

Every score in SIDERIUS — model output, raw-signal baseline, and perfect-denoiser ceiling — is computed on **one ruler** so they are directly comparable at every file index and in the scalar aggregate. The ruler is **Option B, global `s_max`**:

```
per_segment[f, i]  = (snr_sg[f, i] / s_max_GLOBAL) · snr_squid[f, i]
per_file_linear[f] = mean_i(per_segment[f, i])                       # over sampled segments
per_file_score[f]  = log_{5.27}(round(per_file_linear[f], 2) + 1e-10)

grand_mean         = ( Σ_{f,i} per_segment[f, i] )  /  Σ_f |S_f|     # trial-mode: non-uniform |S_f|
scalar_score       = log_{5.27}(round(grand_mean, 2) + 1e-10)
```

- **Option B** means `TS.astype(np.float64)` before `np.fft.rfft` — the FFT runs in complex128, not complex64. This is what keeps the legacy-parity gate at bit-for-bit identity with the TIDMAD reference implementation.
- **Global `s_max`** is a single constant loaded from `segment_anchors.json` (`s_max = 295_715_680.1425` at the current anchor map). **Never** compute `amax(snr_sg)` over a file list at score time — that creates a per-run ruler and makes scores non-comparable across nodes.
- **TIDMAD round** (`round(·, 2) + 1e-10` before the log) is part of the ruler, not an optional cosmetic step.
- **Grand mean, not mean-of-per-file-log-scores.** Under trial-mode non-uniform sampling (`|S_f|` differs per file) the two disagree; only the grand mean is legacy-compatible. See feedback memory `feedback_no_mean_of_perfile_scores.md`.

### Reference artefacts

| Artefact | What | Source |
|---|---|---|
| `reference_data/raw_and_ground_score.md` | Per-file raw baseline + perfect-denoiser ceiling table (20 files, current anchor map) | version-controlled |
| `{SIDERIUS_DATA_DIR}/raw_baseline/raw_baseline_score_file_XXXX.json` | Per-file raw-signal baseline JSON | generated |
| `{SIDERIUS_DATA_DIR}/ground_truth/ground_truth_score_file_XXXX.json` | Per-file perfect-denoiser ceiling JSON | generated |
| `{SIDERIUS_DATA_DIR}/ground_truth/ceiling_anchor_normalized.json` | Scalar ceiling (current value: **10.1134**) | generated |

### Regeneration

After the anchor map is built (see Quick start §4), regenerate both reference tables:

```bash
python scripts/compute_raw_baseline.py   # reads raw CH1, writes raw_baseline/raw_baseline_score_file_XXXX.json
python scripts/compute_ground_truth.py   # anchor-only (no HDF5 read), writes ceiling JSONs in milliseconds
```

Both scripts use the global `s_max` from the anchor map automatically and refuse to overwrite existing JSONs unless `--override` is passed.

Full derivation, legacy-parity proof, and rationale for Option B are in [`docs/align_denoising_score.md`](docs/align_denoising_score.md).

---

## Configuration files

| File | What it controls | Tracked? |
|---|---|---|
| `tidmad_data_config.example.yaml` | Template for the data-paths config | yes |
| `tidmad_data_config.yaml` | Local copy with the actual machine-specific paths | **no (gitignored)** |
| `dashboard_config.example.yaml` | Template for the dashboard config | yes |
| `dashboard_config.yaml` | Local copy with the actual root path / port | **no (gitignored)** |
| `.env` | API keys (`GEMINI_API_KEY`, `OPENAI_API_KEY`) | no (gitignored) |
| `advice/single_agent/*.json` | Per-experiment human advice for a single agent | yes |
| `advice/workflow/*.json` | Per-agent human advice for full-chain runs | yes |
| `pyproject.toml` + `uv.lock` | Python dependencies (managed by `uv`) | yes |

The two `*.yaml` files containing machine-specific paths are gitignored: each developer copies them once from the `*.example.yaml` template on first checkout, and `git pull` thereafter never touches them. This is what prevents lilab paths from clobbering SDSC paths and vice versa.

---

## Testing

The test pyramid has five tiers, distinguished by *how many nodes* a test exercises and *whether it hits real LLM APIs / real training*:

| Category | Scope | LLM | GPU | Location | When to run |
|---|---|---|---|---|---|
| Unit | Single function/class, mocked LLM | mock | no | `tests/unit/` | Every commit |
| Integration Tier 0 (pseudo-full-loop) | Full node orchestration via predefined LLM + subprocess responses (`@dual_mode`) | pseudo | no | `tests/integration/` | Every commit — runs in ms |
| Integration Tier 1 | Single node end-to-end, real API | real | depends | `tests/integration/nodes/` | On demand |
| Integration Tier 2 | One graph edge (source → target), real API | real | depends | `tests/integration/protocols/` | On demand |
| Integration Tier 3 | Multi-hop workflow, real API + GPU | real | yes | `tests/integration/workflows/` | Before releases |

```bash
# Unit tests (always pass, no API key needed)
uv run pytest tests/unit/ -q

# Tier 0 — pseudo-full-loop dual-mode tests (milliseconds, no API key, no GPU)
uv run pytest tests/integration/ -q

# Tier 0 same tests, real API + real training (opt in via --real-api-call / --real-training)
uv run pytest tests/integration/ --real-api-call --real-training -v

# Tier 1 — individual node with real LLM
uv run pytest tests/integration/nodes/ -m real_run -v

# Tier 2 — one protocol edge end-to-end
uv run pytest tests/integration/protocols/ -m real_run -v

# Tier 3 — full chain (~2.5h, validates planner/reflector split, real API + GPU)
uv run pytest tests/integration/workflows/test_full_exploration_loop.py::TestFullExplorationLoop::test_chained_iterations -m real_run -v
```

`real_run`-marked tests skip automatically when the required API key is absent. They never run in CI.

### Dual-mode (pseudo/real) tests

The `@pytest.mark.dual_mode` decorator lets one test file cover both pseudo-full-loop (Tier 0) and real-LLM behaviour without duplication. By default a dual-mode test runs in **pseudo mode** — `RecordingLLMBridge` replays canned responses from `tests/pseudo_data/` and `RecordingSandbox` replays canned subprocess outputs — so the whole 5-agent loop finishes in milliseconds on CI without any API key or GPU. Flipping `--real-api-call` (real LLM, surrogated training) or `--real-training` (real GPU, surrogated LLM) or both (`-m real_run`) promotes the same test to Tier 1/2/3. New integration tests should be dual-mode by default — see [`docs/pseudo_test_infra.md`](docs/pseudo_test_infra.md) for the full design.

### Architectural invariant tests

- **`tests/unit/agent/test_llm_bridge_singleton.py`** — fails if any file outside `agent/llm_bridge.py` constructs an `OpenAI()` client. Ensures every LLM call goes through the unified retry policy.

---

## Server migration

When deploying SIDERIUS on a new machine:

1. **Clone and install**:
   ```bash
   git clone git@github.com:Galileo-Sandbox/SIDERIUS.git
   cd SIDERIUS
   uv sync
   ```

2. **Copy TIDMAD data** — `abra_training_0000.h5`..`0019.h5` and `abra_validation_0000.h5`..`0019.h5`.

3. **Create local config files from the templates**:
   ```bash
   cp tidmad_data_config.example.yaml tidmad_data_config.yaml
   cp dashboard_config.example.yaml   dashboard_config.yaml
   # then edit both for your machine's paths
   ```
   Both real files are gitignored, so future `git pull`s won't clobber them.

4. **Set API keys** in `.env`.

5. **Pre-compute anchor map** (one-time, ~30 min):
   ```bash
   python execute_tools/build_anchor_map.py --parallel -n 8
   ```

6. **Verify**:
   ```bash
   python env_validation/test_agent_env.py
   uv run pytest tests/unit/ -q
   uv run pytest tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini[loss_cfg0] -v -s -m real_run
   ```

### What does NOT need changing
- Python source code — reads paths from config
- Shell scripts — read from YAML
- Tests — fall back gracefully if config is missing

### Lilab vs SDSC quick reference

| | lilab | SDSC Expanse |
|---|---|---|
| GPU | RTX 5090 (32 GB) | V100 / A100 (`gpu-shared`) |
| Workspace | `/home/klz/Data/SIDEREIS_DATA/` | `/expanse/lustre/projects/ddp433/ym137/siderius_workspace/` |
| Chain runner | `run_iteration_chain_lilab.sh` (foreground) | `run_iteration_chain.sh` (slurm `afterany`) |
| Single tuner | `python nodes/ml_hyperparameter_tune_agent.py ...` | `sbatch sdsc_submission_scripts/submit_hpt_agent.slurm ...` |

More in [`docs/memories/reference_sdsc_workspace_paths.md`](docs/memories/reference_sdsc_workspace_paths.md) (gitignored — read locally).

---

## Documentation index

### Design and architecture
- [`docs/architecture.md`](docs/architecture.md) — full system design (graph, nodes, protocols, skills)
- [`CLAUDE.md`](CLAUDE.md) — coding standards and architectural rules every contributor must follow
- [`docs/full_loop_5_agents.md`](docs/full_loop_5_agents.md) — 5-agent workflow design
- [`docs/first_model_proposal_demo_architecture.md`](docs/first_model_proposal_demo_architecture.md) — first demo plan
- [`docs/soft_edge_for_all_nodes.md`](docs/soft_edge_for_all_nodes.md) — protocol design notes
- [`docs/learning_from_sota_agents.md`](docs/learning_from_sota_agents.md) — survey of related work

### Tuner and LLM infrastructure
- [`docs/break_tuner_agent.md`](docs/break_tuner_agent.md) — planner/reflector LLM split (implemented)
- [`docs/refactor_llm_bridge.md`](docs/refactor_llm_bridge.md) — LLMBridge refactor history
- [`docs/hyperparameter_tuner_features.md`](docs/hyperparameter_tuner_features.md) — tuner prompt features
- [`docs/small_sample_trial.md`](docs/small_sample_trial.md) — multi-fidelity trial/formal mode
- [`docs/small_sample_trial_dependencies_improve.md`](docs/small_sample_trial_dependencies_improve.md) — schema cleanup notes
- [`docs/trial_epoch_default.md`](docs/trial_epoch_default.md) — trial-mode epoch default and override path

### Scoring and denoising metric
- [`docs/align_denoising_score.md`](docs/align_denoising_score.md) — **canonical**: scoring-ruler derivation, Option B global `s_max`, legacy-parity proof
- [`reference_data/raw_and_ground_score.md`](reference_data/raw_and_ground_score.md) — per-file raw baseline + perfect-denoiser ceiling table (20 files, current anchor map)
- [`docs/optimize_inference_and_scoring.md`](docs/optimize_inference_and_scoring.md) — host-RAM post-mortem + 5-commit memory optimization (PR 57)

### Proposer reliability and resource gating
- [`docs/reliable_resource_proposer.md`](docs/reliable_resource_proposer.md) — pre-flight cost-check + architectural blacklist + up-to-3 revision loop (PR 56)
- [`docs/resource_estimator_implement.md`](docs/resource_estimator_implement.md) — Phases K + L: VRAM budget gate, per-round attempt budget, Trigger A/B fail-round abort (PRs 54, 55)
- [`docs/adaptive_new_model_proposer.md`](docs/adaptive_new_model_proposer.md) — cumulative negative-feedback design (`disallowed_architectural_patterns`)
- [`docs/adaptive_new_model_proposer_overall_review.md`](docs/adaptive_new_model_proposer_overall_review.md) — full-arc review
- [`docs/adaptive_new_model_proposer_phase_C_review.md`](docs/adaptive_new_model_proposer_phase_C_review.md) — Phase C vocab-feedback review
- [`docs/improving_validation_awareness.md`](docs/improving_validation_awareness.md) — dataset-divisor + schema-violation feedback across proposer/implementor/tuner (PRs 52, 53)

### Test infrastructure
- [`docs/pseudo_test_infra.md`](docs/pseudo_test_infra.md) — dual-mode pseudo/real tests, `RecordingLLMBridge`, `RecordingSandbox`, surrogation axes

### Plugins and external agents
- [`docs/run_scoped_plugins.md`](docs/run_scoped_plugins.md) — per-run plugin isolation via `SIDERIUS_PLUGIN_DIRS`; `--seed_plugin_path` for chain runs (PR 53)
- [`docs/external_agents_for_proposer.md`](docs/external_agents_for_proposer.md) — Phase F receptive-side infra for external agents

### Operations
- [`docs/running_chain_test.md`](docs/running_chain_test.md) — runbook for chain runs on lilab and SDSC

### Reference data
- [`reference_data/raw_and_ground_score.md`](reference_data/raw_and_ground_score.md) — per-file raw baseline + ceiling table
- [`reference_data/tidmad_signal_frequencies.txt`](reference_data/tidmad_signal_frequencies.txt) — 309 injected signal frequencies (kHz–MHz), distributed across 20 files

### Per-developer memories (gitignored)
- `docs/memories/` — local-only shared notes. See `docs/memories/README.md` for the format. Currently captures:
  - Gemini quota and the planner/reflector split rationale
  - SDSC chain `afterany` + 48 GB memory rule
  - SDSC workspace paths reference
  - Design-doc-first workflow preference
  - Known TODO: GPU-name lie in `scripts/run_comparison.py`

---

## License and citation

(To be added.)
