#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain — SHARED LIBRARY (source, do not exec)
# ---------------------------------------------------------------------------
# Role : library, mode-agnostic. Holds everything that is identical between
#        any execution backend (lilab subprocess, SDSC slurm, future ones).
# Entry: run_chain.sh sources this file and adds the mode-aware pieces.
# Files: see scripts/launch/README.md for the folder map.
# Doc  : docs/running_chain_test.md is the operator runbook.
# ---------------------------------------------------------------------------
# What lives here:
#   * Default values for every CLI flag
#   * parse_chain_args     — unified CLI parser
#   * load_advice_file     — human-advice JSON validation
#   * build_source_paths   — per-iter SOURCE_PATHS construction
#   * build_app_args       — per-iter run_one_iteration.py argv assembly
#   * print_chain_header   — formatted launch banner
#   * run_chain            — the iteration loop body
#
# What does NOT live here (lives in run_chain.sh instead):
#   * python interpreter resolution + version guard
#   * auto-resume inspector call
#   * mode-specific submit_iteration implementations
#       - submit_iteration_lilab : foreground subprocess
#       - submit_iteration_sdsc  : sbatch + afterany dependency chain
#   * mode dispatcher + final summary
#
# Contract for callers:
#   1. Source this file.
#   2. Define a function `submit_iteration <ITER>` that runs ONE iteration
#      using the already-populated APP_ARGS and SOURCE_PATHS arrays.
#   3. Call `parse_chain_args "$@"`, then `run_chain`.
#
# Why split this from run_chain.sh: the iter loop body must be identical
# across all backends so lilab and SDSC can never diverge in subtle ways.
# The split also lets unit tests source this library directly (without a
# python interpreter or slurm) to exercise the argument-parsing and
# arg-building logic in isolation.

set -e
set -o pipefail

# --- Defaults (apply to both lilab and SDSC) ---
WORKSPACE=""
NUM_ITERATIONS=2
SEED_PATHS=()
# Commit 4.3 follow-up — chain-level run name. Forwarded as --run_name to
# run_one_iteration.py, where it (a) labels chain_run_name in audit logs
# and (b) seeds {workspace}/.token_run_id on iter 1 so all subprocess
# iters share one immutable run_id (§1.4.1). Required: chain runs must
# pin their identity at launch, not at the first subprocess.
RUN_NAME=""
MAX_ROUNDS=3                        # §3.2: matches run_one_iteration.py default 3
MAX_EPOCHS=1                        # §3.2: matches run_one_iteration.py default 1
# D-BUD-6 — per-mode epoch ceilings. "" ≡ omit ≡ run_one_iteration.py's
# None (that role stays on the mode-agnostic MAX_EPOCHS); forwarded only
# when typed, so an unset pair keeps the child argv byte-identical.
TRIAL_MAX_EPOCHS=""
FORMAL_MAX_EPOCHS=""
# Tuner delta-gates (added in commit 8f1cf52). Defaults match the
# HyperparamTuningInput schema defaults so omitting these flags
# reproduces pre-v16 behaviour.
# V20 PR D (D-C1b): the formal-launch policy declarations. A chain launch
# must state what its HealthGate verdicts DO and whether its results may
# inform science; run_one_iteration.py refuses a launch that omits either,
# or whose declaration contradicts the HealthGate config it names.
#
# blocking + scientific is what a V19/V20 formal chain already IS: it runs
# configs/health_checks.yaml, whose three role:blocking gates invalidate a
# round, and its results feed the chain incumbent and the science. These
# values state that fact; they do not change it.
HEALTHGATE_MODE=blocking
RESULT_AUTHORITY=scientific
SKIP_FORMAL_MIN_DELTA=-1.0
BYPASS_FORMAL_TIME_BUDGET_MIN_DELTA=0.0
BYPASS_FORMAL_TIME_BUDGET_MINUTES=""             # Lane F3: empty == omit == no bypass ceiling extension
LLM_MODEL="gemini-3.1-pro-preview"  # §3.2: matches run_one_iteration.py default
LLM_CONFIG=""
# F-PROFILE-WIRE-1 — the DECLARED required runtime profile. Both empty ==
# omitted == the legacy measured > shipped > uncalibrated ladder, and no new
# token reaches the child argv. Declared, they make profile resolution
# fail-closed: wrong device/regime, a missing overlay, a digest mismatch or a
# verified overlay lacking the row all REFUSE the launch.
REQUIRED_RUNTIME_PROFILE_PATH=""    # ABSOLUTE artifact path; empty == undeclared
REQUIRED_RUNTIME_PROFILE=""         # '<gpu_slug>/<regime>'; empty == undeclared
REQUIRED_RUNTIME_PROFILE_SHA256=""  # 64 hex chars of the certified artifact
HEALTH_CHECKS_CONFIG=""             # optional; empty preserves tuner's shipped default
# Step 10 / P5+P6 W1 — the operator's only way to launch a COMPOSED run.
# Empty == omitted == Python None == the legacy un-composed run, whose child
# argv stays byte-identical. Until this flag existed the chain could not
# launch a composed run at all, even though run_one_iteration.py has parsed
# --task_composition since P1.
TASK_COMPOSITION=""                 # required task declaration
DATA_SCOPE=""                       # DS6c: '4-9' / '4,5,6,7,8,9' / mixed; empty = complete dataset
HEALTH_GATE_ENABLED=1               # DS6c: --no-health_gate_enabled disables the subsystem
HEALTH_GATE_FILES=""                # DS6c: shared monitored-file list; empty = YAML defaults
REFLECT_PROVIDER=""
REFLECT_MODEL_ID=""
TRIAL_PORTION=""                    # Lane F2 tri-state: empty == omit == AGENT_CONTROLLED; typed == EXPERIMENT_FIXED (plan_overrides lock)
TRAIN_PORTION=""                    # Lane F2 tri-state: empty == omit == AGENT_CONTROLLED
EVAL_PORTION=""                     # Lane F2 tri-state: empty == omit == AGENT_CONTROLLED
HUMAN_ADVICE_FILE=""
ANALYSIS_SOURCE_PROMPT=""
ADVICE=""
# The launcher's OBSERVED sha256 of the advice artifact. Forwarded as a
# DECLARATION: run_one_iteration.py certifies it against its own read and
# pins the OBSERVED digest, never this one. Empty == undeclared, and the
# child's argv is then byte-identical to a pre-feature chain.
ADVICE_SHA256=""
PLAN_OVERRIDES=""
WORKFLOW_PARAMETER_RULES=""          # JSON ParameterRules; empty = workflow unconstrained
# DATA_DIR is caller-owned physical execution provenance. The generic chain
# has no task, machine, environment-variable, or repository fallback; Python
# startup refuses an omitted or unreadable root before any expensive work.
DATA_DIR=""
TRAINING_BUDGET_RESERVE_FRACTION="" # opt in; omitted preserves fixed epochs
TRIAL_TIME_BUDGET_MINUTES=""        # §3.2: empty == omit == Python None
FORMAL_TIME_BUDGET_MINUTES=""       # §3.2: empty == omit == Python None
TRIAL_TIME_ADMISSION_SOURCE="measured"
FORMAL_TIME_ADMISSION_SOURCE="measured"
FORMAL_EVAL_PORTION=1.0             # Phase R §13: eval-side scope for formal training; default 1.0 = production full-clone (lower for smoke/CI)
GPU_ADMISSION_MEASUREMENT_SOURCE="" # B-G3: reference, never a figure; empty == omit
GPU_ADMISSION_ENFORCEMENT=""        # B-G3/D-B4: empty == omit == observe_only
GPU_PAIR_CEILING_GIB=""             # B-G3: empty == omit == defer to env/default
TRIAL_VRAM_BUDGET_GB=""             # §3.2: empty == omit == Python None
FORMAL_VRAM_BUDGET_GB=""            # §3.2: empty == omit == Python None
VRAM_PROBE_STEP_TIMEOUT_SECONDS=180  # one training-mode/inference footprint forward
VRAM_PREFLIGHT_TOTAL_TIMEOUT_SECONDS=900 # complete isolated preflight worker
VRAM_PREFLIGHT_HOST_MEMORY_LIMIT_GB="" # optional complete isolated process-tree RSS
# §3.2 — Runtime-control operator surface (RT6, runtime design §4/§5).
# Defaults synced to run_one_iteration.py (§5 provisional operational
# values); 0 disables a numeric guardrail; booleans forwarded when 1.
MAX_STEPS_PER_ATTEMPT=0             # Disabled: time budgets govern runtime
MIN_FORMAL_BATCH_SIZE=0              # §3.2: matches disabled Python default
ALLOW_EXTREME_STEPS=0
RUNTIME_WATCHDOG=""                 # arXiv #261 tri-state: empty == omit == the (device, execution regime) runtime profile decides; 1 forwards --runtime_watchdog; 0 forwards --no-runtime_watchdog
EXECUTION_REGIME=""                 # arXiv #261: empty == omit == Python default 'single'; the posture declares co-resident regimes
ENABLE_CHAIN_INCUMBENT_FORMAL_GATES=0  # V19 PR 1: consumption-only switch; matches Python default False
ORDER_STRATEGY_OVERRIDE=""          # V19 PR 2: empty == omit == agent decides (default 'shuffle')
FILE_ORDER_OVERRIDE=""              # V19 PR 2: empty == omit == ascending scope order
ENABLE_STRUCTURED_HEALTH_FEEDBACK=0 # V19 PR 3: prompt-rendering flag; matches Python default False
HEALTH_FEEDBACK_HISTORY_WINDOW_ITERATIONS=""   # V19 PR 3: empty == omit == Python default 3
HEALTH_FEEDBACK_HISTORY_MAX_ENTRIES_PER_MODEL="" # V19 PR 3: empty == omit == Python default 8
RUNTIME_SAFETY_FACTOR=1.0           # §3.2: matches Python default; V18 posture 1.5
RUNTIME_TRIAL_SAFETY_FACTOR=""      # §3.2: empty == omit == Python None; effective V18r posture 3.0 (d8d4f1e)
RUNTIME_FORMAL_SAFETY_FACTOR=""     # §3.2: empty == omit == Python None
RUNTIME_WATCHDOG_SAFETY_FACTOR=""   # §3.2: empty == omit == Python None; V19 split — watchdog-only multiplier (5090 posture 3.5)
RUNTIME_WATCHDOG_FLOOR_SECONDS=""   # arXiv #261: empty == omit == profile floor (legacy 60.0 when uncalibrated); explicit value overrides; V18 posture 120
RUNTIME_VERIFICATION_MAX_WALL_SECONDS="" # empty == omit == adaptive verifier default; explicit value supports slow-step workloads
EXPLORATION_MODE="auto"             # §3.2: matches Python default
MINIMUM_BOLDNESS="0.05"             # §3.2: matches Python default
# §3.2 — Adaptive-tuning brakes (default-synced to run_one_iteration.py)
ATTEMPTS_PER_ROUND=3                # inner attempt budget for trial rounds
ATTEMPTS_PER_FORMAL_ROUND=5         # inner attempt budget for formal-promotion round
MAX_FAIL_ROUNDS=3                   # consecutive-failure brake for outer loop
# §3.2 — Propose→Implement retry brakes (13.C-bis)
MAX_PROPOSAL_ATTEMPTS=3             # retry budget for propose→implement→validate
MAX_IMPL_ATTEMPTS=3                 # implementation retries per proposal
# §3.2 — Trial / formal strategy + formal-scope (13.C-bis)
TRIAL_STRATEGY="snapshot"           # DEPRECATED no-op (DS7); parsed, not forwarded
FORMAL_STRATEGY="snapshot"          # choices: snapshot|anchors|target
FORMAL_TRAINING_SCOPE_SOURCE="operator" # choices: operator|agent
FORMAL_PORTION=0.1                  # segments per file for formal training scope
FORMAL_TRAIN_PORTION=1.0            # per-epoch iteration fraction for formal training
FORMAL_ROUND_STRATEGY="full_clone"  # canonical: full_clone|hybrid_params|independent (legacy aliases inherit_best_trial|llm_propose accepted, schema canonicalises)
# §3.2 — Degenerate-output reaction policy (paired with execute_tools.squid_health_checks)
DEGENERATE_PENALTY_SCORE=""                 # empty → omit flag → schema default None (null score on collapse)
# §3.2 — Data slicing / reproducibility (13.C-bis; None-default → omit when empty)
TARGET_FILES=()                     # DEPRECATED no-op (DS7); parsed, not forwarded
SAMPLING_SEED=""                    # empty == omit == Python None
# §3.2 — Debugging (action=store_true; 1 emits the flag)
DEBUG_DUMP_PROMPTS=0
# §3.2 — Pseudo-mode flags (Stage 3 / Commit 4.5; action=store_true on Python side)
# When set, the Python runner swaps LLMBridge / TidmadSandbox for stateless
# stubs and prints a [PSEUDO-MODE ACTIVE] banner to stderr. Default 0 = off
# = production. See docs/audit_and_optimize_token_usage_and_growth.md C4.5.
IS_PSEUDO_LLM=0
IS_PSEUDO_TRAINING=0
# Stage 4 / Commit 4.6 — Consecutive-iter failure brake (chain-level).
# Distinct from MAX_FAIL_ROUNDS (inner propose-implement loop brake): this
# halts the *chain* when the most recent N committed iters all carry
# manifest.status='failed'. Default 3 matches the Python argparse default.
MAX_FAILED_ITERATIONS=3
# Default retirement is now the Python run's policy too. The old negative
# cleanup spelling remains a compatibility alias for the positive retention
# switch, so existing campaigns keep their explicitly requested outputs.
CLEANUP_DENOISED=1
OUTPUT_RETENTION_REQUEST=""
RETAIN_TRAINING_CHECKPOINTS=0
# --- Shell entry condition ---------------------------------------------------
# "Initialise every consumed shell variable" is an ENTRY CONDITION of this
# reused library, not a cleanup step performed by each
# caller. Every variable build_app_args reads is assigned HERE, at source
# time, BEFORE parse_chain_args runs — so the only route into the child
# argv is a flag.
#
# These five were the exception. They were read as "${VAR:-}" and assigned
# NOWHERE, so an exported value in a .bashrc or a tmux session that once
# ran a validation posture reached APP_ARGS directly. That is not a
# cosmetic hole: --validation_fixed_candidate_plan BYPASSES THE PROPOSER,
# substituting one fixed candidate plan for the whole campaign, and
# Task-specific launchers must refuse ambient validation overrides themselves.
# — the environment route went around a refusal that was already written.
#
# The `:-` form is retained at the read sites on purpose: it is what makes
# `set -u` adoption safe later, and it must never again be the reason a
# missing default goes unnoticed. The census in
# tests/unit/sdsc_submission_scripts/test_fscani2_chain_entry_condition.py
# derives every name build_app_args reads and fails when one of them is
# not assigned in this block.
VALIDATION_FIXED_CANDIDATE_PLAN=""
VALIDATION_MAX_PORTION=""
VALIDATION_MAX_TRAIN_SAMPLES=""
VALIDATION_MAX_SAMPLES=""
VALIDATION_MAX_PHASE_SECONDS=""
# The DECLARED environment inputs of this library: the complete list of
# names it may legitimately read from the environment. CHAIN_STOP_FILE is
# a documented operator override (docs/running_chain_test.md, the stop-file
# table row) with its own regression test, so it is declared here rather
# than initialised away. Anything NOT on this list and NOT assigned above
# is an injection route, and the census names it.
CHAIN_DECLARED_ENV_INPUTS=(CHAIN_STOP_FILE)

