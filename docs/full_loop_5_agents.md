# Full-Loop 5-Agent Workflow: Design, Testing, and Deployment

## Status: DESIGN — ready for implementation

## Overview

This document covers the complete model exploration workflow — from design through
testing to production deployment on both local and HPC environments.

```
Existing tuning outputs (punet, fcnet, wavenet)
  → Interpretation agent      (CPU + LLM API)
    → Proposal agent          (CPU + LLM API)
      → Implementor agent     (CPU + LLM API)
        → Validator agent     (CPU + LLM API + subprocess pytest)
          → Tuning agent      (GPU + LLM API)
```

---

## 1. Data Mode: Full Data (not single-file)

**The old single-file mode (`is_trial=False`, `file_index=N`) is OUTDATED.** It was an
early development shortcut that trained and evaluated on a single HDF5 file, producing a
non-comparable scoring metric. All production and testing should now use the **full data
mode** (`is_trial=True`), which provides:

- **Multi-file training**: streaming across all 20 files via `TIDMADEpochDataset`
- **Anchor-normalized scoring**: `score_vector()` with pre-computed segment anchors,
  producing a length-20 `file_vector` and a physics-meaningful scalar score
- **SampleSet-based data control**: explicit, reproducible segment selection per file

The trial mode strategies cover all use cases:

| Strategy | Files | Use case |
|----------|-------|----------|
| `"snapshot"` | All 20 files | Production runs, exploration workflow |
| `"anchors"` | Files 0, 10, 19 | Quick screening (3 frequency bands) |
| `"target"` | Specific file list | **Replaces single-file mode** — e.g. `target_files=[6]` |

The `"target"` strategy with a single file (e.g. `target_files=[6]`) is functionally
equivalent to the old `file_index=6` single-file mode, but uses the modern data pipeline
(SampleSet, streaming training, anchor-normalized scoring). There is no reason to use
the old single-file code path going forward.

---

## 2. GPU Resource Management

### The problem

Only the tuner agent uses GPU (training, inference, scoring). The other 4 agents are
CPU + LLM API only. On HPC clusters with expensive GPU allocations, running the full
workflow on a dedicated GPU wastes SU during the ~3-5 minutes of LLM-only work.

### Solution: VRAM budget per exploration

Instead of splitting CPU/GPU into separate jobs (complex orchestration), each exploration
receives a **VRAM budget** and multiple explorations share one physical GPU:

| Packing | Hard cap per process | LLM soft constraint | Headroom | Explorations per 32 GB GPU |
|---------|---------------------|---------------------|----------|---------------------------|
| 4-way | 8 GB | "VRAM < 6 GB" | 2 GB | 4 |
| 3-way | 10 GB | "VRAM < 8 GB" | 2 GB | 3 (2 GB unused) |
| 2-way | 16 GB | "VRAM < 12 GB" | 4 GB | 2 |
| 1-way | 32 GB | "VRAM < 24 GB" | 8 GB | 1 |

The LLM soft constraint is deliberately **lower** than the hard cap. LLM-generated
configs frequently exceed the stated limit — the headroom absorbs this overshoot
before the PyTorch hard cap triggers an OOM. The hard cap is the safety net; the
soft constraint is the first line of defense.

### Implementation: `gpu_memory_limit_gb`

Add a `gpu_memory_limit_gb` parameter that flows through the system:

```
run_workflow(gpu_memory_limit_gb=8)
  → TidmadSandbox(gpu_memory_limit_gb=8)
    → execute_training()  passes --gpu_memory_limit_gb 8 to subprocess
      → train_engine_sandbox.py calls torch.cuda.set_per_process_memory_fraction(8/32)
    → execute_inference() passes --gpu_memory_limit_gb 8 to subprocess
      → inference_single.py calls torch.cuda.set_per_process_memory_fraction(8/32)
  → Also injects "VRAM < 6 GB" into expert_advice.constraints (soft cap < hard cap)
```

**Critical**: training and inference run as **subprocesses** (via `subprocess.run()`),
not in the parent process. `set_per_process_memory_fraction` must be called inside
each subprocess before any CUDA allocation. The parent process passes the limit as a
CLI argument; each subprocess applies it at startup.

Three layers of enforcement:

