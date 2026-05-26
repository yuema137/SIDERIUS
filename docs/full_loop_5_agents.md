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

## 0. Two Execution Environments: Local Server vs HPC Cluster

The workflow targets two fundamentally different deployment environments, and the
**execution model differs between them** because of resource scheduling constraints.
Understanding this distinction is essential before reading the rest of this document.

### Lilab (local server)

- **Single physical machine** with one GPU (RTX 5090, 32 GB VRAM) and direct shell access
- **No job scheduler** — Python processes run directly via `screen`/`tmux` or pytest
- **No wall-time limit** — long-running processes are fine
- **One workflow = one Python process**: `run_workflow(max_iterations=N)` runs N iterations
  in sequence inside a single Python interpreter, accumulating state in memory between iterations

**Execution model**: monolithic. The `iter 1 → iter 2 → ... → iter N` chain happens
inside one process. Each iteration's `summary_groups` (the historical context for the
interpretation agent) lives in Python memory and grows with each iteration.

### SDSC Expanse (HPC cluster)

- **Shared cluster** with many GPUs distributed across nodes (V100, A100)
- **Slurm job scheduler** required — no direct execution on compute nodes
- **Hard wall-time limits**: 48h max on `gpu-shared`, longer jobs are very hard to schedule
- **Multi-tenant fairness**: short jobs (1-4h) get scheduled in minutes; long jobs (12-48h)
  may sit in the queue for hours or days
- **Lustre filesystem** for I/O — home directory has tight quotas

**Resource scheduling constraint**: requesting a single 48-hour job for the whole
workflow is a **practical anti-pattern** on SDSC. The job will queue forever or get
preempted. The cluster scheduler favors many short jobs over one long one.

**Execution model**: per-iteration job submission. `iter 1 → iter 2 → ... → iter N` is
a chain of N independent Slurm jobs, each running `run_workflow(max_iterations=1)`.
State passing is **on disk**, not in memory: each iteration writes its tuning output
to a known path, and the next job loads it via the new `source_paths` API.

### Why the workflow code supports both

The same `run_workflow()` function runs on both environments. The difference is:

| | Lilab | SDSC |
|---|---|---|
| **Process model** | One process, N iterations | N processes (Slurm jobs), 1 iteration each |
| **State passing** | In-memory (`summary_groups` list) | On-disk (`source_paths` list) |
| **API used** | Legacy: `data_dir + model_types + source_run_name` | New: `source_paths=[...]` |
| **Chaining** | Python `for` loop inside `run_workflow()` | Slurm `--dependency=afterok:JOB_ID` |
| **Failure recovery** | Manual restart of the whole workflow | Resubmit the failed iteration only |
| **Concurrency** | One workflow at a time | Multiple workflows can pack onto one GPU via `gpu_memory_limit_gb` |

The new `source_paths` API (Phase 4) is **additive** — the legacy API still works on
lilab, and existing tests/scripts are unchanged. Slurm-mode chaining is built on top
of the new API without modifying the core workflow logic.

### How chain dependency is enforced (SDSC)

This is critical: on SDSC, **the next iteration must not start until the previous one
completes successfully**. Otherwise iteration N+1 would either:
- Start before iteration N writes its output → load fails
- Run on stale data if iteration N was retried

**Enforcement mechanism**: Slurm's native `--dependency=afterok:<job_id>` flag.

The orchestrator script `run_iteration_chain.sh` submits all N jobs **upfront** in a
single shell loop, with each job depending on the previous job's ID:

```bash
JOB_1=$(sbatch ... submit_one_iteration.slurm --iteration 1 ...)
JOB_2=$(sbatch --dependency=afterok:$JOB_1 ... --iteration 2 ...)
JOB_3=$(sbatch --dependency=afterok:$JOB_2 ... --iteration 3 ...)
# ...
```

After submission, `squeue` shows the chain:

```
JOBID    STATE     REASON
47882500 RUNNING   None             ← iter 1
47882501 PENDING   Dependency       ← iter 2 (waiting on 47882500)
47882502 PENDING   Dependency       ← iter 3 (waiting on 47882501)
```

Slurm handles the rest:

| Event | Slurm behavior |
|-------|---------------|
| Iteration N completes (exit 0) | Iteration N+1 transitions PENDING → RUNNING |
| Iteration N fails (exit non-zero) | Iteration N+1 is **automatically cancelled** with reason `DependencyNeverSatisfied` |
| Iteration N is manually cancelled | Iteration N+1 is also cancelled |
| Iteration N is still running | Iteration N+1 stays PENDING — never starts early |

