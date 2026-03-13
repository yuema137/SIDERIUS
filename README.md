# SIDERIUS

### **S**cientific **I**nquiry, **D**esign, **E**xploration, and **R**easoning **I**ntegrated **U**sing multi-agent **S**ystems

**SIDERIUS** is an autonomous research platform designed to automate the full-loop scientific discovery process — from hypothesis formulation to experimental validation. Inspired by Galileo Galilei's *Sidereus Nuncius*, the project uses a multi-agent architecture to act as a "digital telescope," extracting fundamental physical laws from complex data.

---

> *"All truths are easy to understand once they are discovered; the point is to discover them."*
> <p align="left"><b>—Galileo Galilei</b></p>

---

## Architecture

SIDERIUS is built on a single unifying idea: **the whole system is a typed, directed graph**.

- Every component is a **node** — it has a validated input schema (`BaseModel`) and a validated output schema, and exposes a `run(input) -> output` method.
- **Edges** are directed data dependencies between nodes. Two nodes can only be connected if an explicit, typed **protocol** function exists on that edge.
- **Orchestrators** are nodes too — they select paths through the graph, apply protocols, and call `node.run()`. Cycles in the graph become loops when an orchestrator traverses them repeatedly.

See [`docs/architecture.md`](docs/architecture.md) for the full design and [`docs/first_model_proposal_demo_architecture.md`](docs/first_model_proposal_demo_architecture.md) for the first end-to-end demo plan.

### Current node graph

```
tune_ml_hyperparam_agent
        │  ml_model_tune_to_ml_result_interp :: local_all_records
        ▼
result_interpretation_agent
        │  ml_result_interp_to_ml_model_propose :: local_full_context
        ▼
ml_model_proposal_agent
        │  ml_model_propose_to_ml_model_impl :: local_full_spec
        ▼
ml_model_implementor
        │  ml_model_impl_to_ml_model_valid :: local_all_fields
        ▼
ml_code_validator_agent
        │  ml_model_valid_to_ml_model_tune :: local_validated_model
        ▼
tune_ml_hyperparam_agent  (new model, loop)
```

---

## Project Structure

```
siderius/
├── agent/
│   ├── llm_bridge.py               # LLM transport — generate() (JSON), generate_text() (plain), plan(), reflect()
│   ├── prompts.py                  # System prompts for planner and reflector
│   ├── tools_schema.py             # Skill loader
│   ├── schemas/                    # Pydantic input/output schemas for every node
│   │   ├── storage.py              # StorageConfig — shared per-node storage config
│   │   ├── hyperparam_tuning.py    # HyperparamTuningInput / Output / ExpertAdvice
│   │   ├── interpretation.py       # InterpretationInput / Output / SummaryGroup
│   │   ├── proposal.py             # ProposalInput / Output
│   │   ├── implementor.py          # ImplementorInput / Output
│   │   ├── validator.py            # ValidatorInput / Output
│   │   └── protocols/              # Typed edge functions (NodeAOutput → NodeBInput)
│   └── skills/                     # Atomic research skills (training, inference, scoring)
│
├── core/
│   └── sandbox_executor.py         # TidmadSandbox: config validation, subprocess dispatch
│
├── ml_models/                      # Built-in model definitions and Pydantic config schemas
│   ├── models_sandbox.py           # Network architectures + MODEL_REGISTRY
│   ├── models_format_sandbox.py    # PUNetConfig, AEConfig, TransformerConfig, etc.
│   ├── loss_models_sandbox.py      # Loss functions + get_criterion factory
│   ├── model_descriptions.py       # Loader: ml_models/{model_type}/description.md
│   ├── plugin_loader.py            # Loads agent_generated/models/ into MODEL_REGISTRY
│   ├── punet/description.md
│   ├── fcnet/description.md
│   ├── transformer/description.md
│   ├── wavenet/description.md
│   └── rnn/description.md
│
├── execute_tools/                  # Physical execution scripts (called as subprocesses)
│   ├── train_engine_sandbox.py     # Training loop
│   ├── inference_single.py         # Inference over validation set
│   ├── denoising_score_single.py   # Denoising score computation
│   └── array2h5.py                 # Array-to-HDF5 conversion utility
│
├── nodes/                          # Runnable node implementations (typed directed graph)
│   ├── ml_hyperparameter_tune_agent.py
│   ├── result_interpretation_agent.py
│   ├── ml_model_proposal_agent.py
│   ├── ml_model_implementor.py
│   └── ml_code_validator_agent.py
│
├── dashboard/                      # Web dashboard for browsing experiment results
│   ├── main.py                     # FastAPI + uvicorn server
│   ├── settings.py                 # Dashboard configuration
│   ├── api/                        # REST API routes and response models
│   ├── data_sources/               # Local JSON and Postgres data source backends
│   └── static/                     # Frontend (index.html, app.js, style.css)
│
├── agent_generated/                # LLM-generated plugins (gitignored *.py)
│   ├── models/                     # Agent-written model plugins (+ description.md per plugin)
│   └── tests/                      # Agent-written model tests
│
├── docs/
│   ├── architecture.md             # Full system design
│   └── first_model_proposal_demo_architecture.md
│
├── tests/
│   ├── unit/
│   │   ├── agent/                  # Per-node schema and skill tests
│   │   ├── core/                   # Sandbox executor and plugin loader tests
│   │   └── ml_models/              # Model and loss function tests
│   └── integration/
│       ├── nodes/                  # Tier 1 — single node, real API (no other nodes)
│       ├── protocols/              # Tier 2 — one graph edge, source → target, real API
│       ├── orchestrator/           # Tier 3 — multi-hop critical loops, real API + GPU
│       ├── dashboard/              # Dashboard API integration tests
│       └── execute_tools/          # Training loop integration tests
│
└── env_validation/
    └── test_agent_env.py           # Validate Gemini / OpenAI API keys
```