1. **Hard cap** (PyTorch level, in subprocess): `torch.cuda.set_per_process_memory_fraction(limit / total)`
   prevents one process from stealing memory from co-located explorations. If a model
   exceeds the cap, PyTorch raises `OutOfMemoryError`.

2. **Error records** (tuner agent): when training or inference crashes (OOM or otherwise),
   the tuner now saves a structured error record (`error_training_oom`, `error_inference_oom`,
   `error_training`, `error_inference`) with a truncated error message. The LLM sees these
   records in its reflection context and learns to avoid the failing config. Status values
   on `ExperimentRecord`:
   - `success` — experiment completed normally
   - `skipped_oom_risk` — pre-check estimated OOM (never attempted)
   - `error_training` / `error_training_oom` — training subprocess crashed
   - `error_inference` / `error_inference_oom` — inference subprocess crashed

3. **Soft cap** (LLM guidance): the VRAM constraint is injected into the planner prompt
   via `expert_advice`, so the LLM picks model sizes and batch sizes that fit within
   the budget. This avoids hitting the hard cap in the first place.

### Slurm deployment: multiple explorations per GPU

```bash
# submit_exploration.slurm — allocate 1 GPU, run 3 explorations
#SBATCH --gres=gpu:v100:1
#SBATCH --mem=96G

# Launch 3 explorations with 10 GB VRAM each
python run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v1 &
python run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v2 &
python run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v3 &
wait
```

Each process calls `torch.cuda.set_per_process_memory_fraction(10/32)` at startup,
so even if one LLM-generated model is too large, it can't crash the others.

### Files to change

| File | Change | Status |
|------|--------|--------|
| `agent/schemas/hyperparam_tuning.py` | Add error status values to `ExperimentRecord` | Done |
| `nodes/ml_hyperparameter_tune_agent.py` | Save error records on training/inference failure with OOM detection | Done |
| `core/sandbox_executor.py` | Accept `gpu_memory_limit_gb`, pass as CLI arg to subprocesses | TODO (Phase 2) |
| `execute_tools/train_engine_sandbox.py` | Accept `--gpu_memory_limit_gb`, call `set_per_process_memory_fraction` | TODO (Phase 2) |
| `execute_tools/inference_single.py` | Accept `--gpu_memory_limit_gb`, call `set_per_process_memory_fraction` | TODO (Phase 2) |
| `workflows/model_exploration.py` | Pass `gpu_memory_limit_gb` to `TidmadSandbox`; inject VRAM soft constraint | TODO (Phase 2) |
| `run_exploration.py` | Add `--gpu_memory_limit_gb` CLI arg | TODO (Phase 2) |
| `sdsc_submission_scripts/submit_exploration.slurm` | New Slurm script for multi-exploration packing | TODO (Phase 4) |

---

## 3. Environments: Local vs Slurm

The workflow runs on two environments:

| | Local (lilab) | Slurm (SDSC Expanse) |
|---|---|---|
| **GPU** | RTX 5090 (32 GB), direct access | V100 (32 GB), via Slurm `gpu-shared` |
| **Execution** | `python run_exploration.py` in screen/tmux | `sbatch submit_exploration.slurm` |
| **Data paths** | `/home/klz/Data/TIDMAD/` | `/expanse/lustre/projects/ddp433/ym137/` |
| **Path config** | `tidmad_data_config.yaml` (per-machine) | Same file, different values |
| **API keys** | Environment variables | Environment variables in Slurm script |
| **GPU packing** | 1-4 explorations per GPU | 1-4 explorations per GPU |

Data paths resolve automatically via `tidmad_data_config.yaml` — never hardcoded.

---

## 4. Integration Test Design

### Prerequisites

| Requirement | How to check | Skip guard |
|-------------|-------------|------------|
| `GEMINI_API_KEY` set | `os.getenv("GEMINI_API_KEY")` | `pytest.skip()` |
| TIDMAD data directory | `TIDMAD_DATA_DIR` exists | `pytest.skip()` |
| SIDERIUS run data | `SIDERIUS_DATA_DIR` exists | `pytest.skip()` |
| Existing tuning outputs | `{siderius_data}/{model}/v3_file6/agent/run_output_v3_file6_agent.json` for punet, fcnet, wavenet | `pytest.skip()` |
| Segment anchor map | `{tidmad_data}/segment_anchors.json` | `pytest.skip()` |
| CUDA GPU available | `torch.cuda.is_available()` | `pytest.skip()` |