**This is enforced by the Slurm scheduler itself**, not by polling or custom code.
Our orchestrator just submits all jobs in seconds and exits. There are no race
conditions, no waiting loops, no daemons to maintain.

**Requirement on the runner**: `run_one_iteration.py` must exit **non-zero** on any
failure (workflow exception, validation failure, missing manifest) so Slurm sees
the right exit code. This is verified in the runner's failure paths.

**Failure recovery**: if iteration N fails, jobs N+1..M are auto-cancelled. After
fixing the issue, manually resubmit with `run_iteration_chain.sh` starting from
iteration N (a future enhancement could add a `--start_from N` flag).

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
python scripts/run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v1 &
python scripts/run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v2 &
python scripts/run_exploration.py --gpu_memory_limit_gb 10 --run_name explore_v3 &
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
| **Execution** | `python scripts/run_exploration.py` in screen/tmux | `sbatch submit_exploration.slurm` |
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
| `"regressor"` | `[B, T] float32` | `smooth_l1` | (future regressor plugins) |
| `"hybrid"` | `[B, 256, T] float32` | ALL (`ce`, `focal`, `focal_cw`, `smooth_l1`) | fcnet |

Note: fcnet outputs `[B, 256, T]` like classifiers but supports regression-style
training with `smooth_l1`. The "hybrid" type allows all loss types.

### Implementation plan

#### Step 1: Add `PLUGIN_OUTPUT_TYPE` to the plugin contract and built-in registry

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

**Files**: `ml_models/models_sandbox.py`

**Checklist**:
- [ ] Add `BUILTIN_OUTPUT_TYPES` dict after `MODEL_REGISTRY`
- [ ] Verify all 6 built-in models have correct output types
- [ ] Unit test: `test_builtin_output_types_covers_all_registry_models`

#### Step 2: Plugin loader collects output types

`ml_models/plugin_loader.py` already loads `PLUGIN_MODEL_TYPE`, `PLUGIN_CONFIG_CLASS`,
`PLUGIN_MODEL_CLASS`. Extend to load `PLUGIN_OUTPUT_TYPE` and build a registry.

Add a unified helper:

```python
PLUGIN_OUTPUT_TYPE_REGISTRY: dict[str, str] = {}

def get_output_type(model_type: str) -> str:
    """Return 'classifier' or 'regressor' for any model (built-in or plugin)."""
    from ml_models.models_sandbox import BUILTIN_OUTPUT_TYPES
    if model_type in BUILTIN_OUTPUT_TYPES:
        return BUILTIN_OUTPUT_TYPES[model_type]
    if model_type in PLUGIN_OUTPUT_TYPE_REGISTRY:
        return PLUGIN_OUTPUT_TYPE_REGISTRY[model_type]
    # Unknown model — default to classifier (the standard forward contract)
    return "classifier"
```

**Files**: `ml_models/plugin_loader.py`

**Checklist**:
- [ ] Add `PLUGIN_OUTPUT_TYPE_REGISTRY` dict
- [ ] Load `PLUGIN_OUTPUT_TYPE` from each plugin file during `extend_registries()`
- [ ] Default to `"classifier"` if `PLUGIN_OUTPUT_TYPE` is missing (backward compat)
- [ ] Add `get_output_type()` function
- [ ] Unit test: `test_plugin_output_type_loaded`
- [ ] Unit test: `test_get_output_type_builtin`
- [ ] Unit test: `test_get_output_type_plugin`
- [ ] Unit test: `test_get_output_type_unknown_defaults_to_classifier`

#### Step 3: Backfill existing plugins

Add `PLUGIN_OUTPUT_TYPE = "classifier"` to all existing agent-generated plugins.
These all follow the `[B, 256, T]` contract.

**Files**: `agent_generated/models/*.py` (all existing plugins)

**Checklist**:
- [ ] Add `PLUGIN_OUTPUT_TYPE = "classifier"` to each plugin file, after `PLUGIN_MODEL_CLASS`
- [ ] Verify with: `grep PLUGIN_OUTPUT_TYPE agent_generated/models/*.py`

#### Step 4: Update `ExperimentConfig` validator

Replace the hardcoded `m_type != "fcnet"` check with a registry lookup:

```python
@model_validator(mode='after')
def validate_architecture_loss_match(self) -> 'ExperimentConfig':
    from ml_models.plugin_loader import get_output_type
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

**Files**: `ml_models/models_format_sandbox.py`

**Checklist**:
- [ ] Replace hardcoded check with `get_output_type()` lookup
- [ ] Existing unit tests still pass (punet+smooth_l1 rejected, fcnet+ce allowed)
- [ ] New test: `test_plugin_classifier_rejects_smooth_l1`
- [ ] New test: `test_plugin_regressor_accepts_smooth_l1`
- [ ] New test: `test_plugin_regressor_rejects_ce`

#### Step 5: Implementor writes `PLUGIN_OUTPUT_TYPE` in plugin template

The implementor assembles the plugin file from a template + LLM-generated code sections.
Add `PLUGIN_OUTPUT_TYPE` to the fixed template portion.

Since the current forward contract is always `[B, 256, T]` (classifier), the implementor
can hardcode `"classifier"` for now. When we support regressor plugins, the LLM will need
to decide based on the mathematical_definition, and the code prompt should ask it to
specify the output type.

**Files**: `nodes/ml_model_implementor.py`

**Checklist**:
- [ ] Find the `_assemble_plugin()` function that builds the plugin file
- [ ] Add `PLUGIN_OUTPUT_TYPE = "classifier"` after `PLUGIN_MODEL_CLASS` in the template
- [ ] Unit test: generated plugin file contains `PLUGIN_OUTPUT_TYPE`

#### Step 6: Validator checks output type consistency (8th check)

Add a new validation check in `_check_instantiation_and_gradient()` or as a separate
function: after the forward pass produces output, verify the output shape matches
the declared `PLUGIN_OUTPUT_TYPE`:

- `"classifier"` → output shape must be `[B, 256, T]`
- `"regressor"` → output shape must be `[B, T]`
- Mismatch → return `(False, "PLUGIN_OUTPUT_TYPE is 'classifier' but output shape is [B, T]")`

**Files**: `nodes/ml_code_validator_agent.py`

**Checklist**:
- [ ] Load `PLUGIN_OUTPUT_TYPE` from the plugin module
- [ ] Check output shape vs declared type after forward pass
- [ ] Add `output_type_valid` field to `ValidatorOutput` schema
- [ ] Update `passed = all([...])` to include the new check
- [ ] Unit test: classifier with `[B, 256, T]` output passes
- [ ] Unit test: classifier with `[B, T]` output fails
- [ ] Unit test: missing `PLUGIN_OUTPUT_TYPE` defaults to classifier

#### Step 7: Tell the LLM in planner prompt

In the planner prompt, when `force_model` is set, inject the output type and
valid loss types so the LLM doesn't try incompatible losses:

```
### MODEL OUTPUT TYPE:
- This model is a CLASSIFIER (output: [B, 256, T] float32).
- Valid loss types: ce, focal, focal_cw.
- Do NOT use smooth_l1 — it is only for regressor models (like fcnet).
```

This uses `get_output_type(force_model)` at prompt construction time.
When `force_model="auto"`, include a general note about loss compatibility.

**Files**: `agent/prompts.py`, `agent/llm_bridge.py` (pass output_type to prompt builder)

**Checklist**:
- [ ] Import `get_output_type` in prompt builder
- [ ] When `force_model != "auto"`: inject output type + valid losses
- [ ] When `force_model == "auto"`: inject general compatibility note
- [ ] Pass `output_type` info from tuner agent to `brain.plan()` if needed
- [ ] Unit test: prompt contains "CLASSIFIER" when force_model is a classifier
- [ ] Unit test: prompt contains "REGRESSOR" when force_model is fcnet
- [ ] Unit test: prompt contains valid loss list

#### Step 8: Run tests and verify end-to-end

- [ ] All existing unit tests pass (no regressions)
- [ ] Run GatedFNO cfg0 integration test (classifier, should reject smooth_l1)
- [ ] Run FCNet cfg0 integration test (regressor, should accept smooth_l1)
- [ ] Re-run full loop test — LLM should not try smooth_l1 on proposed classifier model
- [ ] Verify error records contain clear message when wrong loss is used

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

### Phase 4: Production Slurm deployment — Per-Iteration Job Model

**Goal**: Run the full exploration workflow on SDSC with **one Slurm job per
iteration**, not one job for the entire workflow. This solves the core SDSC pain
point: long wall-time jobs (12-48h) are hard to schedule on shared partitions,
while short jobs (1-4h) get scheduled quickly.

#### Why per-iteration, not per-tuning-round?

| Granularity | Wall time per job | Pros | Cons |
|---|---|---|---|
| **1 job per workflow** (`max_iterations=N`) | 12-48h | Simplest code | Hard to schedule, all-or-nothing failure |
| **1 job per iteration** ✓ | 1-4h | Easy scheduling, fault-tolerant per iteration | Need state passing between jobs |
| **1 job per tuning round** | 5-20 min | Most fine-grained | Excessive overhead (queue + venv setup per round) |

Per-iteration is the sweet spot:
- Each job runs `run_workflow(max_iterations=1)`: one full 5-agent loop
- Job lifetime is bounded (~1-4 hours) — fits SDSC's `gpu-shared` queue easily
- Multiple iteration jobs can pack onto a shared GPU (independent processes)
- Failure in iteration N doesn't waste iterations 1..N-1
- Each iteration's output is checkpointed before the next job starts

#### State passing: how iteration N+1 sees iterations 1..N

Currently `run_workflow()` accumulates state **in memory** during a single Python
process: iteration N reads `summary_groups`, runs the 5-agent loop, then appends
its output to `summary_groups` for iteration N+1.

For per-job execution we need **on-disk state passing**: each job's output is
discoverable by the next job. The orchestrator constructs the next job's source
list as: `[original_seeds] + [all_previous_iteration_outputs]`.

Currently iteration N sees:
- Original seed (from `data_dir/{model_type}/{source_run_name}/agent/run_output_*.json`)
- All previous iterations' tuning outputs (from in-memory `summary_groups`)

After the change, iteration N (separate Slurm job) will see:
- Original seed (loaded from explicit paths)
- All previous iterations' outputs (loaded from explicit paths in the workspace)

#### API change: explicit source paths

**Current API:**
```python
run_workflow(
    data_dir="/path/to/SIDEREIS_DATA",
    model_types=["punet", "wavenet"],
    source_run_name="small_sample_trial_v0",
    max_iterations=10,
    ...
)
# Loads: {data_dir}/punet/small_sample_trial_v0/agent/run_output_*.json
#        {data_dir}/wavenet/small_sample_trial_v0/agent/run_output_*.json
```

**New API (additive, backward compatible):**
```python
run_workflow(
    source_paths=[
        "/scratch/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json",
        "/scratch/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json",
        "/scratch/exploration_v1/iteration_001/{model_a}/run_output_iteration_001.json",  # from iter 1
        "/scratch/exploration_v1/iteration_002/{model_b}/run_output_iteration_002.json",  # from iter 2
    ],
    workspace="/scratch/exploration_v1",
    run_name="iteration_003",
    max_iterations=1,  # one iteration per job
    ...
)
```

**Backward compatibility**: when `source_paths` is None, fall back to constructing
paths from `(data_dir, model_types, source_run_name)`. Existing tests and
`run_exploration.py` keep working unchanged.

#### Step 4.1: Extend `load_tuning_outputs()` to accept explicit paths

**File**: `workflows/model_exploration.py`

Refactor to support both calling conventions:

```python
def load_tuning_outputs_from_paths(paths: list[str]) -> list[HyperparamTuningOutput]:
    """Load HyperparamTuningOutput from an explicit list of JSON file paths."""
    outputs = []
    missing = []
    for path in paths:
        if not os.path.exists(path):
            missing.append(path)
            continue
        with open(path) as f:
            data = json.load(f)
        outputs.append(HyperparamTuningOutput.model_validate(data))
    if missing:
        raise FileNotFoundError(f"Missing source files:\n" + "\n".join(missing))
    return outputs