# --- Unified-orchestrator (run_chain.sh) defaults ---
# MODE picks the execution backend: lilab (foreground subprocess) or
# sdsc (sbatch + afterany). Required when invoking run_chain.sh directly;
# the legacy stubs preset it before calling parse_chain_args.
MODE=""
# DRY_RUN=1 makes run_chain print the exact command per iteration without
# touching the workspace or submitting any jobs. Side-effect-free.
DRY_RUN=0
# Auto-resume control (Phase 6.8 Commit 13.B). AUTO_RESUME=1 means the
# orchestrator queries scripts/launch/inspect_run_state.py --next-iter to pick up
# where a partially-run chain left off. --no_auto_resume forces 1.
# --start_iter N overrides everything (manual pin). --force_fresh bypasses
# the stale-fresh safety guard that otherwise refuses to clobber a
# non-empty workspace from iter 1.
AUTO_RESUME=1
FORCE_FRESH=0
# #258 refinement: set to 1 by run_chain.sh ONLY on the resolve_start_iter
# branch where the inspector actually computed START_ITER. build_app_args
# then forwards --auto_resume, letting run_one_iteration.py replace a
# failed/no_records same-iteration manifest through the explicit
# replacement path (previous manifest kept, provenance recorded). Never
# set for a manual --start_iter pin or --no_auto_resume.
AUTO_RESUME_RECOVERY=0
# Force the LAST round of each iteration to be a FORMAL training run
# (full dataset, no --trial_portion clamp). Default ON to preserve the
# pre-existing chain behavior. Pass --no-force_formal_round in smoke /
# gate tests where all rounds should stay in trial mode — otherwise the
# last round uses the full training set and a 2-iter chain takes 2+
# hours instead of ~30-60 min. CLI flag exists on run_one_iteration.py
# (--force_formal_round / --no-force_formal_round); this wrapper-side
# forwarding closes the same bash-wrapper gap the lit-review flags hit.
FORCE_FORMAL_ROUND=1
# ml_literature_review enable flag (Risk 4 two-layer gate). THREE states
# (arXiv U3, #259): "" (default, unset) forwards nothing and the YAML's
# `enabled: false` keeps lit-review off — byte-identical to pre-lit-review
# chain argv; 1 (--ml_lit_review_enabled) forwards the positive flag; 0
# (--no-ml_lit_review_enabled, EXPLICIT) forwards the negative flag so the
# OFF arm of an experiment is recorded positively on the child argv rather
# than inherited from a YAML default. Closes the same bash-wrapper gap as
# --no-force_formal_round, originally surfaced during loss-inventory Gate 3.
ML_LIT_REVIEW_ENABLED=""
# Explicit task-composed Data Analysis override. Empty preserves the task
# composition; 1 and 0 forward the corresponding existing Python CLI flags.
DATA_ANALYSIS_ENABLED=""
# Optional task-owned literature-review config. Empty preserves the child's
# historical default; a supplied path is transported unchanged.
ML_LIT_REVIEW_CONFIG=""
# Workflow-owned evidence ordering. The runner's legacy default is omitted
# from child argv for compatibility; the alternative order must be transported.
SCIENTIFIC_EVIDENCE_ORDER="analysis_then_literature"
# arXiv U1 (#254) — opaque experiment-arm label. Empty = unlabelled (the
# legacy default); forwarded to run_one_iteration.py ONLY when set, so an
# unlabelled chain's child argv is byte-identical to pre-U1.
EXPERIMENT_ARM=""
# arXiv U3 (#260) — the WITHOUT arm's explicit isolation flag. Default 0
# forwards nothing; 1 forwards --baseline_isolation.
BASELINE_ISOLATION=0
ALLOWED_OUTPUT_TYPES=""
START_ITER=""