### File location

```
tests/integration/workflows/test_full_exploration_loop.py
```

### Marker and execution modes

```python
pytestmark = pytest.mark.real_run
```

```bash
# Local mode (default) — runs in-process
uv run pytest -m real_run tests/integration/workflows/test_full_exploration_loop.py -v -s

# Slurm mode — submits job, waits, then validates
uv run pytest -m real_run tests/integration/workflows/test_full_exploration_loop.py -v -s --execution-mode=slurm
```

### Architecture: separate execution from validation

```
┌─────────────────────────────────────┐
│  test_full_exploration_loop.py      │
│                                     │
│  1. EXECUTE (mode-dependent)        │
│     ├─ local: run_workflow()        │
│     └─ slurm: sbatch + poll squeue │
│                                     │
│  2. VALIDATE (shared logic)         │
│     ├─ Load saved JSON files        │
│     ├─ Assert all 5 stages correct  │
│     └─ Check trial→formal records   │
└─────────────────────────────────────┘
```

The validation logic is **identical** for both modes — it reads saved output files
from the workspace directory. Only the execution step differs.

### Slurm mode details

When `--execution-mode=slurm`:

1. **Generate a temporary Slurm script** that calls a standalone runner with test parameters
2. **Submit via `sbatch`** and capture the job ID
3. **Poll `squeue -j {job_id}`** every 30s until completion (timeout ~30 min)
4. **Run the same validation logic** on the output directory
5. **Report**: on failure, print the Slurm log file contents for debugging

For Slurm mode, additional config:
- `--slurm-partition`: GPU partition name (e.g. `gpu-shared`)
- `--slurm-account`: Allocation account (e.g. `ddp433`)
- `--slurm-workspace`: Output directory on the cluster filesystem
- Or read from `sdsc_test_config.yaml`

### Strategy: minimize wall-clock time

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `max_iterations` | 1 | One full loop is sufficient |
| `max_rounds` | 2 | Round 1 = trial, round 2 = forced formal (tests trial→formal transition) |
| `max_proposal_attempts` | 3 | Allow retries if LLM produces bad code |
| `is_trial` | True | Full data mode — the only production-supported mode |
| `trial_strategy` | "snapshot" | All 20 files, sparse sampling |
| `trial_portion` | 0.02 | Tiny data scope (~4 segments/file × 20 files = ~80 total) |
| `eval_portion` | 0.02 | Tiny eval scope for fast inference + scoring |
| `train_portion` | 1.0 | Use all of the (already tiny) training scope per epoch |
| `gpu_memory_limit_gb` | 8 | Test with constrained VRAM budget |
| `cleanup_denoised` | True | Delete H5 files after scoring to save disk |
| Model architecture | Forced small via `human_advice` | Shallow/narrow → fast forward/backward |

### human_advice strategy

**Proposal guidance** — force small and simple:
```
"Propose a VERY simple architecture — no more than 3 layers, fewer than 10K parameters.
 Use only basic PyTorch modules (nn.Embedding, nn.Conv1d, nn.Linear, nn.ReLU).
 Do NOT use attention, transformers, or complex gating mechanisms.
 The model must train and infer in under 30 seconds on a single GPU.
 Use segmentation_size=10000 in the baseline_config.train_config."
```

**Tuning guidance** — force small config and 1 epoch:
```
"CRITICAL: Use exactly 1 epoch, batch_size=1, lr=1e-4, device=cuda.
 Keep the model as small as possible — under 10K parameters.
 This is an integration test — speed matters more than score.
 You MUST use segmentation_size from the model_config as-is."
```

### What to assert

**1. Interpretation**
- Output is `InterpretationOutput`
- `model_types` contains punet, fcnet, wavenet
- `key_findings` is non-empty
- `take_home_message` is non-empty string
- `best_denoising_score` is not None

**2. Proposal**
- Output is `ProposalOutput`
- `model_name` is not in ["punet", "fcnet", "wavenet", "transformer", "rnn"]
- `model_name` is snake_case
- `mathematical_definition` is substantive (>50 chars)
- `expert_advice` is a valid `ExpertAdvice` with non-empty constraints
- `baseline_config` has model_config, train_config, loss_config keys

