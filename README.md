# SIDERIUS

### **S**cientific **I**nquiry, **D**esign, **E**xploration, and **R**easoning **I**ntegrated **U**sing multi-agent **S**ystems

**SIDERIUS** is an autonomous research platform designed to automate the full-loop scientific discovery process—from literature-driven hypothesis formulation to experimental validation. Inspired by Galileo Galilei’s seminal work *Sidereus Nuncius*, the project leverages a multi-agent architecture to act as a "digital telescope," extracting fundamental physical laws from complex data noise.

---

> *"All truths are easy to understand once they are discovered; the point is to discover them."* <p align="left"><b>—Galileo Galilei</b></p>

---

## Project Structure

```
siderius/
├── agent/                      # LLM decision brain
│   ├── llm_bridge.py           # Gemini / OpenAI API wrapper (plan + reflect)
│   ├── prompts.py              # System prompts for Planner and Reflector
│   ├── tools_schema.py         # Dynamic skill loader (reads agent/skills/)
│   └── skills/                 # Pluggable atomic research skills
│       ├── training_skill/
│       ├── inference_skill/
│       ├── denoising_score_skill/
│       └── check_config_format_skill/
│
├── core/                       # Execution and recording infrastructure
│   ├── sandbox_executor.py     # TidmadSandbox: validates configs, dispatches subprocesses
│   └── recorder.py             # LocalRecorder / MongoRecorder for experiment memory
│
├── model_tools/                # Model definitions and Pydantic config schemas
│   ├── models_sandbox.py       # Network architectures + MODEL_REGISTRY
│   ├── models_format_sandbox.py# Pydantic configs: PUNetConfig, AEConfig, TransformerConfig, etc.
│   └── loss_models_sandbox.py  # Loss functions + get_criterion factory
│
├── execute_tools/              # Physical execution scripts (called as subprocesses)
│   ├── train_engine_sandbox.py # Training loop (Dataset, DataLoader, optimizer)
│   ├── inference_single.py     # Inference over validation set
│   └── denoising_score_single.py # Denoising score computation
│
├── env_validation/
│   └── test_agent_env.py       # Validate OpenAI / Gemini API keys
│
└── agent_main.py               # Main CLI entry point for the autonomous research loop
```

The agent loop follows an **Observe -> Think -> Act -> Reflect -> Commit** cycle:
1. **Observe**: load experiment history from `summary.json`
2. **Think**: LLM Planner proposes next experiment (model type, hyperparameters, hypothesis)
3. **Act**: `training_skill` -> `inference_skill` -> `denoising_score_skill`
4. **Reflect**: LLM Reflector converts raw results into research memory
5. **Commit**: save full record to `summary.json` for the next round

---

## Implemented Models

All models operate on SQUID time-series data (ADC values 0–255, sequence length configurable via `segmentation_size`).

| Key | Class | Description |
|---|---|---|
| `punet` | `PositionalUNet` | 1D convolutional U-Net with sinusoidal positional encoding at every layer. Depth and channel multiplier are agent-adjustable. |
| `fcnet` | `AE` | Fully connected AutoEncoder with configurable hidden layer dimensions (`latent_dims`). Supports both classification (CE/focal) and regression (smooth_l1) modes. |
| `transformer` | `TransformerModel` | Transformer encoder with embedding + positional encoding, projecting to 256 ADC classes. Use `segmentation_size <= 20000` to avoid OOM. |

## Implemented Loss Functions

| Key | Class | Compatible Models | Notes |
|---|---|---|---|
| `focal` | `FocalLoss1D` | `punet`, `transformer`, `fcnet` | Standard focal loss, tunable `alpha` and `gamma` |
| `focal_cw` | `FocalLoss1DCW` | `punet`, `transformer`, `fcnet` | Class-weighted focal loss |
| `ce` | `nn.CrossEntropyLoss` | `punet`, `transformer`, `fcnet` | Baseline classification loss |
| `smooth_l1` | `nn.SmoothL1Loss` | `fcnet` only | Waveform regression mode; incompatible with `punet`/`transformer` |

---

## Quick Start

### 1. Environment setup

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Python 3.12 and create virtual environment
uv python install 3.12
cd /path/to/siderius
uv venv --python 3.12
source .venv/bin/activate

# Install dependencies
uv add torch numpy scipy h5py tqdm "jax[cpu]" iminuit matplotlib pandas \
    requests scitokens openai google-generativeai pydantic python-dotenv
```

### 2. Configure API keys

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key
```

Validate connectivity:

```bash
python env_validation/test_agent_env.py
```

### 3. Run the autonomous agent

```bash
# Minimal run: let the agent decide everything, 1 round
python agent_main.py --max_rounds 1 --run_name first_run

# With expert advice and a forced model
python agent_main.py \
    --expert_advice "Try Transformer. CRITICAL: set segmentation_size=10000 to avoid OOM. Use nhead=4." \
    --max_rounds 1 \
    --force_model transformer \
    --run_name transformer_v1

# Use OpenAI instead of Gemini
python agent_main.py \
    --provider openai \
    --model_id gpt-4o \
    --max_rounds 5 \
    --run_name openai_run
```

### CLI Reference

| Argument | Default | Choices | Description |
|---|---|---|---|
| `--provider` | `gemini` | `gemini`, `openai` | LLM backend |
| `--model_id` | `gemini-3.1-flash-lite-preview` | any valid model ID | Specific model to use |
| `--expert_advice` | `"None"` | free text | Human guidance injected into the Planner prompt |
| `--max_rounds` | `10` | int | Max experiment iterations |
| `--force_model` | `auto` | `punet`, `fcnet`, `transformer`, `auto` | Lock the architecture or let the agent choose |
| `--run_name` | `test_run` | str | Name for this research session; scopes all saved records |
| `--workspace` | `./siderius_workspace` | path | Root directory for all agent-generated outputs (configs, cached models, records) |

---