# --- Slurm-only defaults (ignored by lilab caller) ---
PARTITION="gpu-shared"
TIME="04:00:00"
MEM="48G"
GPUS=1
CPUS=8

parse_chain_args() {
    while [[ $# -gt 0 ]]; do
      case $1 in
        --workspace)              WORKSPACE="$2"; shift 2 ;;
        --run_name)               RUN_NAME="$2"; shift 2 ;;
        --num_iterations)         NUM_ITERATIONS="$2"; shift 2 ;;
        --seed_paths)
          shift
          while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
            SEED_PATHS+=("$1")
            shift
          done
          ;;
        --max_rounds)             MAX_ROUNDS="$2"; shift 2 ;;
        --max_epochs)             MAX_EPOCHS="$2"; shift 2 ;;
        --training_budget_reserve_fraction) TRAINING_BUDGET_RESERVE_FRACTION="$2"; shift 2 ;;
        --trial_max_epochs)       TRIAL_MAX_EPOCHS="$2"; shift 2 ;;
        --formal_max_epochs)      FORMAL_MAX_EPOCHS="$2"; shift 2 ;;
        --healthgate_mode)                    HEALTHGATE_MODE="$2"; shift 2 ;;
        --result_authority)                   RESULT_AUTHORITY="$2"; shift 2 ;;
        --skip_formal_min_delta)              SKIP_FORMAL_MIN_DELTA="$2"; shift 2 ;;
        --bypass_formal_time_budget_min_delta) BYPASS_FORMAL_TIME_BUDGET_MIN_DELTA="$2"; shift 2 ;;
        --bypass_formal_time_budget_minutes) BYPASS_FORMAL_TIME_BUDGET_MINUTES="$2"; shift 2 ;;
        --llm_model)              LLM_MODEL="$2"; shift 2 ;;
        --reflect_provider)       REFLECT_PROVIDER="$2"; shift 2 ;;
        --reflect_model_id)       REFLECT_MODEL_ID="$2"; shift 2 ;;
        --trial_portion)          TRIAL_PORTION="$2"; shift 2 ;;
        --train_portion)          TRAIN_PORTION="$2"; shift 2 ;;
        --eval_portion)           EVAL_PORTION="$2"; shift 2 ;;
        --human_advice_file)      HUMAN_ADVICE_FILE="$2"; shift 2 ;;
        --analysis_source_prompt) ANALYSIS_SOURCE_PROMPT="$2"; shift 2 ;;
        --advice)                 ADVICE="$2"; shift 2 ;;
        --advice_sha256)          ADVICE_SHA256="$2"; shift 2 ;;
        --plan_overrides)         PLAN_OVERRIDES="$2"; shift 2 ;;
        --workflow_parameter_rules) WORKFLOW_PARAMETER_RULES="$2"; shift 2 ;;
        --llm_config)             LLM_CONFIG="$2"; shift 2 ;;
        --required_runtime_profile_path) REQUIRED_RUNTIME_PROFILE_PATH="$2"; shift 2 ;;
        --required_runtime_profile) REQUIRED_RUNTIME_PROFILE="$2"; shift 2 ;;
        --required_runtime_profile_sha256) REQUIRED_RUNTIME_PROFILE_SHA256="$2"; shift 2 ;;
        --health_checks_config)   HEALTH_CHECKS_CONFIG="$2"; shift 2 ;;
        --task_composition)       TASK_COMPOSITION="$2"; shift 2 ;;
        --data_scope)             DATA_SCOPE="$2"; shift 2 ;;
        --health_gate_enabled)    HEALTH_GATE_ENABLED=1; shift ;;
        --no-health_gate_enabled) HEALTH_GATE_ENABLED=0; shift ;;
        --health_gate_files)      HEALTH_GATE_FILES="$2"; shift 2 ;;
        --data_dir)               DATA_DIR="$2"; shift 2 ;;
        --trial_time_budget_minutes) TRIAL_TIME_BUDGET_MINUTES="$2"; shift 2 ;;
        --formal_time_budget_minutes) FORMAL_TIME_BUDGET_MINUTES="$2"; shift 2 ;;
        --trial_time_admission_source) TRIAL_TIME_ADMISSION_SOURCE="$2"; shift 2 ;;
        --formal_time_admission_source) FORMAL_TIME_ADMISSION_SOURCE="$2"; shift 2 ;;
        --max_steps_per_attempt)  MAX_STEPS_PER_ATTEMPT="$2"; shift 2 ;;
        --min_formal_batch_size)  MIN_FORMAL_BATCH_SIZE="$2"; shift 2 ;;
        --allow_extreme_steps)    ALLOW_EXTREME_STEPS=1; shift ;;
        --runtime_watchdog)       RUNTIME_WATCHDOG=1; shift ;;
        --no-runtime_watchdog)    RUNTIME_WATCHDOG=0; shift ;;
        --execution_regime)       EXECUTION_REGIME="$2"; shift 2 ;;
        --enable_chain_incumbent_formal_gates) ENABLE_CHAIN_INCUMBENT_FORMAL_GATES=1; shift ;;
        --order_strategy_override) ORDER_STRATEGY_OVERRIDE="$2"; shift 2 ;;
        --file_order_override)     FILE_ORDER_OVERRIDE="$2"; shift 2 ;;
        --enable_structured_health_feedback) ENABLE_STRUCTURED_HEALTH_FEEDBACK=1; shift ;;
        --health_feedback_history_window_iterations) HEALTH_FEEDBACK_HISTORY_WINDOW_ITERATIONS="$2"; shift 2 ;;
        --health_feedback_history_max_entries_per_model) HEALTH_FEEDBACK_HISTORY_MAX_ENTRIES_PER_MODEL="$2"; shift 2 ;;
        --runtime_safety_factor)  RUNTIME_SAFETY_FACTOR="$2"; shift 2 ;;
        --runtime_trial_safety_factor)  RUNTIME_TRIAL_SAFETY_FACTOR="$2"; shift 2 ;;
        --runtime_formal_safety_factor) RUNTIME_FORMAL_SAFETY_FACTOR="$2"; shift 2 ;;
        --runtime_watchdog_safety_factor) RUNTIME_WATCHDOG_SAFETY_FACTOR="$2"; shift 2 ;;
        --runtime_watchdog_floor_seconds) RUNTIME_WATCHDOG_FLOOR_SECONDS="$2"; shift 2 ;;
        --runtime_verification_max_wall_seconds) RUNTIME_VERIFICATION_MAX_WALL_SECONDS="$2"; shift 2 ;;
        --formal_eval_portion)       FORMAL_EVAL_PORTION="$2"; shift 2 ;;
        --gpu_admission_measurement_source) GPU_ADMISSION_MEASUREMENT_SOURCE="$2"; shift 2 ;;
        --gpu_admission_enforcement) GPU_ADMISSION_ENFORCEMENT="$2"; shift 2 ;;
        --gpu_pair_ceiling_gib)   GPU_PAIR_CEILING_GIB="$2"; shift 2 ;;
        --trial_vram_budget_gb)   TRIAL_VRAM_BUDGET_GB="$2"; shift 2 ;;
        --formal_vram_budget_gb)  FORMAL_VRAM_BUDGET_GB="$2"; shift 2 ;;
        --vram_probe_step_timeout_seconds) VRAM_PROBE_STEP_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --vram_preflight_total_timeout_seconds) VRAM_PREFLIGHT_TOTAL_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --vram_preflight_host_memory_limit_gb) VRAM_PREFLIGHT_HOST_MEMORY_LIMIT_GB="$2"; shift 2 ;;
        --exploration_mode)       EXPLORATION_MODE="$2"; shift 2 ;;
        --minimum_boldness)       MINIMUM_BOLDNESS="$2"; shift 2 ;;
        --mode)                   MODE="$2"; shift 2 ;;
        --dry-run|--dry_run)      DRY_RUN=1; shift ;;
        --auto_resume)            AUTO_RESUME=1; shift ;;
        --no_auto_resume)         AUTO_RESUME=0; shift ;;
        --force_fresh)            FORCE_FRESH=1; shift ;;
        --force_formal_round)     FORCE_FORMAL_ROUND=1; shift ;;
        --no-force_formal_round)  FORCE_FORMAL_ROUND=0; shift ;;
        --ml_lit_review_enabled)     ML_LIT_REVIEW_ENABLED=1; shift ;;
        --no-ml_lit_review_enabled)  ML_LIT_REVIEW_ENABLED=0; shift ;;
        --data_analysis_enabled)     DATA_ANALYSIS_ENABLED=1; shift ;;
        --no-data_analysis_enabled)  DATA_ANALYSIS_ENABLED=0; shift ;;
        --ml_lit_review_config)      ML_LIT_REVIEW_CONFIG="$2"; shift 2 ;;
        --scientific_evidence_order)
            case "${2:-}" in
                analysis_then_literature|literature_then_analysis)
                    SCIENTIFIC_EVIDENCE_ORDER="$2"; shift 2 ;;
                *) echo "Invalid --scientific_evidence_order: ${2:-<missing>}" >&2; exit 1 ;;
            esac ;;
        --experiment_arm)         EXPERIMENT_ARM="$2"; shift 2 ;;
        --baseline_isolation)     BASELINE_ISOLATION=1; shift ;;
        --allowed_output_types)   ALLOWED_OUTPUT_TYPES="$2"; shift 2 ;;
        --start_iter)             START_ITER="$2"; shift 2 ;;
        # §3.2 — Adaptive-tuning brakes
        --attempts_per_round)        ATTEMPTS_PER_ROUND="$2"; shift 2 ;;
        --attempts_per_formal_round) ATTEMPTS_PER_FORMAL_ROUND="$2"; shift 2 ;;
        --max_fail_rounds)           MAX_FAIL_ROUNDS="$2"; shift 2 ;;
        # §3.2 — Propose→Implement retry brakes (13.C-bis)
        --max_proposal_attempts)     MAX_PROPOSAL_ATTEMPTS="$2"; shift 2 ;;
        --max_impl_attempts)         MAX_IMPL_ATTEMPTS="$2"; shift 2 ;;
        # VALIDATION POSTURE ONLY (V20 FU-D-11) — bypasses the proposer.
        --validation_fixed_candidate_plan) VALIDATION_FIXED_CANDIDATE_PLAN="$2"; shift 2 ;;
        --validation_max_portion)          VALIDATION_MAX_PORTION="$2"; shift 2 ;;
        --validation_max_train_samples)    VALIDATION_MAX_TRAIN_SAMPLES="$2"; shift 2 ;;
        --validation_max_samples)          VALIDATION_MAX_SAMPLES="$2"; shift 2 ;;
        --validation_max_phase_seconds)    VALIDATION_MAX_PHASE_SECONDS="$2"; shift 2 ;;
        # §3.2 — Trial / formal strategy + formal-scope (13.C-bis)
        --trial_strategy)            TRIAL_STRATEGY="$2"; shift 2 ;;
        --formal_strategy)           FORMAL_STRATEGY="$2"; shift 2 ;;
        --formal_training_scope_source) FORMAL_TRAINING_SCOPE_SOURCE="$2"; shift 2 ;;
        --formal_portion)            FORMAL_PORTION="$2"; shift 2 ;;
        --formal_train_portion)      FORMAL_TRAIN_PORTION="$2"; shift 2 ;;
        --formal_round_strategy)     FORMAL_ROUND_STRATEGY="$2"; shift 2 ;;
        --degenerate_penalty_score) DEGENERATE_PENALTY_SCORE="$2"; shift 2 ;;
        # §3.2 — Data slicing / reproducibility (13.C-bis)
        --target_files)
          # Mirrors --seed_paths: greedy slurp of positional ints until next --flag.
          shift
          while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
            TARGET_FILES+=("$1")
            shift
          done
          ;;
        --sampling_seed)             SAMPLING_SEED="$2"; shift 2 ;;
        # §3.2 — Debugging
        --debug_dump_prompts)        DEBUG_DUMP_PROMPTS=1; shift ;;
        # Stage 3 / Commit 4.5 — pseudo-mode flags
        --is_pseudo_llm)             IS_PSEUDO_LLM=1; shift ;;
        --is_pseudo_training)        IS_PSEUDO_TRAINING=1; shift ;;
        # Stage 4 / Commit 4.6 — consecutive-iter failure brake
        --max_failed_iterations)     MAX_FAILED_ITERATIONS="$2"; shift 2 ;;
        # R-RETENTION-1 — formal-deliverable retention (campaign entrypoint).
        --cleanup_denoised)
          if [ "$OUTPUT_RETENTION_REQUEST" = "retain" ]; then
              echo "ERROR: --cleanup_denoised conflicts with output retention" >&2; return 2
          fi
          OUTPUT_RETENTION_REQUEST="retire"; CLEANUP_DENOISED=1; shift ;;
        --no-cleanup_denoised|--retain_model_outputs)
          if [ "$OUTPUT_RETENTION_REQUEST" = "retire" ]; then
              echo "ERROR: output retention conflicts with --cleanup_denoised" >&2; return 2
          fi
          OUTPUT_RETENTION_REQUEST="retain"; CLEANUP_DENOISED=0; shift ;;
        --retain_training_checkpoints)
          RETAIN_TRAINING_CHECKPOINTS=1; shift ;;
        # Slurm-only flags — silently accepted on lilab too (ignored)
        --partition)              PARTITION="$2"; shift 2 ;;
        --time)                   TIME="$2"; shift 2 ;;
        --mem)                    MEM="$2"; shift 2 ;;
        --gpus)                   GPUS="$2"; shift 2 ;;
        --cpus)                   CPUS="$2"; shift 2 ;;
        *)                        echo "Unknown arg: $1" >&2; exit 1 ;;
      esac
    done

    if [ -z "$WORKSPACE" ] || [ -z "$RUN_NAME" ]; then
        echo "Required: --workspace, --run_name" >&2
        exit 1
    fi
    # --seed_paths is optional: an empty list is a valid cold start (no prior
    # experimental evidence). build_app_args omits --seed_paths entirely when
    # SEED_PATHS is empty so run_one_iteration.py falls back to its cold-start
    # default. A bare --seed_paths with zero values remains an argparse error.
}