---

## Plugin System

Agent-generated models are dropped into `agent_generated/models/` as `.py` files. Each plugin must define:

- `PLUGIN_MODEL_TYPE: str` — unique model type key
- `PLUGIN_CONFIG_CLASS: BaseModel` — Pydantic config schema
- `PLUGIN_MODEL_CLASS: nn.Module` — model with forward contract `[B, T] int64 → [B, 256, T] float32`
- `description.md` — plain-English + math description alongside the plugin file; required by the interpretation agent

`ml_models/plugin_loader.py` scans `agent_generated/models/` at import time and extends `MODEL_REGISTRY` and `PLUGIN_CONFIG_REGISTRY` in-place. The core codebase is never modified by agents.

---

## Nodes

| Node | Role | GPU | LLM | Status |
|---|---|---|---|---|
| `tune_ml_hyperparam_agent` | Trains, infers, and scores a model; optimises hyperparameters over N rounds | yes | yes | ✅ implemented |
| `result_interpretation_agent` | Synthesises experiment records across models; surfaces bottlenecks and patterns | no | yes | ✅ implemented |
| `ml_model_proposal_agent` | Reads interpretation → proposes a new architecture + expert advice for the tuner | no | yes | ✅ implemented |
| `ml_model_implementor` | Takes a proposal → writes PyTorch plugin file, test skeleton, and description.md; self-correction loop validates code (config consistency, syntax, smoke test) and retries on failure | no | yes | ✅ implemented |
| `ml_code_validator_agent` | 7 checks: plugin load, pytest, description, config fields, instantiation, gradient flow, LLM code review with runtime diagnosis | no | yes | ✅ implemented |
| `data_analysis_agent` | Profiles dataset properties; detects distribution shifts | no | yes | ⬜ planned |

---

## Built-in Models

All models take SQUID time-series data (ADC values 0–255) and produce a per-timestep class distribution.

| Key | Class | Description |
|---|---|---|
| `punet` | `PositionalUNet` | 1D convolutional U-Net with sinusoidal positional encoding. |
| `fcnet` | `AE` | Fully connected AutoEncoder with configurable hidden dimensions. |
| `transformer` | `TransformerModel` | Transformer encoder projecting to 256 ADC classes. Keep `segmentation_size ≤ 20000` to avoid OOM. |
| `wavenet` | `SimpleWaveNet` | WaveNet-style dilated causal convolutions. |
| `rnn` | `RNNSeq2Seq` | LSTM encoder-decoder with teacher forcing. |

## Built-in Loss Functions