def load_tuning_outputs(data_dir, model_types, source_run_name) -> list[HyperparamTuningOutput]:
    """Backward-compat wrapper — constructs paths from the old API."""
    paths = [
        os.path.join(data_dir, m, source_run_name, "agent",
                     f"run_output_{source_run_name}_agent.json")
        for m in model_types
    ]
    return load_tuning_outputs_from_paths(paths)
```

**Checklist:**
- [ ] Add `load_tuning_outputs_from_paths(paths)` function
- [ ] Refactor existing `load_tuning_outputs()` as backward-compat wrapper
- [ ] Unit test: paths-based loading returns same result as legacy API
- [ ] Unit test: missing path raises FileNotFoundError with clear message
- [ ] Unit test: handles mix of seed paths + iteration output paths

#### Step 4.2: Add `source_paths` to `run_workflow()`

**File**: `workflows/model_exploration.py`

```python
def run_workflow(
    # New: explicit source paths (preferred)
    source_paths: list[str] | None = None,
    # Legacy: derive paths from data_dir + model_types + source_run_name
    data_dir: str | None = None,
    model_types: list[str] | None = None,
    source_run_name: str | None = None,
    # ... rest unchanged
):
    # Resolve source paths
    if source_paths is None:
        if not (data_dir and model_types and source_run_name):
            raise ValueError("Must provide either source_paths OR (data_dir, model_types, source_run_name)")
        tuning_outputs = load_tuning_outputs(data_dir, model_types, source_run_name)
    else:
        tuning_outputs = load_tuning_outputs_from_paths(source_paths)
    summary_groups = tuning_outputs_to_summaries(tuning_outputs)
    # ... rest unchanged
