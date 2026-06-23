#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain — SHARED LIBRARY (source, do not exec)
# ---------------------------------------------------------------------------
# Role : library, mode-agnostic. Holds everything that is identical between
#        any execution backend (lilab subprocess, SDSC slurm, future ones).
# Entry: run_chain.sh sources this file and adds the mode-aware pieces.
# Files: see sdsc_submission_scripts/README.md for the folder map.
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
LLM_MODEL="gemini-3.1-pro-preview"  # §3.2: matches run_one_iteration.py default
LLM_CONFIG=""
REFLECT_PROVIDER=""
REFLECT_MODEL_ID=""
TRIAL_PORTION=0.1                   # §3.2: synced to Python default 0.1 (was 0.02)
TRAIN_PORTION=0.1                   # §3.2: synced to Python default 0.1 (was 1.0)
EVAL_PORTION=0.1                    # §3.2: synced to Python default 0.1 (was 0.02)
HUMAN_ADVICE_FILE=""
ADVICE=""
PLAN_OVERRIDES=""
# DATA_DIR: lilab environment default per 13.C directive. Python argparse
# default is None; the shell pre-fills the canonical lilab data path so the
# chain runbook works without an explicit --data_dir flag on lilab. SDSC
# operators must override via --data_dir to point at the cluster's
# scratch path.
DATA_DIR="/home/klz/Data/TIDMAD/"
TRIAL_TIME_BUDGET_MINUTES=""        # §3.2: empty == omit == Python None
FORMAL_TIME_BUDGET_MINUTES=""       # §3.2: empty == omit == Python None
FORMAL_EVAL_PORTION=1.0             # Phase R §13: eval-side scope for formal training; default 1.0 = production full-clone (lower for smoke/CI)
TRIAL_VRAM_BUDGET_GB=""             # §3.2: empty == omit == Python None
FORMAL_VRAM_BUDGET_GB=""            # §3.2: empty == omit == Python None
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
TRIAL_STRATEGY="snapshot"           # choices: snapshot|anchors|target
FORMAL_STRATEGY="snapshot"          # choices: snapshot|anchors|target
FORMAL_PORTION=0.1                  # segments per file for formal training scope
FORMAL_TRAIN_PORTION=1.0            # per-epoch iteration fraction for formal training
FORMAL_ROUND_STRATEGY="full_clone"  # canonical: full_clone|hybrid_params|independent (legacy aliases inherit_best_trial|llm_propose accepted, schema canonicalises)
# §3.2 — Degenerate-output reaction policy (paired with execute_tools.squid_health_checks)
DEGENERATE_PENALTY_SCORE=""                 # empty → omit flag → schema default None (null score on collapse)
# §3.2 — Data slicing / reproducibility (13.C-bis; None-default → omit when empty)
TARGET_FILES=()                     # int list; passed only when non-empty
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

