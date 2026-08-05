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

### Campaign launchers and their control state

A **campaign** is a set of chains launched together under one identity.
Each launcher owns its own control state; none of them reads another's.

| file | status | control state | stop channel |
|---|---|---|---|
| `v19_queue_runner.sh` | **current production surface** | `$WS_ROOT/$CAMPAIGN_ID/{control,queue_state,pair_summaries}/` | `$WS_ROOT/$CAMPAIGN_ID/control/STOP`, or `SIGTERM`/`SIGINT`/`SIGHUP` |
| `v19_gate0_pair_runner.sh` | **current production surface** (Gate) | `$GATE_ROOT/${GATE_RUN_PREFIX}_pair_summary.json`, `${GATE_RUN_PREFIX}_runner.log` | **none** — the Gate has no stop file; its summary is written on every exit path by an `EXIT` trap |
| `v18r_queue_runner.sh` | **historical**, kept for reference | its own pre-V20 layout | unchanged; not modified by V20 PR E |

Despite the `v19_` filenames, both current launchers are
campaign-parameterised: the campaign id and the Gate prefix come from
the environment, and every name they produce derives from them. Nothing
infers a campaign, a role or a membership list from a filename prefix —
membership comes from the launcher's own `ROSTER`, and a chain's role
from that roster's fourth field.

**Layout status.** The V20 PR E layout is the one written and read today.
Pre-PR-E artifacts remain on disk and are never moved, rewritten or
deleted:

| path | read | written |
|---|---|---|
| `$WS_ROOT/$CAMPAIGN_ID/queue_state/wave_state.jsonl` | yes — canonical | yes |
| `$WS_ROOT/$CAMPAIGN_ID/pair_summaries/wave_<n>_<tag>.json` | — | yes (derived view) |
| `$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl` | **only under adoption** (see below) | never |
| `$WS_ROOT/${CAMPAIGN_ID}_queue_runner.log` | never | never |
| `$WS_ROOT/STOP` | observed and recorded; **no authority** | never |
| `$GATE_ROOT/gate0_pair_summary.json`, `gate0_runner.log` | never | never |
| `$WS_ROOT/<run_name>/` | chain workspaces, flat and unchanged | by the chain |

**Adoption** is decided once, when a campaign's `control/campaign.json`
is first written: if the campaign has no state of its own yet and a
pre-PR-E `${CAMPAIGN_ID}_wave_state.jsonl` exists, the stamp records
`legacy_adopted_from` and that file may be read for completion evidence.
After the campaign has its own state the legacy file is never consulted
again — a run recorded complete only there is launched, not skipped.

`CAMPAIGN_ID` and `GATE_RUN_PREFIX` become directory and file names, so
both are validated as safe path components (1-128 chars of
`[A-Za-z0-9._-]`, and not exactly `.` or `..`; `alpha..beta` is fine).
**Unset** falls back to the compatibility default; **explicitly empty**
is refused before anything is created.

Full operator detail — the stop commands, the wave-record schema and the
canonical/derived contract — is in `docs/running_chain_test.md`.

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