| Key | Class | Notes |
|---|---|---|
| `focal` | `FocalLoss1D` | Tunable `alpha` and `gamma` |
| `focal_cw` | `FocalLoss1DCW` | Class-weighted focal loss |
| `ce` | `nn.CrossEntropyLoss` | Baseline classification loss |
| `smooth_l1` | `nn.SmoothL1Loss` | Regression mode — `fcnet` only |

---

## Quick Start

### 1. Environment setup

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

uv python install 3.12
cd /path/to/siderius
uv venv --python 3.12
source .venv/bin/activate

uv add torch numpy scipy h5py tqdm "jax[cpu]" iminuit matplotlib pandas \
    requests scitokens openai google-generativeai pydantic python-dotenv
```

### 2. Configure API keys

```
GEMINI_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key
```

Validate connectivity:

```bash
python env_validation/test_agent_env.py
```

### 3. Run the hyperparameter tuning agent

```bash
# Minimal run — agent picks the model, 1 round
python nodes/ml_hyperparameter_tune_agent.py --max_rounds 1 --run_name first_run

# Force a specific model with expert guidance
python nodes/ml_hyperparameter_tune_agent.py \
    --force_model transformer \
    --expert_advice "Set segmentation_size=10000 to avoid OOM. Use nhead=4." \
    --max_rounds 5 \
    --run_name transformer_v1

# Use OpenAI instead of Gemini
python nodes/ml_hyperparameter_tune_agent.py \
    --provider openai \
    --model_id gpt-4o \
    --max_rounds 5 \
    --run_name openai_run
```

### CLI Reference — `nodes/ml_hyperparameter_tune_agent.py`

| Argument | Default | Description |
|---|---|---|
| `--provider` | `gemini` | LLM backend (`gemini` or `openai`) |
| `--model_id` | `gemini-3.1-flash-lite-preview` | Specific model ID |
| `--expert_advice` | `"None"` | Human guidance injected into the planner prompt |
| `--max_rounds` | `10` | Maximum completed experiment rounds |
| `--force_model` | `auto` | Lock the architecture or let the agent choose |
| `--run_name` | `test_run` | Run identifier — scopes all saved files |
| `--workspace` | `./siderius_workspace` | Root directory for all agent outputs |
| `--file_index` | `6` | Training/validation file index |
| `--progress_bar` | off | Stream live tqdm progress bars from subprocesses |

### 4. Open the dashboard

```bash
# Edit dashboard_config.yaml to point at your data directory, then:
python dashboard/main.py

# Development mode (auto-reload on code changes)
uvicorn dashboard.main:app --reload
```

Open `http://localhost:8000` in your browser. Key config options in `dashboard_config.yaml`:

```yaml
data_source:
  type: local           # "local" or "postgres"
  local:
    root_data_dir: /path/to/SIDEREIS_DATA
    models: [punet, wavenet, rnn, fcnet, transformer]  # leave [] to auto-discover

server:
  port: 8000
```

---

### Output layout

```
{workspace}/
├── summary_{run_name}.json         # all experiment records (agent memory)
├── run_output_{run_name}.json      # validated HyperparamTuningOutput
├── run_config_{run_name}.json      # startup config snapshot
├── configs/{run_name}/             # per-experiment configs
├── records/{run_name}/             # per-experiment detail JSONs
└── cached_models/                  # trained model checkpoints
```

---

## Running Tests

| Category | Scope | LLM | GPU | Location | When to run |
|---|---|---|---|---|---|
| Unit | Single node, mocked LLM | mock | no | `tests/unit/` | Every commit |
| Integration Tier 1 | Single node, real API | real | depends | `tests/integration/nodes/` | On demand |
| Integration Tier 2 | One graph edge (source → target) | real | depends | `tests/integration/protocols/` | On demand |
| Integration Tier 3 | Critical multi-hop loop | real | yes | `tests/integration/orchestrator/` | Before releases |

```bash
# Unit tests (always pass, no API key needed)
pytest tests/unit/ -v

# Tier 1 — individual node with real LLM (requires API key)
pytest tests/integration/nodes/ -m real_run -v

# Tier 2 — one protocol edge end-to-end
pytest tests/integration/protocols/ -m real_run -v

# All real-run tests at once
pytest tests/integration/ -m real_run -v
```

Tests marked `real_run` skip automatically when the required API key or data is absent. They never run in CI.
