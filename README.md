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
tune_ml_hyperparam_agent ────────────► result_interpretation_agent
                                                  │
                                                  ▼
                                       ml_model_proposal_agent
                                          │              │
                                          ▼              ▼
                                  ml_model_implementor   tune_ml_hyperparam_agent
                                          │
                                          ▼
                                  code_validator_agent
                                          │
                                          ▼
                                  tune_ml_hyperparam_agent  (new model)
```

---

## Project Structure

```
siderius/
├── agent/
│   ├── llm_bridge.py               # LLM transport — generate(), plan(), reflect()
│   ├── prompts.py                  # System prompts for planner and reflector
│   ├── tools_schema.py             # Skill loader
│   ├── schemas/                    # Pydantic input/output schemas for every node
│   │   ├── storage.py              # StorageConfig — shared per-node storage config
│   │   ├── hyperparam_tuning.py    # HyperparamTuningInput / Output / ExpertAdvice
│   │   ├── interpretation.py       # InterpretationInput / Output
│   │   ├── proposal.py             # ProposalInput / Output
│   │   ├── implementor.py          # ImplementorInput / Output
│   │   ├── validator.py            # ValidatorInput / Output
│   │   └── protocols/              # Typed edge functions (NodeAOutput → NodeBInput)
│   └── skills/                     # Atomic research skills (training, inference, scoring)
│
├── core/
│   ├── sandbox_executor.py         # TidmadSandbox: config validation, subprocess dispatch
│   └── plugin_loader.py            # Loads agent_generated/models/ into MODEL_REGISTRY
│
├── model_tools/                    # Built-in model definitions and Pydantic config schemas
│   ├── models_sandbox.py           # Network architectures + MODEL_REGISTRY
│   ├── models_format_sandbox.py    # PUNetConfig, AEConfig, TransformerConfig, etc.
│   └── loss_models_sandbox.py      # Loss functions + get_criterion factory
│
├── execute_tools/                  # Physical execution scripts (called as subprocesses)
│   ├── train_engine_sandbox.py     # Training loop
│   ├── inference_single.py         # Inference over validation set
│   └── denoising_score_single.py   # Denoising score computation
│
├── agent_generated/                # LLM-generated plugins (gitignored *.py)
│   ├── models/                     # Agent-written model plugins
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
│   │   └── model_tools/            # Model and loss function tests
│   └── integration/                # Real-data and real-GPU tests (requires API keys)
│
├── env_validation/
│   └── test_agent_env.py           # Validate Gemini / OpenAI API keys
│
└── ml_hyperparameter_tune_agent.py # Entry point: autonomous hyperparameter tuning loop
```

---

## Plugin System

Agent-generated models are dropped into `agent_generated/models/` as `.py` files. Each plugin must define:

- `PLUGIN_MODEL_TYPE: str` — unique model type key
- `PLUGIN_CONFIG_CLASS: BaseModel` — Pydantic config schema
- `PLUGIN_MODEL_CLASS: nn.Module` — model with forward contract `[B, T] int64 → [B, 256, T] float32`

`core/plugin_loader.py` scans this directory at import time and extends `MODEL_REGISTRY` in-place. The core codebase is never modified by agents.

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
python ml_hyperparameter_tune_agent.py --max_rounds 1 --run_name first_run

# Force a specific model with expert guidance
python ml_hyperparameter_tune_agent.py \
    --force_model transformer \
    --expert_advice "Set segmentation_size=10000 to avoid OOM. Use nhead=4." \
    --max_rounds 5 \
    --run_name transformer_v1

# Use OpenAI instead of Gemini
python ml_hyperparameter_tune_agent.py \
    --provider openai \
    --model_id gpt-4o \
    --max_rounds 5 \
    --run_name openai_run
```

### CLI Reference — `ml_hyperparameter_tune_agent.py`

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

```bash
# All unit tests
pytest tests/unit/ -v

# Integration tests (requires API keys + GPU)
pytest tests/integration/ -m real_run -v
```