**3. Implementation**
- Output is `ImplementorOutput`
- `model_file_path` exists on disk
- `test_file_path` exists on disk
- Plugin file is valid Python (AST parse succeeds)

**4. Validation**
- Output is `ValidatorOutput`
- `passed` is True (if not, the workflow retries — assert after retry loop)
- All 7 checks passed: `plugin_registered`, `tests_passed`, `description_valid`,
  `config_fields_valid`, `instantiation_passed`, `gradient_check_passed`, `llm_review_passed`

**5. Tuning**
- Output is `HyperparamTuningOutput`
- `status` in ["completed", "partial"]
- `completed_rounds` >= 2 (round 1 = trial, round 2 = forced formal)
- `best_denoising_score` is not None (some score was produced)
- `all_records` has at least 2 records
- Both records have `file_vector` (full data mode produces anchor-normalized per-file scores)
- Last record's `is_trial` is False (formal mode forced on last round)
- Formal record's `file_vector` has 20 non-NaN entries (all files evaluated)

**Important**: `output.all_records` contains **raw dicts**, not Pydantic models.
Access fields with `record["is_trial"]`, `record["file_vector"]`, etc. To validate
as a Pydantic model, use `ExperimentRecord.model_validate(record)`.

### Error handling

If validation exhausts all 3 attempts without passing, `run_workflow()` returns an
**empty list** (no exception). The test must assert `len(results) == 1` and produce
a clear failure message if empty — likely pointing to the validation error messages
in the saved `validation_{run_name}.json` files.

### Post-workflow assertions via saved files

After `run_workflow()` returns, read the saved output files to validate each stage:

```
{workspace}/{run_name}/
├── iteration_001/
│   ├── interpretation_{run_name}.json    → validate InterpretationOutput
│   ├── attempt_001_{model_name}/
│   │   ├── proposal_{run_name}.json      → validate ProposalOutput
│   │   ├── implementor_{run_name}.json   → validate ImplementorOutput
│   │   ├── validation_{run_name}.json    → validate ValidatorOutput
│   │   ├── models/{model_name}.py        → assert file exists
│   │   └── tests/test_{model_name}.py    → assert file exists
│   └── {model_name}/
│       ├── run_output_{run_name}.json    → validate HyperparamTuningOutput
│       └── summary_{run_name}.json       → assert exists
```

### Estimated wall-clock time

| Stage | Estimated time | Notes |
|-------|---------------|-------|
| Load tuning outputs | <1s | JSON parsing |
| Interpretation (2+ LLM calls) | 10-20s | Per-model summaries + synthesis |
| Proposal (2 LLM calls) | 10-20s | Reasoning + commit |
| Implementation (2+ LLM calls) | 15-30s | Reasoning + code + possible retries |
| Validation (7 checks) | 20-40s | pytest subprocess + LLM review |
| Tuning round 1 (trial) | 15-30s | Tiny data (0.02 portion for both train and eval) |
| Tuning round 2 (formal) | 120-300s | Training still small, but eval uses **all** segments (eval_portion forced to 1.0 = 4000 segments across 20 files). This is the slowest step. |
| **Total** | **~4-8 minutes** | With retries: up to ~12 minutes |

**Note on formal round cost**: The tuner hardcodes `eval_portion=1.0` for formal rounds
regardless of the input `eval_portion`. This means inference + anchor-normalized scoring
runs on all 4000 segments (200 per file × 20 files). With a tiny model (<10K params) this
should complete in 2-5 minutes, but it dominates the test runtime.

### Cleanup

The test writes output to a temporary directory (`tmp_path` fixture). pytest cleans
this up automatically. No real data is modified.

The only side effect is the `agent_generated/models/` plugin registration by
`_register_plugin()` in the workflow. The test should clean this up in a fixture
teardown. Specifically, `_register_plugin()` copies two things:

- `agent_generated/models/{model_name}.py` — the plugin file
- `agent_generated/models/{model_name}/description.md` — the description directory

The teardown should delete both. Since we don't know `model_name` upfront (the LLM
chooses it), discover it from the workflow output (`results[0].model_type`) or by
scanning the iteration directory.

---

## 5. Plugin Output Type: Classifier vs Regressor

### The problem

The current `ExperimentConfig` validator hardcodes loss compatibility:

```python
if l_type == "smooth_l1" and m_type != "fcnet":
    raise ValueError("smooth_l1 is for fcnet only")
```