```

**Checklist:**
- [ ] Add `source_paths` parameter (Optional, defaults to None)
- [ ] Update parameter resolution logic
- [ ] Unit test: explicit `source_paths` works
- [ ] Unit test: legacy API still works
- [ ] Unit test: error if neither is provided
- [ ] Update docstring with both calling conventions

#### Step 4.3: Per-iteration runner script

**File**: `sdsc_submission_scripts/run_one_iteration.py`

Like `run_exploration_test.py` but for production: takes explicit source paths,
runs `max_iterations=1`, outputs to a predictable iteration directory.

```python
# Usage:
# python run_one_iteration.py \
#     --workspace /scratch/exploration_v1 \
#     --iteration 3 \
#     --source_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \
#                    /scratch/exploration_v1/iter_001/{m}/run_output_iter_001.json \
#                    /scratch/exploration_v1/iter_002/{m}/run_output_iter_002.json \
#     --max_rounds 20 \
#     --gpu_memory_limit_gb 10 \
#     --llm_model gemini-3.1-pro-preview
```

The script:
1. Resolves the iteration number → workspace subdirectory (`{workspace}/iter_{N:03d}`)
2. Calls `run_workflow(source_paths=..., max_iterations=1, ...)`
3. After completion, writes a **manifest file** (`{workspace}/iter_{N:03d}/manifest.json`)
   that contains the tuning output path, model name, and best score — so the
   next job can discover this iteration's output without scanning.

**Checklist:**
- [ ] Create `sdsc_submission_scripts/run_one_iteration.py`
- [ ] CLI args: workspace, iteration, source_paths (nargs=+), max_rounds, gpu_memory_limit_gb, llm_model
- [ ] Resolve iteration directory and create it
- [ ] Call `run_workflow()` with explicit source_paths
- [ ] Write manifest.json with output_path, model_name, best_score
- [ ] Exit 0 on success, 1 on failure

#### Step 4.4: Per-iteration Slurm submission script

**File**: `sdsc_submission_scripts/submit_one_iteration.slurm`

Single Slurm job that runs one iteration. The orchestrator (Step 4.5) submits
multiple of these in sequence.

```bash
# Usage:
# sbatch --partition=gpu-shared --nodes=1 --ntasks=1 --gpus=1 --mem=24G \
#        --time=04:00:00 --cpus-per-task=8 \
#        sdsc_submission_scripts/submit_one_iteration.slurm \
#        --workspace /scratch/exploration_v1 --iteration 3 \
#        --source_paths /scratch/.../a.json /scratch/.../b.json \
#        --max_rounds 20 --gpu_memory_limit_gb 10
```

Same structure as `submit_exploration_test.slurm` but with:
- Production-realistic time/mem (4h, 24GB)
- Calls `run_one_iteration.py` instead of `run_exploration_test.py`
- No cleanup (we keep the iteration outputs for the next job)
- Post-run verification: check that `manifest.json` was written

**Checklist:**
- [ ] Create `sdsc_submission_scripts/submit_one_iteration.slurm`
- [ ] Match the format of `submit_hpt_agent.slurm` (account, output, error paths)
- [ ] Argument parsing for application-level args
- [ ] Post-run verification: `manifest.json` exists and is non-empty
- [ ] Document the sbatch invocation in the script header comment

#### Step 4.5: Orchestrator script

**File**: `sdsc_submission_scripts/run_iteration_chain.sh`

Submits N iteration jobs in sequence using Slurm `--dependency=afterok:JOB_ID`
for automatic chaining. Each job's source paths are constructed from the original
seeds + all previous iteration manifests.

```bash
# Usage:
# bash run_iteration_chain.sh \
#   --workspace /scratch/exploration_v1 \
#   --num_iterations 10 \
#   --gpu_memory_limit_gb 10 \
#   --seed_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json
```

The orchestrator:
1. Builds the source path list for iteration 1 (just the seeds)
2. Submits iteration 1 → captures job ID
3. For iteration 2..N:
   - Construct source paths = seeds + manifest paths from iterations 1..N-1
     - Manifest paths use predictable pattern: `{workspace}/iter_{i:03d}/manifest.json`
     - The runner reads each manifest to get the actual output_path
   - Submit with `--dependency=afterok:{prev_job_id}` so it only runs after the prior succeeds
4. Print all submitted job IDs

**Note**: The runner script (Step 4.3) needs to handle two formats in its
`--source_paths`:
- Direct JSON file paths (for original seeds): `.../run_output_*.json`
- Manifest file paths (for previous iterations): `.../manifest.json` → indirection to actual output

OR simpler: pass actual `run_output_*.json` paths directly, and the orchestrator
discovers them by reading `manifest.json` of each previous iteration.

**Checklist:**
- [ ] Create `sdsc_submission_scripts/run_iteration_chain.sh`
- [ ] CLI args: workspace, num_iterations, seed_paths, gpu_memory_limit_gb
- [ ] Submit iteration 1 with seed_paths only
- [ ] For each subsequent iteration:
  - [ ] Construct source list from seeds + previous manifests
  - [ ] Submit with `--dependency=afterok:{prev_job_id}`
- [ ] Print job ID chain
- [ ] Document failure modes (what happens if iter N fails — chain breaks at N+1)

#### Step 4.6: Workspace layout for per-iteration runs

```
{workspace}/
├── exploration_v1/                     # set by run_name
│   ├── iter_001/
│   │   ├── interpretation_iter_001.json
│   │   ├── attempt_001_{model_a}/
│   │   │   ├── proposal_iter_001.json
│   │   │   ├── implementor_iter_001.json
│   │   │   ├── validation_iter_001.json
│   │   │   ├── models/{model_a}.py
│   │   │   └── tests/test_{model_a}.py
│   │   ├── {model_a}/
│   │   │   ├── run_output_iter_001.json     ← input for iter_002
│   │   │   └── ...
│   │   └── manifest.json                     ← {output_path, model_name, score}
│   ├── iter_002/                             ← built from seeds + iter_001/manifest.json
│   │   └── ... same structure
│   └── iter_003/
└── ...
```

#### Step 4.7: SDSC-specific considerations

- **Lustre filesystem**: All workspace I/O goes to `/expanse/lustre/projects/ddp433/ym137/`
- **Wall time per iteration**: 1-4h is sufficient for one iteration with reasonable rounds
- **Network access**: SDSC compute nodes can reach Gemini API (verified)
- **GPU packing via memory limit**: see Phase 2 (`gpu_memory_limit_gb`) — 2-4 iterations
  per GPU is feasible
- **Failure recovery**: if iteration N fails, manually rerun it. Iterations N+1..M are
  blocked by `--dependency=afterok` and automatically cancelled — resubmit them after
  fixing iteration N.

#### Step 4.8: Documentation update

- [ ] Update `run_exploration.py` docstring to mention the per-iteration model
- [ ] Add a section to README about running on SDSC
- [ ] Document the orchestrator script usage with examples
- [ ] Document the manifest.json schema

#### Step 4.9: Top-level checklist (Phase 4)

- [ ] **Code changes** (works on lilab and SDSC):
  - [ ] Add `load_tuning_outputs_from_paths()` (Step 4.1)
  - [ ] Add `source_paths` parameter to `run_workflow()` (Step 4.2)
  - [ ] Unit tests for both, with backward-compat verification
- [ ] **SDSC scripts**:
  - [ ] `run_one_iteration.py` (Step 4.3)
  - [ ] `submit_one_iteration.slurm` (Step 4.4)
  - [ ] `run_iteration_chain.sh` (Step 4.5)
- [ ] **GPU memory packing** (Phase 2 prerequisite):
  - [ ] Implement `gpu_memory_limit_gb` end-to-end
  - [ ] Test 2 iterations sharing one GPU on SDSC
- [ ] **End-to-end test on SDSC**:
  - [ ] Submit 3-iteration chain
  - [ ] Verify each iteration uses the previous iteration's output
  - [ ] Verify final iteration sees seeds + all 2 previous outputs
  - [ ] Verify dashboard shows all iterations
- [ ] **Documentation** (Step 4.8)