# --- Unified-orchestrator (run_chain.sh) defaults ---
# MODE picks the execution backend: lilab (foreground subprocess) or
# sdsc (sbatch + afterany). Required when invoking run_chain.sh directly;
# the legacy stubs preset it before calling parse_chain_args.
MODE=""
# DRY_RUN=1 makes run_chain print the exact command per iteration without
# touching the workspace or submitting any jobs. Side-effect-free.
DRY_RUN=0
# Auto-resume control (Phase 6.8 Commit 13.B). AUTO_RESUME=1 means the
# orchestrator queries scripts/inspect_run_state.py --next-iter to pick up
# where a partially-run chain left off. --no_auto_resume forces 1.
# --start_iter N overrides everything (manual pin). --force_fresh bypasses
# the stale-fresh safety guard that otherwise refuses to clobber a
# non-empty workspace from iter 1.
AUTO_RESUME=1
FORCE_FRESH=0
# Force the LAST round of each iteration to be a FORMAL training run
# (full dataset, no --trial_portion clamp). Default ON to preserve the
# pre-existing chain behavior. Pass --no-force_formal_round in smoke /
# gate tests where all rounds should stay in trial mode — otherwise the
# last round uses the full training set and a 2-iter chain takes 2+
# hours instead of ~30-60 min. CLI flag exists on run_one_iteration.py
# (--force_formal_round / --no-force_formal_round); this wrapper-side
# forwarding closes the same bash-wrapper gap the lit-review flags hit.
FORCE_FORMAL_ROUND=1
# ml_literature_review enable flag (Risk 4 two-layer gate). Default 0
# matches configs/lit_review_config.yaml's `enabled: false` baseline —
# backward-compatible with pre-lit-review chain invocations. When the
# operator passes --ml_lit_review_enabled at the chain level the wrapper
# forwards it to run_one_iteration.py; otherwise nothing is forwarded
# and the YAML's `enabled: false` keeps lit-review off. Closes the same
# bash-wrapper gap as --no-force_formal_round, originally surfaced
# during loss-inventory Gate 3.
ML_LIT_REVIEW_ENABLED=0
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
        --llm_model)              LLM_MODEL="$2"; shift 2 ;;
        --reflect_provider)       REFLECT_PROVIDER="$2"; shift 2 ;;
        --reflect_model_id)       REFLECT_MODEL_ID="$2"; shift 2 ;;
        --trial_portion)          TRIAL_PORTION="$2"; shift 2 ;;
        --train_portion)          TRAIN_PORTION="$2"; shift 2 ;;
        --eval_portion)           EVAL_PORTION="$2"; shift 2 ;;
        --human_advice_file)      HUMAN_ADVICE_FILE="$2"; shift 2 ;;
        --advice)                 ADVICE="$2"; shift 2 ;;
        --plan_overrides)         PLAN_OVERRIDES="$2"; shift 2 ;;
        --llm_config)             LLM_CONFIG="$2"; shift 2 ;;
        --data_dir)               DATA_DIR="$2"; shift 2 ;;
        --trial_time_budget_minutes) TRIAL_TIME_BUDGET_MINUTES="$2"; shift 2 ;;
        --formal_time_budget_minutes) FORMAL_TIME_BUDGET_MINUTES="$2"; shift 2 ;;
        --formal_eval_portion)       FORMAL_EVAL_PORTION="$2"; shift 2 ;;
        --trial_vram_budget_gb)   TRIAL_VRAM_BUDGET_GB="$2"; shift 2 ;;
        --formal_vram_budget_gb)  FORMAL_VRAM_BUDGET_GB="$2"; shift 2 ;;
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
        --start_iter)             START_ITER="$2"; shift 2 ;;
        # §3.2 — Adaptive-tuning brakes
        --attempts_per_round)        ATTEMPTS_PER_ROUND="$2"; shift 2 ;;
        --attempts_per_formal_round) ATTEMPTS_PER_FORMAL_ROUND="$2"; shift 2 ;;
        --max_fail_rounds)           MAX_FAIL_ROUNDS="$2"; shift 2 ;;
        # §3.2 — Propose→Implement retry brakes (13.C-bis)
        --max_proposal_attempts)     MAX_PROPOSAL_ATTEMPTS="$2"; shift 2 ;;
        --max_impl_attempts)         MAX_IMPL_ATTEMPTS="$2"; shift 2 ;;
        # §3.2 — Trial / formal strategy + formal-scope (13.C-bis)
        --trial_strategy)            TRIAL_STRATEGY="$2"; shift 2 ;;
        --formal_strategy)           FORMAL_STRATEGY="$2"; shift 2 ;;
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
        # Slurm-only flags — silently accepted on lilab too (ignored)
        --partition)              PARTITION="$2"; shift 2 ;;
        --time)                   TIME="$2"; shift 2 ;;
        --mem)                    MEM="$2"; shift 2 ;;
        --gpus)                   GPUS="$2"; shift 2 ;;
        --cpus)                   CPUS="$2"; shift 2 ;;
        *)                        echo "Unknown arg: $1" >&2; exit 1 ;;
      esac
    done

    if [ -z "$WORKSPACE" ] || [ ${#SEED_PATHS[@]} -eq 0 ] || [ -z "$RUN_NAME" ]; then
        echo "Required: --workspace, --seed_paths, --run_name" >&2
        exit 1
    fi
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
        --seed_paths "${SEED_PATHS[@]}"
        --max_rounds "$MAX_ROUNDS"
        --max_epochs "$MAX_EPOCHS"
        --llm_model "$LLM_MODEL"
        --trial_portion "$TRIAL_PORTION"
        --train_portion "$TRAIN_PORTION"
        --eval_portion "$EVAL_PORTION"
        --exploration_mode "$EXPLORATION_MODE"
        --minimum_boldness "$MINIMUM_BOLDNESS"
        --attempts_per_round "$ATTEMPTS_PER_ROUND"
        --attempts_per_formal_round "$ATTEMPTS_PER_FORMAL_ROUND"
        --max_fail_rounds "$MAX_FAIL_ROUNDS"
        --max_proposal_attempts "$MAX_PROPOSAL_ATTEMPTS"
        --max_impl_attempts "$MAX_IMPL_ATTEMPTS"
        --max_failed_iterations "$MAX_FAILED_ITERATIONS"
        --trial_strategy "$TRIAL_STRATEGY"
        --formal_strategy "$FORMAL_STRATEGY"
        --formal_portion "$FORMAL_PORTION"
        --formal_train_portion "$FORMAL_TRAIN_PORTION"
        --formal_round_strategy "$FORMAL_ROUND_STRATEGY"
        # Always-on for chain runs: per-experiment denoised .h5 files
        # accumulate at ~76 GB / attempt and can fill the data drive
        # within 3-4 iterations of a 20-iter chain. Mirrors what
        # submit_one_iteration.slurm hardcodes for SDSC mode.
        --cleanup_denoised
    )
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
    if [ ${#TARGET_FILES[@]} -gt 0 ]; then
        APP_ARGS+=(--target_files "${TARGET_FILES[@]}")
    fi
    if [ -n "$SAMPLING_SEED" ]; then
        APP_ARGS+=(--sampling_seed "$SAMPLING_SEED")
    fi
    if [ -n "$LLM_CONFIG" ]; then
        APP_ARGS+=(--llm_config "$LLM_CONFIG")
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
    if [ -n "$PLAN_OVERRIDES" ]; then
        APP_ARGS+=(--plan_overrides "$PLAN_OVERRIDES")
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
    # FORCE_FORMAL_ROUND default 1 preserves prior chain behavior; only forward
    # the negation explicitly when set to 0 (run_one_iteration.py's argparse
    # default is True, so omitting the flag keeps formal forcing on).
    if [ "$FORCE_FORMAL_ROUND" -eq 0 ]; then
        APP_ARGS+=(--no-force_formal_round)
    fi
    # ML_LIT_REVIEW_ENABLED default 0 matches the YAML's enabled: false; only
    # forward the flag when explicitly enabled at the chain level. When 0 we
    # forward nothing and run_one_iteration.py reads the YAML.
    [ "$ML_LIT_REVIEW_ENABLED" -eq 1 ] && APP_ARGS+=(--ml_lit_review_enabled)
    APP_ARGS+=(--formal_eval_portion "$FORMAL_EVAL_PORTION")
    if [ -n "$TRIAL_VRAM_BUDGET_GB" ]; then
        APP_ARGS+=(--trial_vram_budget_gb "$TRIAL_VRAM_BUDGET_GB")
    fi
    if [ -n "$FORMAL_VRAM_BUDGET_GB" ]; then
        APP_ARGS+=(--formal_vram_budget_gb "$FORMAL_VRAM_BUDGET_GB")
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
    echo "  LLM model        : $LLM_MODEL"
    if [ -n "$LLM_CONFIG" ]; then
        echo "  LLM config       : $LLM_CONFIG"
    fi
    if [ -n "$MODE" ]; then
        echo "  Mode             : $MODE"
    fi
    if [ -n "${START_ITER:-}" ]; then
        echo "  Start iter       : $START_ITER  (auto_resume=$AUTO_RESUME, force_fresh=$FORCE_FRESH)"
    fi
    # --- §3.2 plan flags (input contract) ---
    echo "  §3.2 plan flags:"
    echo "    Data dir       : $DATA_DIR"
    echo "    Trial portion  : $TRIAL_PORTION"
    echo "    Train portion  : $TRAIN_PORTION"
    echo "    Eval portion   : $EVAL_PORTION"
    echo "    Exploration    : $EXPLORATION_MODE  (boldness>=$MINIMUM_BOLDNESS)"
    echo "    Round attempts : trial=$ATTEMPTS_PER_ROUND, formal=$ATTEMPTS_PER_FORMAL_ROUND, max_fail_rounds=$MAX_FAIL_ROUNDS"
    echo "    Propose retry  : max_proposal_attempts=$MAX_PROPOSAL_ATTEMPTS, max_impl_attempts=$MAX_IMPL_ATTEMPTS"
    echo "    Chain brake    : max_failed_iterations=$MAX_FAILED_ITERATIONS  (halt on streak of failed iter manifests)"
    echo "    Trial strategy : $TRIAL_STRATEGY"
    echo "    Formal scope   : strategy=$FORMAL_STRATEGY, portion=$FORMAL_PORTION, train_portion=$FORMAL_TRAIN_PORTION"
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
        echo "    Time budgets   : trial=${TRIAL_TIME_BUDGET_MINUTES:-(none)}min, formal=${FORMAL_TIME_BUDGET_MINUTES:-(none)}min, eval_portion=$FORMAL_EVAL_PORTION"
    fi
    if [ -n "$TRIAL_VRAM_BUDGET_GB" ] || [ -n "$FORMAL_VRAM_BUDGET_GB" ]; then
        echo "    VRAM budgets   : trial=${TRIAL_VRAM_BUDGET_GB:-(auto)}GB, formal=${FORMAL_VRAM_BUDGET_GB:-(auto)}GB"
    fi
    if [ -n "$ADVICE" ]; then
        echo "    Advice file    : $ADVICE"
    elif [ -n "$HUMAN_ADVICE_FILE" ]; then
        echo "    Advice file    : $HUMAN_ADVICE_FILE  (legacy --human_advice_file)"
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

# Run all iterations. The caller must have defined a `submit_iteration`
# function that takes the iteration number and uses the populated
# SOURCE_PATHS and APP_ARGS arrays.
run_chain() {
    if [ "$DRY_RUN" -ne 1 ]; then
        mkdir -p "$WORKSPACE"
    fi
    local ITER
    local first="${START_ITER:-1}"
    for ITER in $(seq "$first" "$NUM_ITERATIONS"); do
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

        submit_iteration "$ITER"
    done
}