This breaks for plugin models: ALL plugins are blocked from `smooth_l1`, even if they're
regressors. And the LLM planner has no way to know which loss types are valid for a
newly proposed model — it follows the Cross-Exploration Rule and tries `smooth_l1`,
which crashes the training subprocess.

### The fix: per-model output type metadata

Each model (built-in and plugin) declares its **output type**, which determines valid loss types:

| Output type | Forward contract | Valid losses | Example models |
|------------|-----------------|-------------|----------------|
| `"classifier"` | `[B, 256, T] float32` | `ce`, `focal`, `focal_cw` | punet, transformer, wavenet, rnn, gated_fno |
| `"regressor"` | `[B, T] float32` | `smooth_l1` | fcnet |

### Implementation plan

#### Step 1: Add `PLUGIN_OUTPUT_TYPE` to the plugin contract

Each plugin file already exports 3 constants. Add a 4th:

```python
PLUGIN_MODEL_TYPE = "my_model"
PLUGIN_CONFIG_CLASS = MyModelConfig
PLUGIN_MODEL_CLASS = MyModel
PLUGIN_OUTPUT_TYPE = "classifier"  # or "regressor"
```

**Built-in models**: define a `BUILTIN_OUTPUT_TYPES` dict in `models_sandbox.py`:

```python
BUILTIN_OUTPUT_TYPES = {
    "punet": "classifier",
    "fcnet": "regressor",
    "transformer": "classifier",
    "wavenet": "classifier",
    "rnn": "classifier",
    "gated_fno": "classifier",
}
```

#### Step 2: Implementor writes `PLUGIN_OUTPUT_TYPE`

The implementor agent already knows the forward contract from the proposal's
`mathematical_definition`. Update the plugin file template to include:

```python
PLUGIN_OUTPUT_TYPE = "classifier"  # [B, 256, T] → 256-class classification
```

The LLM decides this based on the architecture. The validator checks it in Step 3.

#### Step 3: Validator checks output type consistency

Add an 8th validation check: verify that `PLUGIN_OUTPUT_TYPE` matches the actual
forward pass output shape:

- If output shape is `[B, 256, T]` → must be `"classifier"`
- If output shape is `[B, T]` → must be `"regressor"`
- Mismatch → validation fails with clear error

#### Step 4: Plugin loader collects output types

`ml_models/plugin_loader.py` already loads `PLUGIN_MODEL_TYPE`, `PLUGIN_CONFIG_CLASS`,
`PLUGIN_MODEL_CLASS`. Add:

```python
PLUGIN_OUTPUT_TYPE_REGISTRY: dict[str, str] = {}
# Populated at load time: {"my_model": "classifier", ...}
```

Add a helper function:

```python
def get_output_type(model_type: str) -> str:
    """Return 'classifier' or 'regressor' for any model (built-in or plugin)."""
    if model_type in BUILTIN_OUTPUT_TYPES:
        return BUILTIN_OUTPUT_TYPES[model_type]
    if model_type in PLUGIN_OUTPUT_TYPE_REGISTRY:
        return PLUGIN_OUTPUT_TYPE_REGISTRY[model_type]
    raise ValueError(f"Unknown model type: {model_type}")
```

#### Step 5: Update `ExperimentConfig` validator

Replace the hardcoded check with a registry lookup:

```python
@model_validator(mode='after')
def validate_architecture_loss_match(self) -> 'ExperimentConfig':
    output_type = get_output_type(self.model_type)
    l_type = self.loss_config.loss_type

    if l_type == "smooth_l1" and output_type == "classifier":
        raise ValueError(
            f"'{self.model_type}' is a classifier — use 'ce' or 'focal', not 'smooth_l1'."
        )
    if l_type in ["ce", "focal", "focal_cw"] and output_type == "regressor":
        raise ValueError(
            f"'{self.model_type}' is a regressor — use 'smooth_l1', not '{l_type}'."
        )
    return self
```

#### Step 6: Tell the LLM

In the planner prompt, when `force_model` is set, inject the output type:

```
This model is a CLASSIFIER (output: [B, 256, T] float32).
Valid loss types: ce, focal, focal_cw.
Do NOT use smooth_l1 — it is only for regressor models.
```

This comes from `get_output_type(force_model)` at prompt construction time.

#### Files to change

