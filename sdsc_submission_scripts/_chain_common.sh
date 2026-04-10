#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain — shared logic (sourced by both lilab and SDSC)
# ---------------------------------------------------------------------------
# Full runbook (lilab + SDSC): docs/running_chain_test.md
# ---------------------------------------------------------------------------
# This file is sourced by run_iteration_chain.sh (SDSC, Slurm) and
# run_iteration_chain_lilab.sh (lilab, foreground subprocess). It owns
# everything that should be identical between the two: defaults, argument
# parsing, human-advice file loading, app-arg construction, source-path
# building, and the per-iteration loop scaffolding.
#
# Each caller defines a single function:
#   submit_iteration <ITER>   # given the current iteration number, run
#                               # one iteration. APP_ARGS and SOURCE_PATHS
#                               # are already populated in the environment.
# It then calls `run_chain` to execute all N iterations.
#
# Why this exists: keeping a single source of truth for the shared logic
# means the lilab and SDSC chains can never drift in subtle ways. The only
# legitimate diff between the two callers is the execution mechanism
# (sbatch with dependencies vs foreground python3 subprocess).

set -e
set -o pipefail

# --- Defaults (apply to both lilab and SDSC) ---
WORKSPACE=""
NUM_ITERATIONS=2
SEED_PATHS=()
MAX_ROUNDS=5
MAX_EPOCHS=""
LLM_MODEL="gemini-3.1-pro-preview"
REFLECT_PROVIDER=""
REFLECT_MODEL_ID=""
TRIAL_PORTION=0.02
TRAIN_PORTION=1.0
EVAL_PORTION=0.02
HUMAN_ADVICE_FILE=""
PLAN_OVERRIDES=""

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
        --plan_overrides)         PLAN_OVERRIDES="$2"; shift 2 ;;
        # Slurm-only flags — silently accepted on lilab too (ignored)
        --partition)              PARTITION="$2"; shift 2 ;;
        --time)                   TIME="$2"; shift 2 ;;
        --mem)                    MEM="$2"; shift 2 ;;
        --gpus)                   GPUS="$2"; shift 2 ;;
        --cpus)                   CPUS="$2"; shift 2 ;;
        *)                        echo "Unknown arg: $1" >&2; exit 1 ;;
      esac
    done

    if [ -z "$WORKSPACE" ] || [ ${#SEED_PATHS[@]} -eq 0 ]; then
        echo "Required: --workspace, --seed_paths" >&2
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
# Populates the SOURCE_PATHS array in the caller's scope.
build_source_paths() {
    local iter=$1
    SOURCE_PATHS=("${SEED_PATHS[@]}")
    local prev
    for prev in $(seq 1 $((iter - 1))); do
        local prev_iter_dir
        prev_iter_dir=$(printf "${WORKSPACE}/iter_%03d" "$prev")
        SOURCE_PATHS+=("@manifest:${prev_iter_dir}/manifest.json")
    done
}

# Build the APP_ARGS array (run_one_iteration.py CLI) for iteration $1.
# SOURCE_PATHS must already be populated.
build_app_args() {
    local iter=$1
    APP_ARGS=(
        --workspace "$WORKSPACE"
        --iteration "$iter"
        --source_paths "${SOURCE_PATHS[@]}"
        --max_rounds "$MAX_ROUNDS"
        --llm_model "$LLM_MODEL"
        --trial_portion "$TRIAL_PORTION"
        --train_portion "$TRAIN_PORTION"
        --eval_portion "$EVAL_PORTION"
    )
    if [ -n "$MAX_EPOCHS" ]; then
        APP_ARGS+=(--max_epochs "$MAX_EPOCHS")
    fi
    if [ -n "$REFLECT_PROVIDER" ]; then
        APP_ARGS+=(--reflect_provider "$REFLECT_PROVIDER")
    fi
    if [ -n "$REFLECT_MODEL_ID" ]; then
        APP_ARGS+=(--reflect_model_id "$REFLECT_MODEL_ID")
    fi
    if [ -n "$HUMAN_ADVICE_FILE" ]; then
        APP_ARGS+=(--human_advice_file "$HUMAN_ADVICE_FILE")
    fi
    if [ -n "$PLAN_OVERRIDES" ]; then
        APP_ARGS+=(--plan_overrides "$PLAN_OVERRIDES")
    fi
}

print_chain_header() {
    local label=$1
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
    echo "  Max epochs       : ${MAX_EPOCHS:-(no cap)}"
    echo "  LLM model        : $LLM_MODEL"
    echo "############################################################"
}

# Run all iterations. The caller must have defined a `submit_iteration`
# function that takes the iteration number and uses the populated
# SOURCE_PATHS and APP_ARGS arrays.
run_chain() {
    mkdir -p "$WORKSPACE"
    local ITER
    for ITER in $(seq 1 $NUM_ITERATIONS); do
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
