#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Per-Iteration Slurm Job
# ---------------------------------------------------------------------------
# Runs ONE iteration of the 5-agent exploration workflow as a Slurm job.
# Designed for chained submission via run_iteration_chain.sh — each job
# is 1-4 hours (fits gpu-shared partition easily) and writes a manifest.json
# that the next job uses to discover this iteration's output.
#
# Usage:
#   sbatch --partition=gpu-shared --nodes=1 --ntasks=1 --gpus=1 --mem=24G \
#          --time=04:00:00 --cpus-per-task=8 \
#          sdsc_submission_scripts/submit_one_iteration.slurm \
#          --workspace /expanse/lustre/projects/ddp433/ym137/exploration_v1 \
#          --iteration 3 \
#          --source_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \
#          --max_rounds 20
#
# FIXED SBATCH HEADERS (Static cluster configuration)
#SBATCH --account=ddp433
#SBATCH --job-name="SIDERIUS_ITER"
#SBATCH --output="/home/ym137/SIDERIUS/sdsc_submission_scripts/logs/iter_%j.out"
#SBATCH --error="/home/ym137/SIDERIUS/sdsc_submission_scripts/logs/iter_%j.err"

# NOTE: Resource parameters (nodes, ntasks, partition, gpus, mem, time, cpus-per-task)
# must be provided via sbatch CLI to ensure full compliance with the bank_limit plugin.

# --- Robust Error Handling ---
set -e
set -o pipefail

# --- Project Paths & Validation ---
PROJECT_DIR="/home/ym137/SIDERIUS"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "[CRITICAL] Project directory $PROJECT_DIR not found!" >&2
    exit 1
fi

# --- Environment Setup ---
if [ -f "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
fi

cd "$PROJECT_DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "[CRITICAL] Virtual environment not found in $PROJECT_DIR" >&2
    exit 1
fi

export PYTHONPATH="${PROJECT_DIR}:${PROJECT_DIR}/ml_models:${PROJECT_DIR}/execute_tools:${PYTHONPATH:-}"

# --- Application Defaults ---
WORKSPACE=""
ITERATION=""
SOURCE_PATHS=()
MAX_ROUNDS=20
MAX_PROPOSAL_ATTEMPTS=3
LLM_MODEL="gemini-3.1-pro-preview"
TRIAL_PORTION=0.1
TRAIN_PORTION=0.1
EVAL_PORTION=0.1
HUMAN_ADVICE_PROPOSE=""
HUMAN_ADVICE_TUNE=""

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case $1 in
    --workspace)              WORKSPACE="$2"; shift 2 ;;
    --iteration)              ITERATION="$2"; shift 2 ;;
    --source_paths)
      shift
      while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
        SOURCE_PATHS+=("$1")
        shift
      done
      ;;
    --max_rounds)             MAX_ROUNDS="$2"; shift 2 ;;
    --max_proposal_attempts)  MAX_PROPOSAL_ATTEMPTS="$2"; shift 2 ;;
    --llm_model)              LLM_MODEL="$2"; shift 2 ;;
    --trial_portion)          TRIAL_PORTION="$2"; shift 2 ;;
    --train_portion)          TRAIN_PORTION="$2"; shift 2 ;;
    --eval_portion)           EVAL_PORTION="$2"; shift 2 ;;
    --human_advice_propose)   HUMAN_ADVICE_PROPOSE="$2"; shift 2 ;;
    --human_advice_tune)      HUMAN_ADVICE_TUNE="$2"; shift 2 ;;
    *)                        shift ;;  # ignore unknown flags
  esac
done

if [ -z "$WORKSPACE" ] || [ -z "$ITERATION" ] || [ ${#SOURCE_PATHS[@]} -eq 0 ]; then
    echo "[FAIL] Required args: --workspace, --iteration, --source_paths" >&2
    exit 1
fi

echo "############################################################"
echo "  SIDERIUS PER-ITERATION JOB"
echo "------------------------------------------------------------"
echo "  [EXECUTION CONTEXT]"
echo "    Workspace        : ${WORKSPACE}"
echo "    Iteration        : ${ITERATION}"
echo "    Source paths     : ${#SOURCE_PATHS[@]} files"
for p in "${SOURCE_PATHS[@]}"; do
    echo "      - $p"
done
echo "    Max rounds       : ${MAX_ROUNDS}"
echo "    LLM model        : ${LLM_MODEL}"
echo ""
echo "  [RUNTIME CONTEXT (Assigned by Slurm)]"
echo "    Job ID           : ${SLURM_JOB_ID:-N/A}"
echo "    Partition        : ${SLURM_JOB_PARTITION:-N/A}"
echo "    Nodes            : ${SLURM_JOB_NUM_NODES:-1}"
echo "    GPUs             : ${SLURM_JOB_GPUS:-0}"
echo "    CPUs             : ${SLURM_CPUS_PER_TASK:-N/A}"
echo "############################################################"

# --- Build CLI args for the runner ---
RUNNER_ARGS=(
    --workspace "${WORKSPACE}"
    --iteration "${ITERATION}"
    --source_paths "${SOURCE_PATHS[@]}"
    --max_rounds "${MAX_ROUNDS}"
    --max_proposal_attempts "${MAX_PROPOSAL_ATTEMPTS}"
    --llm_model "${LLM_MODEL}"
    --trial_portion "${TRIAL_PORTION}"
    --train_portion "${TRAIN_PORTION}"
    --eval_portion "${EVAL_PORTION}"
    --is_trial
    --cleanup_denoised
)

if [ -n "$HUMAN_ADVICE_PROPOSE" ]; then
    RUNNER_ARGS+=(--human_advice_propose "${HUMAN_ADVICE_PROPOSE}")
fi
if [ -n "$HUMAN_ADVICE_TUNE" ]; then
    RUNNER_ARGS+=(--human_advice_tune "${HUMAN_ADVICE_TUNE}")
fi

# --- Execute the runner ---
set +e
python sdsc_submission_scripts/run_one_iteration.py "${RUNNER_ARGS[@]}"
PY_EXIT_CODE=$?
set -e

# --- Post-Run Verification ---
echo ""
echo "--- Post-Run Verification ---"

if [ $PY_EXIT_CODE -ne 0 ]; then
    echo "[FAIL] Iteration runner exited with code: $PY_EXIT_CODE" >&2
    exit $PY_EXIT_CODE
fi

# Verify manifest.json was written
ITER_DIR_NAME=$(printf "iter_%03d" "${ITERATION}")
MANIFEST="${WORKSPACE}/${ITER_DIR_NAME}/manifest.json"
if [ ! -s "$MANIFEST" ]; then
    echo "[FAIL] Manifest not found or empty: $MANIFEST" >&2
    exit 1
fi

echo "[SUCCESS] Iteration ${ITERATION} complete. Manifest: $MANIFEST"
echo "############################################################"
echo "  SIDERIUS | Iteration Job ${SLURM_JOB_ID:-N/A} COMPLETED SUCCESSFULLY"
echo "############################################################"