| File | Change |
|------|--------|
| `ml_models/models_sandbox.py` | Add `BUILTIN_OUTPUT_TYPES` dict |
| `ml_models/plugin_loader.py` | Load `PLUGIN_OUTPUT_TYPE`, add `PLUGIN_OUTPUT_TYPE_REGISTRY`, add `get_output_type()` |
| `ml_models/models_format_sandbox.py` | Update `ExperimentConfig` validator to use `get_output_type()` |
| `nodes/ml_model_implementor.py` | Add `PLUGIN_OUTPUT_TYPE` to plugin template |
| `nodes/ml_code_validator_agent.py` | Add 8th check: output type vs forward shape consistency |
| `agent/prompts.py` | Inject output type + valid losses when `force_model` is set |
| `agent_generated/models/*.py` | Backfill `PLUGIN_OUTPUT_TYPE = "classifier"` to existing plugins |
| Tests | Update plugin loader tests, validator tests, prompt tests |

---

## 6. Earlier Changes (completed)

- [x] Add trial mode parameters to `local_validated_model()` protocol
- [x] Add trial mode parameters to `run_workflow()`
- [x] Pass trial params from `run_workflow()` through to `local_validated_model()` call
- [x] Update `run_exploration.py` to use full data mode
- [x] Add unit tests for new protocol parameters
- [x] Fix `ExperimentConfig.model_type` to accept plugin models (`str` instead of `Literal`)
- [x] Fix planner prompt to show `force_model` when locked
- [x] Remove hardcoded model type restrictions (CLI, skill configs, dashboard)
- [x] Save error records on training/inference failure with OOM detection
- [x] Register GatedFNO in MODEL_REGISTRY and all config mappings

---

## 6. Implementation Checklist

### Phase 1: Local test mode (implement first)

- [ ] Create `tests/integration/workflows/test_full_exploration_loop.py`
- [ ] Add `--execution-mode` pytest option via `conftest.py`
- [ ] Skip guards: API key, TIDMAD data, SIDERIUS data, anchor map, CUDA
- [ ] **Execution**: call `run_workflow()` with full data mode + minimal config (1 iteration, 2 rounds, 3 attempts)
- [ ] **Validation** (shared function, reused by both modes):
  - [ ] Assert return value is a list with 1 `HyperparamTuningOutput`
  - [ ] Load and validate intermediate outputs from saved JSON files
  - [ ] Assert plugin file exists and is valid Python
  - [ ] Assert both tuning records have `file_vector` (anchor-normalized per-file scores)
  - [ ] Assert round 2 record is formal (`is_trial=False`)
- [ ] Clean up registered plugin in teardown
- [ ] Run once manually: `uv run pytest -m real_run tests/integration/workflows/test_full_exploration_loop.py -v -s`

### Phase 2: GPU memory management

- [x] Add error status values to `ExperimentRecord` (training/inference OOM detection)
- [x] Save structured error records when training/inference crashes (with OOM detection)
- [x] Unit tests for new error status values (5 tests)
- [ ] Add `gpu_memory_limit_gb` to `TidmadSandbox` → pass as CLI arg to subprocesses
- [ ] Add `--gpu_memory_limit_gb` to `train_engine_sandbox.py` and `inference_single.py`
- [ ] Call `torch.cuda.set_per_process_memory_fraction(limit / total)` in each subprocess
- [ ] Add `gpu_memory_limit_gb` to `run_workflow()` → inject VRAM soft constraint
- [ ] Add `--gpu_memory_limit_gb` to `run_exploration.py` CLI
- [ ] Test with `gpu_memory_limit_gb=8` on local server

### Phase 3: Slurm test mode

**Goal**: Run the same Tier 3 integration test on SDSC Expanse via Slurm, validating
that the workflow works on HPC infrastructure with different data paths and GPU hardware.

#### Step 3.1: Create standalone test runner

**File**: `sdsc_submission_scripts/run_exploration_test.py`

A standalone Python script (not pytest) that:
1. Calls `run_workflow()` with the same minimal test parameters as Phase 1
2. Calls `validate_workflow_outputs()` (imported from the test file)
3. Prints PASS/FAIL and exits with code 0/1
4. Accepts CLI args for workspace, run_name, and data paths

This decouples execution from pytest — the Slurm job runs this script directly.