load_advice_file() {
    # Validate that the human advice file exists (if provided).
    # The JSON is passed as a path to run_one_iteration.py, which loads
    # and decomposes it into per-agent fields. No shell-side expansion needed.
    if [ -z "$HUMAN_ADVICE_FILE" ]; then
        return 0
    fi
    if [ ! -f "$HUMAN_ADVICE_FILE" ]; then
        echo "Human advice file not found: $HUMAN_ADVICE_FILE" >&2
        exit 1
    fi
    echo "Human advice file: $HUMAN_ADVICE_FILE (validated)"
}

# Build the source-path list for iteration $1.
# With restore_prior_state (Commit 7) handling prior iters, the shell
# passes only seeds. The Python-side restore prepends prior outputs.
build_source_paths() {
    local iter=$1
    SOURCE_PATHS=("${SEED_PATHS[@]}")
}

# Build the APP_ARGS array (run_one_iteration.py CLI) for iteration $1.
# SOURCE_PATHS must already be populated.
build_app_args() {
    local iter=$1
    APP_ARGS=(
        --workspace "$WORKSPACE"
        --run_name "$RUN_NAME"
        --start_iteration "$iter"
        --max_rounds "$MAX_ROUNDS"
        --max_epochs "$MAX_EPOCHS"
        # D-BUD-6 — forwarded only when TYPED (empty == omit == the
        # Python default None == the mode-agnostic MAX_EPOCHS governs
        # that role), so an unset pair reproduces the legacy child argv.
        ${TRAINING_BUDGET_RESERVE_FRACTION:+--training_budget_reserve_fraction "$TRAINING_BUDGET_RESERVE_FRACTION"}
        ${TRIAL_MAX_EPOCHS:+--trial_max_epochs "$TRIAL_MAX_EPOCHS"}
        ${FORMAL_MAX_EPOCHS:+--formal_max_epochs "$FORMAL_MAX_EPOCHS"}
        --healthgate_mode "$HEALTHGATE_MODE"
        --result_authority "$RESULT_AUTHORITY"
        --skip_formal_min_delta "$SKIP_FORMAL_MIN_DELTA"
        --bypass_formal_time_budget_min_delta "$BYPASS_FORMAL_TIME_BUDGET_MIN_DELTA"
        ${BYPASS_FORMAL_TIME_BUDGET_MINUTES:+--bypass_formal_time_budget_minutes "$BYPASS_FORMAL_TIME_BUDGET_MINUTES"}
        --llm_model "$LLM_MODEL"
        # Lane F2 — forwarded only when TYPED (empty == omit == the
        # Python tri-state's None == AGENT_CONTROLLED).
        ${TRIAL_PORTION:+--trial_portion "$TRIAL_PORTION"}
        ${TRAIN_PORTION:+--train_portion "$TRAIN_PORTION"}
        ${EVAL_PORTION:+--eval_portion "$EVAL_PORTION"}
        --exploration_mode "$EXPLORATION_MODE"
        --minimum_boldness "$MINIMUM_BOLDNESS"
        --attempts_per_round "$ATTEMPTS_PER_ROUND"
        --attempts_per_formal_round "$ATTEMPTS_PER_FORMAL_ROUND"
        --max_fail_rounds "$MAX_FAIL_ROUNDS"
        --max_proposal_attempts "$MAX_PROPOSAL_ATTEMPTS"
        --max_impl_attempts "$MAX_IMPL_ATTEMPTS"
        --max_failed_iterations "$MAX_FAILED_ITERATIONS"
        --formal_strategy "$FORMAL_STRATEGY"
        --formal_training_scope_source "$FORMAL_TRAINING_SCOPE_SOURCE"
        --formal_portion "$FORMAL_PORTION"
        --formal_train_portion "$FORMAL_TRAIN_PORTION"
        --formal_round_strategy "$FORMAL_ROUND_STRATEGY"
    )
    # One effective policy reaches the child. The legacy negative cleanup
    # spelling is translated into --retain_model_outputs, not dropped.
    if [ "$CLEANUP_DENOISED" -eq 1 ]; then
        APP_ARGS+=(--cleanup_denoised)
    else
        APP_ARGS+=(--retain_model_outputs)
    fi
    if [ "$RETAIN_TRAINING_CHECKPOINTS" -eq 1 ]; then
        APP_ARGS+=(--retain_training_checkpoints)
    fi
    # Emit --seed_paths only when seeds are actually supplied. Omitting the flag
    # (empty SEED_PATHS) is a valid cold start; a bare --seed_paths with zero
    # values would be an argparse error by design (see requirement 2).
    if [ ${#SEED_PATHS[@]} -gt 0 ]; then
        APP_ARGS+=(--seed_paths "${SEED_PATHS[@]}")
    fi
    if [[ -n "${VALIDATION_FIXED_CANDIDATE_PLAN:-}" ]]; then
        APP_ARGS+=(--validation_fixed_candidate_plan "$VALIDATION_FIXED_CANDIDATE_PLAN")
    fi
    if [[ -n "${VALIDATION_MAX_PORTION:-}" ]]; then
        APP_ARGS+=(--validation_max_portion "$VALIDATION_MAX_PORTION")
    fi
    if [[ -n "${VALIDATION_MAX_TRAIN_SAMPLES:-}" ]]; then
        APP_ARGS+=(--validation_max_train_samples "$VALIDATION_MAX_TRAIN_SAMPLES")
    fi
    if [[ -n "${VALIDATION_MAX_SAMPLES:-}" ]]; then
        APP_ARGS+=(--validation_max_samples "$VALIDATION_MAX_SAMPLES")
    fi
    if [[ -n "${VALIDATION_MAX_PHASE_SECONDS:-}" ]]; then
        APP_ARGS+=(--validation_max_phase_seconds "$VALIDATION_MAX_PHASE_SECONDS")
    fi
    if [ "$DEBUG_DUMP_PROMPTS" -eq 1 ]; then
        APP_ARGS+=(--debug_dump_prompts)
    fi
    # Stage 3 / Commit 4.5 — pseudo-mode flags
    if [ "$IS_PSEUDO_LLM" -eq 1 ]; then
        APP_ARGS+=(--is_pseudo_llm)
    fi
    if [ "$IS_PSEUDO_TRAINING" -eq 1 ]; then
        APP_ARGS+=(--is_pseudo_training)
    fi
    # DS7 — --trial_strategy / --target_files are deprecated no-ops: still
    # parsed (so existing invocations don't break) but no longer forwarded.
    if [ -n "$SAMPLING_SEED" ]; then
        APP_ARGS+=(--sampling_seed "$SAMPLING_SEED")
    fi
    if [ -n "$LLM_CONFIG" ]; then
        APP_ARGS+=(--llm_config "$LLM_CONFIG")
    fi
    # F-PROFILE-WIRE-1 — forwarded only when declared, so an undeclared
    # launch emits no new token and its child argv is byte-identical to
    # pre-#345. run_one_iteration.py refuses a half declaration by name.
    if [ -n "$REQUIRED_RUNTIME_PROFILE_PATH" ]; then
        APP_ARGS+=(--required_runtime_profile_path "$REQUIRED_RUNTIME_PROFILE_PATH")
    fi
    if [ -n "$REQUIRED_RUNTIME_PROFILE" ]; then
        APP_ARGS+=(--required_runtime_profile "$REQUIRED_RUNTIME_PROFILE")
    fi
    if [ -n "$REQUIRED_RUNTIME_PROFILE_SHA256" ]; then
        APP_ARGS+=(--required_runtime_profile_sha256 "$REQUIRED_RUNTIME_PROFILE_SHA256")
    fi
    if [ -n "$HEALTH_CHECKS_CONFIG" ]; then
        APP_ARGS+=(--health_checks_config "$HEALTH_CHECKS_CONFIG")
    fi
    # W1 — forwarded only when set, so an un-composed launch emits no new
    # token and its child argv is byte-identical to pre-Step-10.
    if [ -n "$TASK_COMPOSITION" ]; then
        APP_ARGS+=(--task_composition "$TASK_COMPOSITION")
    fi
    # DS6c — DataScope + HealthGate subsystem. HEALTH_GATE_ENABLED default 1
    # matches the Python default; only the disabling form is forwarded
    # (mirrors FORCE_FORMAL_ROUND).
    if [ -n "$DATA_SCOPE" ]; then
        APP_ARGS+=(--data_scope "$DATA_SCOPE")
    fi
    if [ "$HEALTH_GATE_ENABLED" -eq 0 ]; then
        APP_ARGS+=(--no-health_gate_enabled)
    fi
    if [ -n "$HEALTH_GATE_FILES" ]; then
        APP_ARGS+=(--health_gate_files "$HEALTH_GATE_FILES")
    fi
    if [ -n "$REFLECT_PROVIDER" ]; then
        APP_ARGS+=(--reflect_provider "$REFLECT_PROVIDER")
    fi
    if [ -n "$REFLECT_MODEL_ID" ]; then
        APP_ARGS+=(--reflect_model_id "$REFLECT_MODEL_ID")
    fi
    if [ -n "$ADVICE" ]; then
        APP_ARGS+=(--advice "$ADVICE")
    elif [ -n "$HUMAN_ADVICE_FILE" ]; then
        APP_ARGS+=(--human_advice_file "$HUMAN_ADVICE_FILE")
    fi
    # Emitted only when DECLARED, and independently of which advice flag
    # carried the path: --human_advice_file names an advice artifact too,
    # and a digest declared for it must reach the child.
    if [ -n "$ADVICE_SHA256" ]; then
        APP_ARGS+=(--advice_sha256 "$ADVICE_SHA256")
    fi
    if [ -n "$ANALYSIS_SOURCE_PROMPT" ]; then
        APP_ARGS+=(--analysis_source_prompt "$ANALYSIS_SOURCE_PROMPT")
    fi
    if [ -n "$PLAN_OVERRIDES" ]; then
        APP_ARGS+=(--plan_overrides "$PLAN_OVERRIDES")
    fi
    if [ -n "$WORKFLOW_PARAMETER_RULES" ]; then
        APP_ARGS+=(--workflow_parameter_rules "$WORKFLOW_PARAMETER_RULES")
    fi
    if [ -n "$DATA_DIR" ]; then
        APP_ARGS+=(--data_dir "$DATA_DIR")
    fi
    if [ -n "$TRIAL_TIME_BUDGET_MINUTES" ]; then
        APP_ARGS+=(--trial_time_budget_minutes "$TRIAL_TIME_BUDGET_MINUTES")
    fi
    if [ -n "$FORMAL_TIME_BUDGET_MINUTES" ]; then
        APP_ARGS+=(--formal_time_budget_minutes "$FORMAL_TIME_BUDGET_MINUTES")
    fi
    APP_ARGS+=(--trial_time_admission_source "$TRIAL_TIME_ADMISSION_SOURCE")
    APP_ARGS+=(--formal_time_admission_source "$FORMAL_TIME_ADMISSION_SOURCE")
    # RT6 runtime-control surface: numeric flags always cross explicitly.
    # The Formal-only batch floor defaults to 0 (disabled), preserving
    # Trial/Formal parity unless a task or campaign opts in.
    APP_ARGS+=(--max_steps_per_attempt "$MAX_STEPS_PER_ATTEMPT")
    APP_ARGS+=(--min_formal_batch_size "$MIN_FORMAL_BATCH_SIZE")
    APP_ARGS+=(--runtime_safety_factor "$RUNTIME_SAFETY_FACTOR")
    if [ -n "$RUNTIME_TRIAL_SAFETY_FACTOR" ]; then
        APP_ARGS+=(--runtime_trial_safety_factor "$RUNTIME_TRIAL_SAFETY_FACTOR")
    fi
    if [ -n "$RUNTIME_FORMAL_SAFETY_FACTOR" ]; then
        APP_ARGS+=(--runtime_formal_safety_factor "$RUNTIME_FORMAL_SAFETY_FACTOR")
    fi
    if [ -n "$RUNTIME_WATCHDOG_SAFETY_FACTOR" ]; then
        APP_ARGS+=(--runtime_watchdog_safety_factor "$RUNTIME_WATCHDOG_SAFETY_FACTOR")
    fi
    # arXiv #261 — floor forwarded only when explicitly set, so an unset
    # chain launch reaches the Python tri-state (profile floor) instead of
    # pinning the legacy 60.0 as a field-level override.
    if [ -n "$RUNTIME_WATCHDOG_FLOOR_SECONDS" ]; then
        APP_ARGS+=(--runtime_watchdog_floor_seconds "$RUNTIME_WATCHDOG_FLOOR_SECONDS")
    fi
    if [ -n "$RUNTIME_VERIFICATION_MAX_WALL_SECONDS" ]; then
        APP_ARGS+=(--runtime_verification_max_wall_seconds "$RUNTIME_VERIFICATION_MAX_WALL_SECONDS")
    fi
    if [ "$ALLOW_EXTREME_STEPS" -eq 1 ]; then
        APP_ARGS+=(--allow_extreme_steps)
    fi
    # arXiv #261 tri-state: 1 -> explicit on, 0 -> explicit off, empty ->
    # neither flag, the (device, regime) runtime profile decides in Python.
    if [ "$RUNTIME_WATCHDOG" = "1" ]; then
        APP_ARGS+=(--runtime_watchdog)
    elif [ "$RUNTIME_WATCHDOG" = "0" ]; then
        APP_ARGS+=(--no-runtime_watchdog)
    fi
    if [ -n "$EXECUTION_REGIME" ]; then
        APP_ARGS+=(--execution_regime "$EXECUTION_REGIME")
    fi
    # V19 PR 1 — consumption-only gate coupling (default OFF; forwarded
    # only when explicitly enabled, matching Python argparse store_true).
    if [ "$ENABLE_CHAIN_INCUMBENT_FORMAL_GATES" -eq 1 ]; then
        APP_ARGS+=(--enable_chain_incumbent_formal_gates)
    fi
    # V19 PR 2 — operator ordering override (default: omit, so the agent's
    # proposal decides and 'shuffle' applies when it proposes nothing).
    # Forwarded only when set, so an unset override reproduces pre-V19 argv.
    if [ -n "$ORDER_STRATEGY_OVERRIDE" ]; then
        APP_ARGS+=(--order_strategy_override "$ORDER_STRATEGY_OVERRIDE")
    fi
    if [ -n "$FILE_ORDER_OVERRIDE" ]; then
        APP_ARGS+=(--file_order_override "$FILE_ORDER_OVERRIDE")
    fi
    # V19 PR 3 — structured-health-feedback policy (default: omit, so
    # Python argparse defaults OFF/3/8 apply and pre-PR3 argv is
    # reproduced byte-identically when unset).
    if [ "$ENABLE_STRUCTURED_HEALTH_FEEDBACK" -eq 1 ]; then
        APP_ARGS+=(--enable_structured_health_feedback)
    fi
    if [ -n "$HEALTH_FEEDBACK_HISTORY_WINDOW_ITERATIONS" ]; then
        APP_ARGS+=(--health_feedback_history_window_iterations "$HEALTH_FEEDBACK_HISTORY_WINDOW_ITERATIONS")
    fi
    if [ -n "$HEALTH_FEEDBACK_HISTORY_MAX_ENTRIES_PER_MODEL" ]; then
        APP_ARGS+=(--health_feedback_history_max_entries_per_model "$HEALTH_FEEDBACK_HISTORY_MAX_ENTRIES_PER_MODEL")
    fi
    # FORCE_FORMAL_ROUND default 1 preserves prior chain behavior; only forward
    # the negation explicitly when set to 0 (run_one_iteration.py's argparse
    # default is True, so omitting the flag keeps formal forcing on).
    if [ "$FORCE_FORMAL_ROUND" -eq 0 ]; then
        APP_ARGS+=(--no-force_formal_round)
    fi
    # ML_LIT_REVIEW_ENABLED: "" (unset) forwards nothing and
    # run_one_iteration.py reads the YAML; 1 forwards the positive flag; an
    # EXPLICIT 0 forwards the negative flag (arXiv U3 — the OFF arm is stated
    # on the child argv, never inherited silently).
    if [ "$ML_LIT_REVIEW_ENABLED" = "1" ]; then
        APP_ARGS+=(--ml_lit_review_enabled)
    elif [ "$ML_LIT_REVIEW_ENABLED" = "0" ]; then
        APP_ARGS+=(--no-ml_lit_review_enabled)
    fi
    if [ -n "$ML_LIT_REVIEW_CONFIG" ]; then
        APP_ARGS+=(--ml_lit_review_config "$ML_LIT_REVIEW_CONFIG")
    fi
    if [ "$DATA_ANALYSIS_ENABLED" = "1" ]; then
        APP_ARGS+=(--data_analysis_enabled)
    elif [ "$DATA_ANALYSIS_ENABLED" = "0" ]; then
        APP_ARGS+=(--no-data_analysis_enabled)
    fi
    if [ "$SCIENTIFIC_EVIDENCE_ORDER" != "analysis_then_literature" ]; then
        APP_ARGS+=(--scientific_evidence_order "$SCIENTIFIC_EVIDENCE_ORDER")
    fi
    # arXiv U1 — the arm label is forwarded only when set (unlabelled chains
    # reproduce pre-U1 argv byte-identically).
    if [ -n "$EXPERIMENT_ARM" ]; then
        APP_ARGS+=(--experiment_arm "$EXPERIMENT_ARM")
    fi
    # arXiv U3 — isolation forwarded only when requested.
    if [ "$BASELINE_ISOLATION" -eq 1 ]; then
        APP_ARGS+=(--baseline_isolation)
    fi
    # arXiv #259 — output-type constraint forwarded only when declared.
    if [ -n "${ALLOWED_OUTPUT_TYPES:-}" ]; then
        APP_ARGS+=(--allowed_output_types "$ALLOWED_OUTPUT_TYPES")
    fi
    # #258 refinement: forward auto-resume recovery intent only when the
    # inspector computed START_ITER (run_chain.sh sets the variable on that
    # branch alone). The Python launcher then replaces a failed/no_records
    # same-iteration manifest through the explicit replacement path with
    # provenance; a completed manifest is never replaced by auto-resume.
    if [ "${AUTO_RESUME_RECOVERY:-0}" -eq 1 ]; then
        APP_ARGS+=(--auto_resume)
    fi
    APP_ARGS+=(--formal_eval_portion "$FORMAL_EVAL_PORTION")
    if [ -n "$GPU_ADMISSION_MEASUREMENT_SOURCE" ]; then
        APP_ARGS+=(--gpu_admission_measurement_source "$GPU_ADMISSION_MEASUREMENT_SOURCE")
    fi
    if [ -n "$GPU_ADMISSION_ENFORCEMENT" ]; then
        APP_ARGS+=(--gpu_admission_enforcement "$GPU_ADMISSION_ENFORCEMENT")
    fi
    if [ -n "$GPU_PAIR_CEILING_GIB" ]; then
        APP_ARGS+=(--gpu_pair_ceiling_gib "$GPU_PAIR_CEILING_GIB")
    fi
    if [ -n "$TRIAL_VRAM_BUDGET_GB" ]; then
        APP_ARGS+=(--trial_vram_budget_gb "$TRIAL_VRAM_BUDGET_GB")
    fi
    if [ -n "$FORMAL_VRAM_BUDGET_GB" ]; then
        APP_ARGS+=(--formal_vram_budget_gb "$FORMAL_VRAM_BUDGET_GB")
    fi
    APP_ARGS+=(--vram_probe_step_timeout_seconds "$VRAM_PROBE_STEP_TIMEOUT_SECONDS")
    APP_ARGS+=(--vram_preflight_total_timeout_seconds "$VRAM_PREFLIGHT_TOTAL_TIMEOUT_SECONDS")
    if [ -n "$VRAM_PREFLIGHT_HOST_MEMORY_LIMIT_GB" ]; then
        APP_ARGS+=(--vram_preflight_host_memory_limit_gb "$VRAM_PREFLIGHT_HOST_MEMORY_LIMIT_GB")
    fi
    if [ -n "$DEGENERATE_PENALTY_SCORE" ]; then
        APP_ARGS+=(--degenerate_penalty_score "$DEGENERATE_PENALTY_SCORE")
    fi
}

print_chain_header() {
    local label=$1
    if [ "$DRY_RUN" -eq 1 ]; then
        label="${label} [DRY-RUN]"
    fi
    echo "############################################################"
    echo "  SIDERIUS Iteration Chain — ${label}"
    echo "  Workspace        : $WORKSPACE"
    echo "  Num iterations   : $NUM_ITERATIONS"
    echo "  Seed paths       : ${#SEED_PATHS[@]} files"
    local p
    for p in "${SEED_PATHS[@]}"; do
        echo "    - $p"
    done
    echo "  Max rounds       : $MAX_ROUNDS"
    echo "  Max epochs       : $MAX_EPOCHS"
    echo "  Skip formal Δ    : $SKIP_FORMAL_MIN_DELTA"
    echo "  Bypass time Δ    : $BYPASS_FORMAL_TIME_BUDGET_MIN_DELTA"
    echo "  LLM model        : $LLM_MODEL"
    if [ -n "$LLM_CONFIG" ]; then
        echo "  LLM config       : $LLM_CONFIG"
    fi
    echo "  HealthGate config: ${HEALTH_CHECKS_CONFIG:-(shipped default)}"
    echo "  Task composition : ${TASK_COMPOSITION:-(missing)}"
    echo "  Required profile : ${REQUIRED_RUNTIME_PROFILE:-(none — measured > shipped > uncalibrated ladder)}${REQUIRED_RUNTIME_PROFILE:+ sha256=${REQUIRED_RUNTIME_PROFILE_SHA256:-(unset)} artifact=${REQUIRED_RUNTIME_PROFILE_PATH:-(unset)}}"
    echo "  Data scope       : ${DATA_SCOPE:-(complete dataset)}"
    echo "  HealthGate       : enabled=$HEALTH_GATE_ENABLED monitored=${HEALTH_GATE_FILES:-(YAML defaults)}"
    if [ -n "$MODE" ]; then
        echo "  Mode             : $MODE"
    fi
    if [ -n "${START_ITER:-}" ]; then
        echo "  Start iter       : $START_ITER  (auto_resume=$AUTO_RESUME, force_fresh=$FORCE_FRESH)"
    fi
    # --- §3.2 plan flags (input contract) ---
    echo "  §3.2 plan flags:"
    echo "    Data dir       : $DATA_DIR"
    echo "    Trial portion  : ${TRIAL_PORTION:-AGENT_CONTROLLED}"
    echo "    Train portion  : ${TRAIN_PORTION:-AGENT_CONTROLLED}"
    echo "    Eval portion   : ${EVAL_PORTION:-AGENT_CONTROLLED}"
    echo "    Exploration    : $EXPLORATION_MODE  (boldness>=$MINIMUM_BOLDNESS)"
    echo "    Round attempts : trial=$ATTEMPTS_PER_ROUND, formal=$ATTEMPTS_PER_FORMAL_ROUND, max_fail_rounds=$MAX_FAIL_ROUNDS"
    echo "    Propose retry  : max_proposal_attempts=$MAX_PROPOSAL_ATTEMPTS, max_impl_attempts=$MAX_IMPL_ATTEMPTS"
    echo "    Chain brake    : max_failed_iterations=$MAX_FAILED_ITERATIONS  (halt on streak of failed iter manifests)"
    echo "    Trial strategy : $TRIAL_STRATEGY"
    echo "    Formal scope   : source=$FORMAL_TRAINING_SCOPE_SOURCE, strategy=$FORMAL_STRATEGY, operator_portion=$FORMAL_PORTION, operator_train_portion=$FORMAL_TRAIN_PORTION"
    echo "    Formal round   : policy=$FORMAL_ROUND_STRATEGY"
    echo "    Degen reaction : penalty=${DEGENERATE_PENALTY_SCORE:-(null score on collapse)}"
    if [ ${#TARGET_FILES[@]} -gt 0 ]; then
        echo "    Target files   : ${TARGET_FILES[*]}"
    fi
    if [ -n "$SAMPLING_SEED" ]; then
        echo "    Sampling seed  : $SAMPLING_SEED"
    fi
    if [ "$DEBUG_DUMP_PROMPTS" -eq 1 ]; then
        echo "    Debug dump     : ON (--debug_dump_prompts)"
    else
        echo "    Debug dump     : off"
    fi
    # Stage 3 / Commit 4.5 — Pseudo-mode (always-print: forensic visibility for dry-runs)
    if [ "$IS_PSEUDO_LLM" -eq 1 ] || [ "$IS_PSEUDO_TRAINING" -eq 1 ]; then
        local _llm="off"
        local _train="off"
        [ "$IS_PSEUDO_LLM" -eq 1 ] && _llm="ON"
        [ "$IS_PSEUDO_TRAINING" -eq 1 ] && _train="ON"
        echo "    Pseudo-mode    : llm=$_llm, training=$_train  (\$0-cost smoke)"
    else
        echo "    Pseudo-mode    : off (production)"
    fi
    if [ -n "$TRIAL_TIME_BUDGET_MINUTES" ] || [ -n "$FORMAL_TIME_BUDGET_MINUTES" ]; then
        echo "    Time budgets   : trial=${TRIAL_TIME_BUDGET_MINUTES:-(none)}min (${TRIAL_TIME_ADMISSION_SOURCE}), formal=${FORMAL_TIME_BUDGET_MINUTES:-(none)}min (${FORMAL_TIME_ADMISSION_SOURCE}), eval_portion=$FORMAL_EVAL_PORTION"
    fi
    if [ -n "$TRIAL_VRAM_BUDGET_GB" ] || [ -n "$FORMAL_VRAM_BUDGET_GB" ]; then
        echo "    VRAM budgets   : trial=${TRIAL_VRAM_BUDGET_GB:-(auto)}GB, formal=${FORMAL_VRAM_BUDGET_GB:-(auto)}GB"
    fi
    if [ -n "$ADVICE" ]; then
        echo "    Advice file    : $ADVICE"
    elif [ -n "$HUMAN_ADVICE_FILE" ]; then
        echo "    Advice file    : $HUMAN_ADVICE_FILE  (legacy --human_advice_file)"
    fi
    if [ -n "$ADVICE_SHA256" ]; then
        echo "    Advice sha256  : $ADVICE_SHA256  (declared; certified against the bytes read)"
    fi
    if [ "$MODE" = "lilab" ] && [ "${#PY_CMD[@]}" -gt 0 ]; then
        echo "  Python           : ${PY_CMD[*]}  (source: ${PY_SOURCE:-?})"
    fi
    if [ "$MODE" = "sdsc" ]; then
        echo "  Slurm partition  : $PARTITION"
        echo "  Slurm time       : $TIME"
        echo "  Slurm mem        : $MEM"
        echo "  Slurm gpus       : $GPUS"
        echo "  Slurm cpus       : $CPUS"
    fi
    echo "############################################################"
}

# --- C13: operator-stop semantics ------------------------------------------
# CONFIRMED defect (V19 wave-1 stop, §15): killing the iteration Python
# only ended ONE CHILD. The loop below then walked straight on and
# respawned iteration 2. An operator stop must end the CHAIN LOOP.
#
# Two independent stop channels, because the two real situations differ:
#
#   * a stop FILE   — "stop after the current iteration", the graceful
#                     request an operator can make without touching a
#                     running process;
#   * a SIGNAL      — TERM/INT/HUP to this script, or a signal-terminated
#                     iteration child (exit >= 128), i.e. the chain was
#                     killed from outside.
#
# Either way the loop stops, a stopped-chain record is written, and no
# further iteration is started. Ordinary in-chain failures are NOT
# affected: a non-zero iteration that was not signalled keeps the frozen
# continuation behaviour, because the no-respawn rule is scoped to an
# OPERATOR-DIRECTED stop.

#: Exit code for a chain that stopped on request rather than finishing.
CHAIN_STOP_EXIT_CODE=99
#: Set by the trap handler to the signal name that arrived.
CHAIN_STOP_SIGNAL=""

chain_stop_file() {
    echo "${CHAIN_STOP_FILE:-${WORKSPACE}/STOP}"
}

# Record the signal and let the loop stop at its next checkpoint, rather
# than dying mid-iteration and leaving no record of why.
_chain_note_signal() {
    CHAIN_STOP_SIGNAL="$1"
    echo "" >&2
    echo "[chain] $1 received — stopping the chain loop after the current iteration" >&2
}

install_chain_stop_traps() {
    trap '_chain_note_signal SIGTERM' TERM
    trap '_chain_note_signal SIGINT'  INT
    trap '_chain_note_signal SIGHUP'  HUP
}

chain_stop_requested() {
    [ -n "$CHAIN_STOP_SIGNAL" ] && return 0
    [ -e "$(chain_stop_file)" ] && return 0
    return 1
}

# The explicit stopped-wave state record. Written on EVERY stop path, so
# "why did this chain end early" is never reconstructed from log text.
record_chain_stop() {  # reason iteration detail
    local reason="$1" iteration="$2" detail="${3:-}"
    local path="${WORKSPACE}/chain_stopped.json"
    [ "$DRY_RUN" -eq 1 ] && return 0
    mkdir -p "$WORKSPACE" 2>/dev/null
    printf '{"stopped": true, "reason": "%s", "signal": "%s", "stopped_before_iteration": %s, "iterations_planned": %s, "run_name": "%s", "workspace": "%s", "chain_pid": %s, "stopped_at": "%s", "detail": "%s", "respawn": false}\n' \
        "$reason" "${CHAIN_STOP_SIGNAL:-none}" "$iteration" "$NUM_ITERATIONS" \
        "${RUN_NAME:-unknown}" "$WORKSPACE" "$$" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$detail" > "$path"
    echo ""
    echo "############################################################"
    echo "  CHAIN STOPPED — $reason"
    echo "  stopped before iteration $iteration of $NUM_ITERATIONS"
    echo "  no further iteration will be started (no respawn)"
    echo "  state record: $path"
    echo "############################################################"
}

#: Exit code for a chain whose loop ran to the end with at least one
#: FAILED iteration. Distinct from 0 (every iteration succeeded), from 3
#: (an infrastructure abort halted the chain), and from
#: CHAIN_STOP_EXIT_CODE (an operator stop).
CHAIN_ITERATION_FAILED_EXIT_CODE=1
#: Exit code an iteration uses to demand the CHAIN halt — the `.chain_halted`
#: sentinel's companion (see run_one_iteration.py and C9c).
CHAIN_HALT_EXIT_CODE=3
#: Iterations whose child exited non-zero, as "ITER:STATUS" entries. The
#: chain's terminal status is derived from this, never from log text.
CHAIN_FAILED_ITERATIONS=()

# Run all iterations. The caller must have defined a `submit_iteration`
# function that takes the iteration number and uses the populated
# SOURCE_PATHS and APP_ARGS arrays.
#
# Returns 0 when every iteration succeeded; CHAIN_HALT_EXIT_CODE when an
# iteration demanded a halt; the child's status when a signal ended it;
# CHAIN_STOP_EXIT_CODE when an operator stop ended the loop early; and
# CHAIN_ITERATION_FAILED_EXIT_CODE when the loop ran to the end but an
# iteration failed.
#
# FAILURE HONESTY (2026-08-26). Until this was fixed the loop captured each
# child's status, tested it ONLY for `>= 128`, and then returned 0 — so a
# chain whose every iteration crashed reported success to its caller, and
# fleet automation gating on `$?` recorded a failed chain as a pass. The
# CONTINUATION behaviour below is deliberately unchanged: an ordinary
# non-zero iteration still does not stop the chain (the no-respawn rule is
# scoped to an OPERATOR-DIRECTED stop, and a later iteration can still make
# progress from an earlier seed). What changed is only what the chain
# REPORTS about itself.
run_chain() {
    if [ "$DRY_RUN" -ne 1 ]; then
        mkdir -p "$WORKSPACE"
    fi
    install_chain_stop_traps
    CHAIN_FAILED_ITERATIONS=()
    local ITER
    local first="${START_ITER:-1}"
    for ITER in $(seq "$first" "$NUM_ITERATIONS"); do
        # Checked BEFORE the iteration is built, so a stop requested while
        # the previous iteration ran costs nothing further.
        if chain_stop_requested; then
            record_chain_stop "operator_stop_requested" "$ITER" \
                "stop observed before iteration $ITER was started"
            return "$CHAIN_STOP_EXIT_CODE"
        fi

        build_source_paths "$ITER"
        build_app_args "$ITER"

        echo ""
        echo "############################################################"
        echo "  Iteration $ITER / $NUM_ITERATIONS"
        echo "  Source paths: ${#SOURCE_PATHS[@]} entries"
        local p
        for p in "${SOURCE_PATHS[@]}"; do
            echo "    - $p"
        done
        echo "############################################################"

        local status=0
        submit_iteration "$ITER" || status=$?

        if [ "$status" -ne 0 ]; then
            CHAIN_FAILED_ITERATIONS+=("${ITER}:${status}")
            echo "[chain] iteration $ITER FAILED (exit $status)" >&2
        fi

        if chain_stop_requested; then
            record_chain_stop "operator_stop_requested" "$((ITER + 1))" \
                "stop observed after iteration $ITER (iteration exit $status)"
            return "$CHAIN_STOP_EXIT_CODE"
        fi
        # A child terminated by a signal is an EXTERNAL stop, whatever
        # sent it — this is the exact wave-1 case, where killing the
        # iteration Python used to let the loop respawn iteration 2.
        if [ "$status" -ge 128 ]; then
            CHAIN_STOP_SIGNAL="child_signal_$((status - 128))"
            record_chain_stop "iteration_terminated_by_signal" "$((ITER + 1))" \
                "iteration $ITER exited $status (128 + signal $((status - 128)))"
            return "$status"
        fi
        # An INFRASTRUCTURE ABORT (C9c): the iteration wrote
        # `.chain_halted` and exited 3 precisely to stop this loop. The
        # sentinel alone was doing the work — every later child read it and
        # refused at startup — so the halt was real but the loop kept
        # spawning children and the chain still called itself complete.
        if [ "$status" -eq "$CHAIN_HALT_EXIT_CODE" ]; then
            record_chain_stop "iteration_infrastructure_abort" "$((ITER + 1))" \
                "iteration $ITER demanded a chain halt (exit $status)"
            return "$status"
        fi
    done
    if [ "${#CHAIN_FAILED_ITERATIONS[@]}" -gt 0 ]; then
        return "$CHAIN_ITERATION_FAILED_EXIT_CODE"
    fi
    return 0
}

#: The ONLY manifest status that means the iteration produced an
#: authoritative result. Everything else — `no_records`, `failed`, an
#: unrecognised value, an unreadable file — is NOT completed. Fail closed:
#: a status this code has never heard of is never added to a success list.
CHAIN_COMPLETED_STATUS="completed"

# One iteration manifest's status, or empty when it cannot be read.
#
# The manifest is written by `core/iteration_manifest.py` with
# `json.dumps(..., indent=2)` and no `sort_keys`, and `status` is the first
# key every writer inserts, so the FIRST `"status": "..."` in the file is
# the top-level one. Compact single-line manifests parse identically.
_manifest_status() {  # path -> status on stdout, empty if unreadable
    grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' "$1" 2>/dev/null \
        | head -1 \
        | sed 's/.*:[[:space:]]*"\([^"]*\)"$/\1/'
}

# The chain's terminal verdict, derived from ARTIFACTS and child statuses.
#
# Lives here, not in the entry script, so it is reachable by a test that
# sources this library — the summary block it replaces sat past the last
# `exit` in run_chain.sh, where the script simply ran off the end and
# returned 0 no matter what it had just printed.
#
# EXISTENCE IS NOT A VERDICT (F-Q4-1). This used to test `-f "$MANIFEST"`
# and nothing else. `run_one_iteration.py` writes a `no_records` manifest
# and DELIBERATELY exits 0 on gate exhaustion (so the chain may continue
# and the next iteration's LLM can adapt), which means neither half of the
# old clean verdict could ever see it: the file existed, and the child's
# exit status was 0. A chain whose every iteration exhausted its gates
# trained nothing, scored nothing, printed CHAIN COMPLETE and exited 0 —
# and an external scheduler read `EXIT=0`, resolved `DISPOSITION=complete`
# and advanced the campaign wave.
#
# `no_records` is a DESIGNED chainable state, not a crash, so it is not
# treated as a failure on its own. The rules:
#
#   * every iteration non-`completed`  -> MUST NOT exit 0. The chain
#     produced no authoritative result and the queue should stop.
#   * a MIXED chain -> MAY exit 0, because it did produce authoritative
#     results — but the banner MUST NAME the non-completed iterations.
#     Silence there is the same lie one level quieter.
#   * an unknown or unreadable status -> counted as non-completed.
#
# Returns 0 only when no manifest is missing, no child failed, and at
# least one iteration reached `completed`.
report_chain_outcome() {
    local ITER MANIFEST STATUS
    local missing=0
    local completed=0
    local lines=()
    local not_completed=()
    # Decide FIRST, announce second: the banner must not contradict the
    # evidence printed under it.
    for ITER in $(seq 1 "$NUM_ITERATIONS"); do
        MANIFEST=$(printf "${WORKSPACE}/iter_%03d/manifest.json" "$ITER")
        if [ ! -f "$MANIFEST" ]; then
            lines+=("  iter $ITER → MISSING")
            missing=$((missing + 1))
            not_completed+=("${ITER}:missing")
            continue
        fi
        STATUS="$(_manifest_status "$MANIFEST")"
        [ -n "$STATUS" ] || STATUS="unreadable"
        # The status is on the line so a reader never has to open the file
        # to learn what the iteration actually did.
        lines+=("  iter $ITER → $MANIFEST [$STATUS]")
        if [ "$STATUS" = "$CHAIN_COMPLETED_STATUS" ]; then
            completed=$((completed + 1))
        else
            not_completed+=("${ITER}:${STATUS}")
        fi
    done

    if [ "$missing" -eq 0 ] && [ "${#CHAIN_FAILED_ITERATIONS[@]}" -eq 0 ] \
        && [ "$completed" -gt 0 ]; then
        if [ "${#not_completed[@]}" -eq 0 ]; then
            echo "  CHAIN COMPLETE — ${NUM_ITERATIONS} iterations"
            printf '%s\n' "${lines[@]}"
        else
            echo "  CHAIN COMPLETE — ${NUM_ITERATIONS} iterations, ${completed} authoritative"
            printf '%s\n' "${lines[@]}"
            echo "    NO authoritative result (iter:status): ${not_completed[*]}"
        fi
        return 0
    fi

    echo "  CHAIN INCOMPLETE — ${NUM_ITERATIONS} iterations planned, did NOT finish cleanly"
    printf '%s\n' "${lines[@]}"
    if [ "${#CHAIN_FAILED_ITERATIONS[@]}" -gt 0 ]; then
        echo "    failed iterations (iter:exit):        ${CHAIN_FAILED_ITERATIONS[*]}"
    fi
    if [ "$missing" -gt 0 ]; then
        echo "    iterations with no manifest:          $missing of $NUM_ITERATIONS"
    fi
    if [ "${#not_completed[@]}" -gt 0 ]; then
        echo "    NO authoritative result (iter:status): ${not_completed[*]}"
    fi
    if [ "$completed" -eq 0 ]; then
        echo "    NO iteration reached '${CHAIN_COMPLETED_STATUS}' — this chain produced no authoritative result"
    fi
    return "$CHAIN_ITERATION_FAILED_EXIT_CODE"
}

# ---------------------------------------------------------------------------
# F-SCANB-4 — auto-resume inspector capture validation
# ---------------------------------------------------------------------------
# `scripts/launch/inspect_run_state.py --layout chain --next-iter` prints ONLY the
# integer index as its FINAL stdout write on the success path (every
# diagnostic goes to stderr; see its `print(compute_next_iter(...))` /
# `return 0`). The shell capture, however, can ALSO carry import-time
# plugin-loader chatter emitted BEFORE that value (observed ~12,960 bytes),
# so the raw capture is NOT the value: pre-fix, run_chain.sh assigned the
# whole capture to START_ITER with no validation, and auto-resume broke
# exactly when a resume mattered (known workaround: --start_iter N).
#
# The last line of an exit-0 capture is therefore the value channel — the
# cheapest clean channel available without changing the inspector's stdout
# contract, which human operators and this wrapper both consume. Anything
# whose last line is not a bare non-negative integer must REFUSE loudly
# upstream: a silently-defaulted or corrupted iteration index corrupts a
# resumed campaign (a fresh START_ITER=1 on a populated workspace, or an
# argparse crash deep in the runner).
#
#   $1     : raw captured stdout of the inspector (exit 0 path).
#   stdout : the validated bare non-negative integer (the capture's last line).
#   return : 0 when the last line is a bare non-negative integer; 1 otherwise
#            (empty capture included). Prints nothing on failure — the caller
#            owns the operator-facing refusal and names the workaround.
extract_validated_next_iter() {
    local raw="$1"
    local last_line="${raw##*$'\n'}"
    if [[ "$last_line" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "$last_line"
        return 0
    fi
    return 1
}
