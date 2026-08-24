# `sdsc_submission_scripts/`

Entry scripts and slurm job templates for running SIDERIUS chain
exploration on both **lilab** (foreground subprocess, dev GPU) and
**SDSC Expanse** (slurm + afterany dependency chain).

The operator runbook is [`docs/guides/operating-a-run.md`](../docs/guides/operating-a-run.md);
launcher flags are in [`docs/reference/entrypoints.md`](../docs/reference/entrypoints.md).
This README is the
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
canonical/derived contract — is in this file and in the launcher headers
(`run_chain.sh`, `_chain_common.sh`).

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

5. **`--task_composition <manifest>` binds a run to ONE declared task**
   (Step 10 / P5+P6, W1). Without it the chain launches an un-composed
   (legacy TIDMAD) run whose argv is byte-identical to before the flag
   existed — the flag is forwarded to `run_one_iteration.py` only when
   non-empty. With it, the manifest's data path, dataset profile, metric,
   optional secondary metrics, Health family and task config are all
   resolved ONCE at the launcher edge and bound for the run.

   * shipped manifest: `configs/task_composition/tidmad.yaml`
   * the resolved `task_composition_fingerprint` is pinned into
     `{workspace}/run_invariants_lock.json`, so a resume under a DIFFERENT
     composition fails closed
   * a composed run does **not** load TIDMAD's legacy per-file reference
     table — that is task-specific science and its absence is deliberate
     and named (ruling C-P56-1), not a regression
   * a malformed or unreadable manifest refuses the launch and writes a
     `failed` manifest, so the consecutive-failure brake can still see it

6. **Cross-iteration carried state.** `accumulated_key_findings` (union)
   and `vocab_link_confirmations` (latest-wins) are restored from the
   prior iters' committed digests and handed to the workflow. The
   `iter_NNN/accumulated_findings_iter_NNN.json` sidecar records what was
   carried (`source_iters`, `count`) — it is a **log for auditing, not the
   transport channel**. Note that under cold start iteration 1 produces no
   findings, so a carried finding first reaches a proposer at iteration 3.

7. **A composed run's data root is TRANSPORTED to every child**
   (Step 11 C4, R-11-8). Until Step 11 the physical dataset root never
   crossed the subprocess boundary at all — training and inference carried
   no `--data_dir`, scoring carried no `--raw_data_dir` — so all three
   children fell back to the import-time `TIDMAD_DATA_DIR` and a composed
   run read TIDMAD's data whatever it had declared, silently. That fallback
   is now **legacy-only**.

   **Nothing changes on the operator surface.** `--data_dir` stays optional
   exactly as `docs/gates/gate_testing_standard.md` describes: the chain
   launcher resolves the root from `tidmad_data_config.yaml` at
   `run_one_iteration.py:1760`, *before* the composition is bound, and
   refuses the launch with exit 2 if nothing resolves. The module CLI
   (`model_exploration.py:3208`) falls back to `SIDERIUS_DATA_DIR` the same
   way. Pass `--data_dir` only to point a run at a different copy.

   The `CompositionDataRootMissing` refusal therefore guards **programmatic**
   callers of `bind_run_task_composition`, not operators: a composed run may
   not lean on the import-time fallback, and a caller that binds a
   composition without stating a root is refused at the binding edge, before
   any LLM call or GPU minute. An empty, placeholder or non-directory root is
   refused there too.

8. **Per-role subprocess memory ceilings** (Step 11 C3). Declared in
   `core/execution_calibration.py` with machine-readable provenance, and
   resolved through exactly TWO layers — no third:

   ```text
   SIDERIUS_SUBPROCESS_RSS_GB   (global; when set, wins for EVERY role)
       ->
   the role's declared default:  training 40 · inference 60 · scoring 24 GiB
   ```

   * `0` **disables** the ceiling. Kept deliberately: an operator
     diagnosing an allocator problem needs a way to take the cap off.
   * anything else non-integer or negative is **REFUSED loudly**
     (`MalformedCeilingOverride`). Before Step 11 it fell back to the role
     default in silence, so `SIDERIUS_SUBPROCESS_RSS_GB=4O` (letter O)
     produced a run that looked correctly configured and was not.
   * these are **execution-HOST calibration, not task config**. Each run
     records the ceilings it executed under in
     `{workspace}/run_invariants_lock.json` under `execution_calibration` —
     **recorded, never compared**, so the same scientific run resumed on a
     differently-calibrated host is still legal.
   * the inference ceiling's recorded derivation is marked
     `empirical_unverified`: its original arithmetic cited code that has
     since changed. The VALUE is known-good (full-scope baseline inference
     fails under 40 GiB); lowering it without re-verifying that is a
     regression.

9. **`--start_iter N` when auto-resume mis-parses.** The auto-resume
   inspector's stdout can be polluted by plugin-loader prints, which makes
   the computed `START_ITER` non-numeric and aborts the launch. Passing
   `--start_iter N` explicitly is the workaround.

---

## Where to look next

* Operator guide (launch, scope, budgets, resume, refusals):
  [`docs/guides/operating-a-run.md`](../docs/guides/operating-a-run.md)
* Launcher flags and defaults:
  [`docs/reference/entrypoints.md`](../docs/reference/entrypoints.md)
* Auto-resume, the invariants lock and carried state:
  [`docs/agent-reference/mechanisms/persistence-and-resume.md`](../docs/agent-reference/mechanisms/persistence-and-resume.md)