```python
# Usage: python sdsc_submission_scripts/run_exploration_test.py \
#          --workspace /scratch/test_output --run_name test_full_loop
```

#### Step 3.2: Create Slurm submission script

**File**: `sdsc_submission_scripts/submit_exploration_test.slurm`

Follow the same pattern as `submit_hpt_agent.slurm`:
- Fixed SBATCH headers: account, job-name, output/error log paths
- Resource params via CLI: `--partition gpu-shared --gres gpu:v100:1 --mem 32G --time 00:30:00`
- Environment setup: source .bashrc, activate .venv, set PYTHONPATH
- Parse `tidmad_data_config.yaml` for data paths
- Run `run_exploration_test.py`
- Post-run verification: check output files exist and are non-empty

```bash
# Launch:
sbatch --partition=gpu-shared --gres=gpu:v100:1 --mem=32G --time=00:30:00 \
  sdsc_submission_scripts/submit_exploration_test.slurm \
  --workspace /expanse/lustre/projects/ddp433/ym137/test_output \
  --run_name test_full_loop
```

#### Step 3.3: Add Slurm execution mode to pytest

Update `tests/integration/workflows/test_full_exploration_loop.py`:
- Add `--execution-mode` pytest option in `conftest.py`
- When `--execution-mode=slurm`:
  1. Generate the `sbatch` command with appropriate resource flags
  2. Submit via `subprocess.run(["sbatch", ...])`, capture job ID from stdout
  3. Poll `squeue -j {job_id} -h` every 30s until job disappears (with 30 min timeout)
  4. Read Slurm output log to check exit status
  5. Read the workflow output directory (passed via `--workspace`)
  6. Call `validate_workflow_outputs()` on the results

- Additional pytest options for Slurm mode:
  - `--slurm-partition` (default: `gpu-shared`)
  - `--slurm-account` (default: `ddp433`)
  - `--slurm-workspace` (required in Slurm mode — no tmp_path on compute nodes)

#### Step 3.4: Verify on SDSC

```bash
# SSH to SDSC
ssh sdsc_expanse

# Pull latest code
cd ~/SIDERIUS && git pull origin small_sample_trial_fixed_config

# Option A: Run the standalone test directly on a compute node
srun --partition=gpu-shared --gres=gpu:v100:1 --mem=32G --time=00:30:00 \
  python sdsc_submission_scripts/run_exploration_test.py \
  --workspace /expanse/lustre/projects/ddp433/ym137/test_output \
  --run_name test_full_loop

# Option B: Submit via Slurm
sbatch --partition=gpu-shared --gres=gpu:v100:1 --mem=32G --time=00:30:00 \
  sdsc_submission_scripts/submit_exploration_test.slurm

# Option C: Run via pytest (from login node, submits Slurm job automatically)
uv run pytest -m real_run tests/integration/workflows/test_full_exploration_loop.py \
  -v -s --execution-mode=slurm \
  --slurm-workspace /expanse/lustre/projects/ddp433/ym137/test_output
```

#### Step 3.5: Checklist

- [ ] Create `sdsc_submission_scripts/run_exploration_test.py`
- [ ] Create `sdsc_submission_scripts/submit_exploration_test.slurm`
- [ ] Add `--execution-mode` pytest option to `conftest.py`
- [ ] Add Slurm execution path in test (sbatch + poll + timeout)
- [ ] Import and reuse `validate_workflow_outputs()` from Phase 1
- [ ] Verify `tidmad_data_config.yaml` on SDSC has correct paths
- [ ] Verify `segment_anchors.json` exists on SDSC
- [ ] Verify tuning outputs exist: `{siderius_data}/{model}/v3_file6/agent/run_output_v3_file6_agent.json`
- [ ] Run test on SDSC — all 5 stages pass
- [ ] Verify cleanup: plugin files removed from `agent_generated/models/`

---

### Phase 4: Production Slurm deployment

**Goal**: Run the full exploration workflow on SDSC for real research — multiple
iterations, full tuning budgets, and GPU packing for SU efficiency.

#### Step 4.1: Create production Slurm script

**File**: `sdsc_submission_scripts/submit_exploration.slurm`

Similar to `submit_hpt_agent.slurm` but calls `run_exploration.py` instead of
`run_comparison.py`. Key differences from the test script:
- Longer wall time: `--time=48:00:00` (production runs take hours/days)
- More memory: `--mem=64G` (formal rounds load all 20 files)
- Configurable parameters: `--max_iterations`, `--max_rounds`, `--gpu_memory_limit_gb`

