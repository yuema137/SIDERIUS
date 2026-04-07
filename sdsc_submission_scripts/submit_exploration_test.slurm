#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Tier 3 Integration Test — SDSC Slurm Submission
# ---------------------------------------------------------------------------
# Runs the full 5-agent exploration workflow as a Slurm job.
# Usage:
#   sbatch --partition=gpu-shared --gres=gpu:v100:1 --mem=24G --time=01:30:00 \
#          --cpus-per-task=8 \
#          sdsc_submission_scripts/submit_exploration_test.slurm
#
# Optional override args (passed after the .slurm filename):
#   --run_name <name>   (default: test_full_loop_<date>)
#   --max_rounds <N>    (default: 2)
#   --llm_model <id>    (default: gemini-3.1-pro-preview)
#
# FIXED SBATCH HEADERS (Static cluster configuration)
#SBATCH --account=ddp433
#SBATCH --job-name="SIDERIUS_TIER3_TEST"
#SBATCH --output="/home/ym137/SIDERIUS/sdsc_submission_scripts/logs/tier3_%j.out"
#SBATCH --error="/home/ym137/SIDERIUS/sdsc_submission_scripts/logs/tier3_%j.err"

# NOTE: Resource parameters (partition, gres, mem, time, cpus) must be
# provided via sbatch CLI to ensure full compliance with the bank_limit plugin.

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

# Activate Python virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "[CRITICAL] Virtual environment not found in $PROJECT_DIR" >&2
    exit 1
fi

# Make internal modules and ml_models discoverable
export PYTHONPATH="${PROJECT_DIR}:${PROJECT_DIR}/ml_models:${PROJECT_DIR}/execute_tools:${PYTHONPATH:-}"

# Resolve workspace from project config (Lustre scratch on SDSC)
WORKSPACE_DIR=$(grep 'siderius_data_dir' "${PROJECT_DIR}/tidmad_data_config.yaml" | cut -d: -f2 | tr -d ' ' | tr -d '"' | tr -d "'")
TEST_WORKSPACE="${WORKSPACE_DIR}/tier3_test_runs"
mkdir -p "${TEST_WORKSPACE}"

# --- Application Defaults ---
RUN_NAME="test_full_loop_$(date +%m%d_%H%M)"
MAX_ROUNDS=2
LLM_MODEL="gemini-3.1-pro-preview"
MAX_EPOCHS=1

# --- Parse application-level args (after the .slurm filename) ---
while [[ $# -gt 0 ]]; do
  case $1 in
    --run_name)     RUN_NAME="$2"; shift 2 ;;
    --max_rounds)   MAX_ROUNDS="$2"; shift 2 ;;
    --llm_model)    LLM_MODEL="$2"; shift 2 ;;
    --max_epochs)   MAX_EPOCHS="$2"; shift 2 ;;
    --*)            shift 2 ;; # Safely ignore Slurm resource flags
    *)              shift ;;
  esac
done

echo "############################################################"
echo "  SIDERIUS TIER 3 INTEGRATION TEST"
echo "------------------------------------------------------------"
echo "  [EXECUTION CONTEXT]"
echo "    Run name    : ${RUN_NAME}"
echo "    Max rounds  : ${MAX_ROUNDS}"
echo "    Max epochs  : ${MAX_EPOCHS}"
echo "    LLM model   : ${LLM_MODEL}"
echo "    Workspace   : ${TEST_WORKSPACE}"
echo ""
echo "  [RUNTIME CONTEXT (Assigned by Slurm)]"
echo "    Job ID      : ${SLURM_JOB_ID:-N/A}"
echo "    Partition   : ${SLURM_JOB_PARTITION:-N/A}"
echo "    Nodes       : ${SLURM_JOB_NUM_NODES:-1}"
echo "    GPUs        : ${SLURM_JOB_GPUS:-0}"
echo "    CPUs        : ${SLURM_CPUS_PER_TASK:-N/A}"
echo "############################################################"

# --- Execute Test ---
set +e
python sdsc_submission_scripts/run_exploration_test.py \
    --workspace "${TEST_WORKSPACE}" \
    --run_name "${RUN_NAME}" \
    --llm_model "${LLM_MODEL}" \
    --max_rounds "${MAX_ROUNDS}" \
    --max_epochs "${MAX_EPOCHS}"
PY_EXIT_CODE=$?
set -e

# --- Post-Run Verification ---
echo ""
echo "--- Post-Run Verification ---"

if [ $PY_EXIT_CODE -ne 0 ]; then
    echo "[FAIL] Test exited with code: $PY_EXIT_CODE" >&2
    exit $PY_EXIT_CODE
fi

# Verify the workflow output directory exists
RUN_DIR="${TEST_WORKSPACE}/${RUN_NAME}"
if [ ! -d "$RUN_DIR" ]; then
    echo "[FAIL] Run directory not found: $RUN_DIR" >&2
    exit 1
fi

# Verify iteration_001 exists with all expected files
ITER_DIR="${RUN_DIR}/iteration_001"
if [ ! -d "$ITER_DIR" ]; then
    echo "[FAIL] Iteration directory not found: $ITER_DIR" >&2
    exit 1
fi

INTERP_FILE="${ITER_DIR}/interpretation_${RUN_NAME}.json"
if [ ! -s "$INTERP_FILE" ]; then
    echo "[FAIL] Interpretation output not found or empty: $INTERP_FILE" >&2
    exit 1
fi

echo "[SUCCESS] Tier 3 test passed. Outputs at: $RUN_DIR"

echo "############################################################"
echo "  SIDERIUS | Tier 3 Test Job ${SLURM_JOB_ID:-N/A} COMPLETED SUCCESSFULLY"
echo "############################################################"
