#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain Orchestrator
# ---------------------------------------------------------------------------
# Submits N iteration jobs in sequence using --dependency=afterok for
# automatic chaining. Each job's source paths = original seeds + all
# previous iteration manifests.
#
# Usage:
#   bash sdsc_submission_scripts/run_iteration_chain.sh \
#       --workspace /expanse/lustre/projects/ddp433/ym137/exploration_v1 \
#       --num_iterations 10 \
#       --seed_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \
#       --max_rounds 20 \
#       --partition gpu-shared \
#       --time 04:00:00 \
#       --mem 24G
#
# Each iteration job is independent. If iteration N fails, iterations N+1..M
# are blocked by --dependency=afterok and automatically cancelled. Resubmit
# them after fixing iteration N.

set -e
set -o pipefail

# --- Defaults ---
WORKSPACE=""
NUM_ITERATIONS=10
SEED_PATHS=()
MAX_ROUNDS=20
LLM_MODEL="gemini-3.1-pro-preview"
TRIAL_PORTION=0.1
TRAIN_PORTION=0.1
EVAL_PORTION=0.1
HUMAN_ADVICE_PROPOSE=""
HUMAN_ADVICE_TUNE=""
PARTITION="gpu-shared"
TIME="04:00:00"
MEM="24G"
GPUS=1
CPUS=8

# --- Argument parsing ---
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
    --llm_model)              LLM_MODEL="$2"; shift 2 ;;
    --trial_portion)          TRIAL_PORTION="$2"; shift 2 ;;
    --train_portion)          TRAIN_PORTION="$2"; shift 2 ;;
    --eval_portion)           EVAL_PORTION="$2"; shift 2 ;;
    --human_advice_propose)   HUMAN_ADVICE_PROPOSE="$2"; shift 2 ;;
    --human_advice_tune)      HUMAN_ADVICE_TUNE="$2"; shift 2 ;;
    --partition)              PARTITION="$2"; shift 2 ;;
    --time)                   TIME="$2"; shift 2 ;;
    --mem)                    MEM="$2"; shift 2 ;;
    --gpus)                   GPUS="$2"; shift 2 ;;
    --cpus)                   CPUS="$2"; shift 2 ;;
    *)                        echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ -z "$WORKSPACE" ] || [ ${#SEED_PATHS[@]} -eq 0 ]; then
    echo "Required: --workspace, --seed_paths" >&2
    exit 1
fi

mkdir -p "$WORKSPACE"

PROJECT_DIR="/home/ym137/SIDERIUS"
SLURM_SCRIPT="${PROJECT_DIR}/sdsc_submission_scripts/submit_one_iteration.slurm"

echo "############################################################"
echo "  SIDERIUS Iteration Chain Orchestrator"
echo "  Workspace        : $WORKSPACE"
echo "  Num iterations   : $NUM_ITERATIONS"
echo "  Seed paths       : ${#SEED_PATHS[@]} files"
for p in "${SEED_PATHS[@]}"; do
    echo "    - $p"
done
echo "  Max rounds       : $MAX_ROUNDS"
echo "  LLM model        : $LLM_MODEL"
echo "  Slurm: ${PARTITION}, ${GPUS} GPU, ${MEM}, ${TIME}, ${CPUS} CPUs"
echo "############################################################"

# --- Submit chain ---
PREV_JOB_ID=""
SUBMITTED_JOBS=()

for ITER in $(seq 1 $NUM_ITERATIONS); do
    # Build source paths for this iteration:
    #   = original seeds + all previous iterations' run_output paths (read from manifests)
    SOURCE_PATHS=("${SEED_PATHS[@]}")
    for PREV_ITER in $(seq 1 $((ITER - 1))); do
        PREV_ITER_DIR=$(printf "${WORKSPACE}/iter_%03d" "$PREV_ITER")
        MANIFEST="${PREV_ITER_DIR}/manifest.json"
        # The orchestrator can't read manifests until previous jobs finish,
        # so we use a predictable wildcard pattern that the runner will
        # resolve at job execution time. Workaround: pass a "hint path"
        # that the runner can glob.
        # SIMPLER: add a helper that reads the manifest at job start.
        # For now, pass the manifest path itself; the runner resolves it.
        # NOTE: This requires run_one_iteration.py to handle manifest paths.
        SOURCE_PATHS+=("@manifest:${MANIFEST}")
    done

    # Build sbatch command
    SBATCH_ARGS=(
        --partition="$PARTITION"
        --nodes=1
        --ntasks=1
        --gpus="$GPUS"
        --mem="$MEM"
        --time="$TIME"
        --cpus-per-task="$CPUS"
    )

    if [ -n "$PREV_JOB_ID" ]; then
        SBATCH_ARGS+=(--dependency="afterok:${PREV_JOB_ID}")
    fi

    # Application args (passed after the .slurm filename)
    APP_ARGS=(
        --workspace "$WORKSPACE"
        --iteration "$ITER"
        --source_paths "${SOURCE_PATHS[@]}"
        --max_rounds "$MAX_ROUNDS"
        --llm_model "$LLM_MODEL"
        --trial_portion "$TRIAL_PORTION"
        --train_portion "$TRAIN_PORTION"
        --eval_portion "$EVAL_PORTION"
    )
    if [ -n "$HUMAN_ADVICE_PROPOSE" ]; then
        APP_ARGS+=(--human_advice_propose "$HUMAN_ADVICE_PROPOSE")
    fi
    if [ -n "$HUMAN_ADVICE_TUNE" ]; then
        APP_ARGS+=(--human_advice_tune "$HUMAN_ADVICE_TUNE")
    fi

    echo ""
    echo "Submitting iteration $ITER..."
    if [ -n "$PREV_JOB_ID" ]; then
        echo "  (depends on job $PREV_JOB_ID)"
    fi

    OUTPUT=$(sbatch "${SBATCH_ARGS[@]}" "$SLURM_SCRIPT" "${APP_ARGS[@]}")
    JOB_ID=$(echo "$OUTPUT" | grep -oP '\d+$')
    if [ -z "$JOB_ID" ]; then
        echo "[FAIL] Could not parse job ID from sbatch output:" >&2
        echo "$OUTPUT" >&2
        exit 1
    fi

    echo "  Job ID: $JOB_ID"
    SUBMITTED_JOBS+=("$ITER:$JOB_ID")
    PREV_JOB_ID="$JOB_ID"
done

echo ""
echo "############################################################"
echo "  CHAIN SUBMITTED — ${NUM_ITERATIONS} iterations"
for entry in "${SUBMITTED_JOBS[@]}"; do
    IFS=':' read -r ITER JOB_ID <<< "$entry"
    echo "  iter $ITER → job $JOB_ID"
done
echo ""
echo "  Monitor with: squeue -u \$USER"
echo "  Cancel chain: scancel ${SUBMITTED_JOBS[*]}"
echo "############################################################"
