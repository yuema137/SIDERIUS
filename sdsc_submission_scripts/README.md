# `sdsc_submission_scripts/`

Entry scripts and slurm job templates for running SIDERIUS chain
exploration on both **lilab** (foreground subprocess, dev GPU) and
**SDSC Expanse** (slurm + afterany dependency chain).

The operator runbook is `docs/running_chain_test.md`. This README is the
**folder map** — what each file does and which one you actually invoke.

---

## Quick start

```bash
# Lilab (foreground, dev GPU)
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
    --run_name  lilab_v1 \
    --num_iterations 3 \
    --seed_paths /path/to/seed_punet.json /path/to/seed_wavenet.json

# SDSC Expanse (slurm)
bash sdsc_submission_scripts/run_chain.sh --mode sdsc \
    --workspace /expanse/lustre/projects/ddp433/ym137/expanse_v1 \
    --run_name  expanse_v1 \
    --num_iterations 10 \
    --seed_paths /scratch/.../seed.json \
    --partition gpu-shared --time 06:00:00 --mem 48G

# Dry-run anything by appending --dry-run
```

---

## Folder map

### Canonical chain orchestration

| file | role |
|---|---|
| `run_chain.sh` | **ENTRY POINT** — `exec` this. Mode-aware: python resolution, auto-resume, slurm vs subprocess dispatch. |
| `_chain_common.sh` | **SHARED LIBRARY** — `source`d by `run_chain.sh`. Mode-agnostic: defaults, CLI parser, iter loop body, per-iter app-arg builder. |
| `run_one_iteration.py` | **PER-ITER PYTHON RUNNER** — executes one iteration of the 5-agent workflow. Called once per iter by both modes. Writes `iter_NNN/manifest.json`. |
| `submit_one_iteration.slurm` | Slurm wrapper around `run_one_iteration.py`. Used by `run_chain.sh --mode sdsc`; chained via `--dependency=afterany:<prev_job>`. |

The role split between `run_chain.sh` and `_chain_common.sh` keeps the
iter loop identical across backends so lilab and SDSC can never diverge.
The shared library is also unit-testable in isolation (see
`tests/unit/sdsc_submission_scripts/`).

### Tier 3 integration test

| file | role |
|---|---|
| `run_exploration_test.py` | Standalone Tier 3 runner: full 5-agent workflow, minimal config, no pytest. |
| `submit_exploration_test.slurm` | Slurm wrapper for the above. |

### Auxiliary

| file | role |
|---|---|
| `submit_hpt_agent.slurm` | Universal slurm dispatcher for ad-hoc agent jobs (legacy; standalone runs of `ml_hyperparameter_tune_agent.py` via `scripts/run_comparison.py`). |
| `run_all_models_trial_sdsc.sh` | SDSC-side multi-model trial launcher (sequential per-model invocation of `scripts/run_comparison.py` with `--is_trial`). Distinct from `scripts/run_all_models_trial.sh` which targets lilab. |

Operator-advice JSON files (e.g. `human_advice_chain_test.json`,
`human_advice_chain_formal.json`) live in `advice/workflow/` — see
`advice/README.md` for the split between single-agent and workflow-level
advice files.

### Deprecated (kept for muscle memory)

| file | role |
|---|---|
| `run_iteration_chain.sh` | Thin wrapper → `run_chain.sh --mode sdsc`. Emits a deprecation warning. Removal tracked under Commit 15. |
| `run_iteration_chain_lilab.sh` | Thin wrapper → `run_chain.sh --mode lilab`. Same status. |

### Generated / runtime

| path | what |
|---|---|
| `logs/` | Slurm `--output` / `--error` files (`iter_<jobid>.out`, `tier3_<jobid>.out`, etc). |
| `__pycache__/` | Python bytecode cache (gitignored). |

---

## Architectural invariants

1. **`_chain_common.sh` knows nothing about lilab or SDSC.** Adding a
   new backend (k8s, AWS Batch, …) means defining one new
   `submit_iteration_X` in `run_chain.sh` plus a `--mode x` case; the
   library is untouched.

2. **`run_chain.sh` does not contain the iter loop.** The loop body
   lives in `_chain_common.sh:run_chain()`. The entry script defines
   `submit_iteration` (mode-aware) and then calls `run_chain` from the
   library.

3. **Every iter writes `iter_NNN/manifest.json`.** The manifest is the
   chain's discoverable handoff between iters (status, output path,
   model name, best score). It is also the source of truth for
   auto-resume (`scripts/inspect_run_state.py --layout chain
   --next-iter`).

4. **Manifest statuses:**
   * `completed` — workflow produced a real `best_denoising_score`.
   * `no_records` — workflow ran cleanly but every tuner round was
     skipped (gate exhaustion or all rounds returned null score).
     Chain continues; the next iter's LLM sees the skip and adapts.
   * `failed` — workflow itself crashed (Python exception, seed
     resolution error, restore error). Counts toward the consecutive-
     failure brake (`--max_failed_iterations`, default 3).

---

## Where to look next

* Operator runbook (step-by-step launch + recovery):
  `docs/running_chain_test.md`
* Auto-resume design + manifest contract:
  `docs/phase68_orchestrator_memory_and_resume.md`
* Token-budget audit / chain knobs:
  `docs/audit_and_optimize_token_usage_and_growth.md`
