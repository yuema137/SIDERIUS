#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Universal Job Dispatcher (v2.2)
# ---------------------------------------------------------------------------
# FIXED SBATCH HEADERS (Static cluster configuration)
#SBATCH --account=ddp433
#SBATCH --job-name="SIDERIUS_AGENT"
#SBATCH --output="/home/ym137/SIDERIUS/sdsc_submission_scripts/logs/hpt_%j.out"
#SBATCH --error="/home/ym137/SIDERIUS/sdsc_submission_scripts/logs/hpt_%j.err"

# NOTE: Resource parameters (nodes, partition, gpus, mem, time) must be 
# provided via sbatch CLI to ensure full compliance with the bank_limit plugin.

# --- Robust Error Handling ---
set -e           # Exit immediately if a command exits with a non-zero status
set -o pipefail  # Return the exit code of the last command in the pipe to fail
# We omit 'set -u' to prevent crashing on uninitialized system variables in /etc/bashrc

# --- Project Paths & Validation ---
PROJECT_DIR="/home/ym137/SIDERIUS"

if [ ! -d "$PROJECT_DIR" ]; then
    echo "[CRITICAL] Project directory $PROJECT_DIR not found!" >&2
    exit 1
fi

# --- Environment Setup ---
# Safely source bashrc (ignoring unbound variables in system scripts)
if [ -f "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
fi

cd "$PROJECT_DIR"

# Activate Python Virtual Environment with explicit check
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "[CRITICAL] Virtual environment not found in $PROJECT_DIR" >&2
    exit 1
fi

# Ensure internal modules and models are discoverable
export PYTHONPATH="${PROJECT_DIR}:${PROJECT_DIR}/ml_models:${PROJECT_DIR}/execute_tools:${PYTHONPATH:-}"

# Force Python stdout/stderr to be unbuffered so progress lines appear in the
# slurm .out file in real time, instead of being block-buffered in memory and
# only flushed when the process exits. Affects every python child process in
# this job session.
export PYTHONUNBUFFERED=1

# Dynamically retrieve workspace directory from project config for verification
# We use a safer way to parse the YAML config
WORKSPACE_DIR=$(grep 'siderius_data_dir' "${PROJECT_DIR}/tidmad_data_config.yaml" | cut -d: -f2 | tr -d ' ' | tr -d '"' | tr -d "'")

# --- Application Defaults ---
MODEL="punet"
RUN_NAME="hpt_$(date +%m%d_%H%M)"
MAX_ROUNDS=20
PROVIDER="gemini"
MODEL_ID="gemini-3.1-flash-lite-preview"
REFLECT_PROVIDER=""
REFLECT_MODEL_ID=""
HUMAN_ADVICE_FILE=""

# --- Interface: Named Argument Parsing ---
# Handles application-level arguments passed after the .slurm filename
while [[ $# -gt 0 ]]; do
  case $1 in
    --model)             MODEL="$2"; shift 2 ;;
    --run_name)          RUN_NAME="$2"; shift 2 ;;
    --max_rounds)        MAX_ROUNDS="$2"; shift 2 ;;
    --provider)          PROVIDER="$2"; shift 2 ;;
    --model_id)          MODEL_ID="$2"; shift 2 ;;
    --reflect_provider)  REFLECT_PROVIDER="$2"; shift 2 ;;
    --reflect_model_id)  REFLECT_MODEL_ID="$2"; shift 2 ;;
    --human_advice_file) HUMAN_ADVICE_FILE="$2"; shift 2 ;;
    --*)                 shift 2 ;; # Safely ignore resource-level flags like --nodes
    *)              shift ;;
  esac
done

echo "############################################################"
echo "  SIDERIUS | DISPATCHER ACTIVE"
echo "------------------------------------------------------------"
echo "  [EXECUTION CONTEXT]"
echo "    Model        : ${MODEL}"
echo "    Run Name     : ${RUN_NAME}"
echo "    Max Rounds   : ${MAX_ROUNDS}"
echo "    Planner LLM  : ${PROVIDER} | ${MODEL_ID}"
if [ -n "${REFLECT_PROVIDER}" ] || [ -n "${REFLECT_MODEL_ID}" ]; then
    echo "    Reflect LLM  : ${REFLECT_PROVIDER:-${PROVIDER}} | ${REFLECT_MODEL_ID:-${MODEL_ID}}"
else
    echo "    Reflect LLM  : (provider-aware default — gemini provider gets gemini-2.5-flash)"
fi
echo "    Advice File  : ${HUMAN_ADVICE_FILE:-(none)}"
echo ""
echo "  [RUNTIME CONTEXT (Assigned by Slurm)]"
echo "    Job ID       : ${SLURM_JOB_ID}"
echo "    Partition    : ${SLURM_JOB_PARTITION:-N/A}"
echo "    Nodes        : ${SLURM_JOB_NUM_NODES:-1}"
echo "    GPUs         : ${SLURM_JOB_GPUS:-0}"
echo "    Workspace    : ${WORKSPACE_DIR}"
echo "############################################################"

# --- Execute Core Logic ---
# Temporarily disable 'exit on error' to handle python exit status manually
set +e
PY_ARGS=(
    --model "${MODEL}"
    --run_name "${RUN_NAME}"
    --max_rounds "${MAX_ROUNDS}"
    --provider "${PROVIDER}"
    --model_id "${MODEL_ID}"
    --is_trial
    --override_old_run
    --progress_bar
    --cleanup_denoised
)
if [ -n "${REFLECT_PROVIDER}" ]; then
    PY_ARGS+=(--reflect_provider "${REFLECT_PROVIDER}")
fi
if [ -n "${REFLECT_MODEL_ID}" ]; then
    PY_ARGS+=(--reflect_model_id "${REFLECT_MODEL_ID}")
fi
if [ -n "${HUMAN_ADVICE_FILE}" ]; then
    PY_ARGS+=(--human_advice_file "${HUMAN_ADVICE_FILE}")
fi
python scripts/run_comparison.py "${PY_ARGS[@]}"
PY_EXIT_CODE=$?
set -e

# --- POST-RUN VERIFICATION ---
echo ""
echo "--- Post-Run Verification ---"

# Target file path to verify agent success
SUMMARY_FILE="${WORKSPACE_DIR}/${MODEL}/${RUN_NAME}/agent/summary_${RUN_NAME}_agent.json"

# Check 1: Did Python exit cleanly?
if [ $PY_EXIT_CODE -ne 0 ]; then
    echo "[FAIL] Python process crashed with Exit Code: $PY_EXIT_CODE" >&2
    exit $PY_EXIT_CODE
fi

# Check 2: Does the output summary exist?
if [ ! -f "$SUMMARY_FILE" ]; then
    echo "[FAIL] Expected summary file NOT FOUND: $SUMMARY_FILE" >&2
    exit 1
else
    # Check 3: Is the summary file non-empty? (Protects against disk quota issues)
    if [ ! -s "$SUMMARY_FILE" ]; then
        echo "[FAIL] Summary file is EMPTY. Check for storage or I/O errors." >&2
        exit 1
    fi
    echo "[SUCCESS] Verified: Research results saved to $SUMMARY_FILE"
fi

echo "############################################################"
echo "  SIDERIUS | Job ${SLURM_JOB_ID} COMPLETED SUCCESSFULLY"
echo "############################################################"