```bash
sbatch --partition=gpu-shared --gres=gpu:v100:1 --mem=64G --time=48:00:00 \
  sdsc_submission_scripts/submit_exploration.slurm \
  --max_iterations 10 --max_rounds 20 --gpu_memory_limit_gb 24
```

#### Step 4.2: Multi-exploration GPU packing

**File**: `sdsc_submission_scripts/run_multi_exploration.sh`

Orchestrator script that launches N explorations on one GPU, similar to
`run_all_models_trial_sdsc.sh` but for the workflow:

```bash
# Allocate 1 V100 (32 GB), run 3 explorations at 10 GB each
#SBATCH --gres=gpu:v100:1
#SBATCH --mem=96G

python run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v1 &
python run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v2 &
python run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v3 &
wait
```

Each process gets a hard VRAM cap via `torch.cuda.set_per_process_memory_fraction()`.
The soft LLM constraint is set lower (e.g., "VRAM < 8 GB") to absorb overshoot.

#### Step 4.3: Post-run verification

The Slurm script should verify outputs after completion, same pattern as
`submit_hpt_agent.slurm`:

```bash
# Check workflow summary exists
SUMMARY_FILE="${WORKSPACE}/${RUN_NAME}/workflow_${RUN_NAME}.json"
if [ ! -s "$SUMMARY_FILE" ]; then
    echo "[FAIL] Workflow summary not found or empty: $SUMMARY_FILE"
    exit 1
fi

# Check at least one iteration completed
ITER_COUNT=$(python -c "import json; d=json.load(open('$SUMMARY_FILE')); print(d.get('completed_iterations', 0))")
if [ "$ITER_COUNT" -eq 0 ]; then
    echo "[FAIL] No iterations completed. Check logs for validation failures."
    exit 1
fi

echo "[SUCCESS] $ITER_COUNT iterations completed. Results: $SUMMARY_FILE"
```

#### Step 4.4: Monitoring

Production runs take hours/days. Monitoring options:
- **Slurm logs**: `tail -f sdsc_submission_scripts/logs/exploration_{jobid}.out`
- **Dashboard**: SSH tunnel + dashboard on port 8000 (already set up)
- **squeue**: `squeue -u ym137` to check job status
- **Iteration progress**: `ls {workspace}/{run_name}/iteration_*/` to count completed iterations

#### Step 4.5: SDSC-specific considerations

- **Lustre filesystem**: Use `$SCRATCH` (`/expanse/lustre/projects/ddp433/ym137/`) for
  all I/O — home directory has quota limits
- **Wall time**: gpu-shared partition has 48h limit. For longer runs, use checkpointing
  (the workflow already saves state per iteration — restart by loading from last iteration)
- **Network access**: SDSC compute nodes CAN access external APIs (Gemini, OpenAI) —
  verified in existing `submit_hpt_agent.slurm` runs
- **Module loads**: No special modules needed — Python venv handles all dependencies
- **Data paths**: `tidmad_data_config.yaml` on SDSC points to Lustre paths. Verify with:
  ```bash
  cat ~/SIDERIUS/tidmad_data_config.yaml
  # Should show: /expanse/lustre/projects/ddp433/ym137/...
  ```

#### Step 4.6: Checklist

- [ ] Create `sdsc_submission_scripts/submit_exploration.slurm`
- [ ] Create `sdsc_submission_scripts/run_multi_exploration.sh`
- [ ] Implement `gpu_memory_limit_gb` (Phase 2 prerequisite)
- [ ] Add post-run verification to Slurm script
- [ ] Test single exploration on SDSC (1 iteration, 2 rounds)
- [ ] Test multi-exploration packing (2 explorations on 1 GPU)
- [ ] Verify dashboard shows results from SDSC runs
- [ ] Document wall time estimates per packing configuration:
  | Packing | VRAM budget | Est. time per iteration | Max iterations in 48h |
  |---------|-------------|------------------------|-----------------------|
  | 1-way   | 24 GB       | TBD                    | TBD                   |
  | 2-way   | 12 GB       | TBD                    | TBD                   |
  | 3-way   | 8 GB        | TBD                    | TBD                   |
