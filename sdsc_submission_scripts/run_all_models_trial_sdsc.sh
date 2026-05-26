#!/bin/bash
# run_all_models_trial_sdsc.sh
# 
# Optimized for SDSC Expanse Slurm environment.
# Replaces 'screen' with native background processes (&) and 'wait'.
# Targets the Lustre Scratch file system for high-performance I/O.

set -euo pipefail

# --- Environment Setup ---
SIDERIUS_DIR="$(cd "$(dirname "$0")" && pwd)"
# Extract scratch workspace path and log directory from YAML config
# Handles potential quotes and spaces in the path
RAW_WORKSPACE_DIR=$(grep 'siderius_data_dir' tidmad_data_config.yaml | cut -d: -f2 | tr -d ' ' | tr -d '"' | tr -d "'")
LOG_DIR="${RAW_WORKSPACE_DIR}/logs"
PYTHON="${SIDERIUS_DIR}/.venv/bin/python"

# --- Run Configuration ---
RUN_NAME="small_sample_trial_sdsc_v1"
MAX_ROUNDS=20
PROVIDER="gemini"
MODEL_ID="gemini-3.1-flash-lite-preview"
CLEANUP_DENOISED=true   # Deletes intermediate H5 files to save Scratch space
POLL_INTERVAL=30        # Seconds between status checks

# --- Model Groups ---
# Models in the same group run in parallel on the allocated GPU node
MODEL_GROUPS=(
    "punet wavenet fcnet"    # Group 1: Light-weight 1D models
    "transformer"            # Group 2: Attention-heavy (High VRAM usage)
    "rnn"                    # Group 3: Recurrent models
)

mkdir -p "$LOG_DIR"
declare -A STATUS
declare -A PIDS

echo "############################################################"
echo "  SIDERIUS — SDSC EXPANSE PRODUCTION RUN"
echo "  Started    : $(date)"
echo "  Run name   : $RUN_NAME"
echo "  Log dir    : $LOG_DIR"
echo "  Workspace  : $RAW_WORKSPACE_DIR"
echo "  Provider   : $PROVIDER ($MODEL_ID)"
echo "############################################################"
echo ""

# ---------------------------------------------------------------------------
# Helper: Launch one model node as a background process
# ---------------------------------------------------------------------------
launch_model() {
    local model="$1"
    local LOG_FILE="$LOG_DIR/${model}_${RUN_NAME}.log"

    echo "  [LAUNCH] Starting ${model}... logging to ${LOG_FILE}"

    # Execute the Python node in the background
    # Redirect both stdout and stderr to the specific log file
    "${PYTHON}" "${SIDERIUS_DIR}/scripts/run_comparison.py" \
        --model "${model}" \
        --max_rounds "${MAX_ROUNDS}" \
        --run_name "${RUN_NAME}" \
        --is_trial \
        --override_old_run \
        --provider "${PROVIDER}" \
        --model_id "${MODEL_ID}" \
        --progress_bar \
        ${CLEANUP_DENOISED:+--cleanup_denoised} > "${LOG_FILE}" 2>&1 &
    
    # Store the Process ID (PID) to track completion
    PIDS[$model]=$!
}

# ---------------------------------------------------------------------------
# Helper: Wait for all background PIDs in the current group
# ---------------------------------------------------------------------------
wait_for_group() {
    local models=("$@")
    echo "  [WAIT] Monitoring Group PIDs: ${models[*]}..."

    for model in "${models[@]}"; do
        local pid=${PIDS[$model]}
        # Wait for the specific PID and capture its exit status
        if wait "$pid"; then
            STATUS[$model]="SUCCESS"
            echo "  ✓ ${model} (PID $pid) completed successfully at $(date)"
        else
            local exit_code=$?
            STATUS[$model]="FAILED (exit code $exit_code)"
            echo "  ✗ ${model} (PID $pid) failed at $(date) - Check logs!"
        fi
    done
}

# ---------------------------------------------------------------------------
# Main Execution Loop
# ---------------------------------------------------------------------------
for i in "${!MODEL_GROUPS[@]}"; do
    group_num=$((i + 1))
    IFS=' ' read -r -a models <<< "${MODEL_GROUPS[$i]}"

    echo "============================================================"
    echo "  GROUP ${group_num}/${#MODEL_GROUPS[@]}: [${models[*]}]"
    echo "============================================================"

    for model in "${models[@]}"; do
        launch_model "$model"
    done

    wait_for_group "${models[@]}"
    echo ""
done

# ---------------------------------------------------------------------------
# Final Execution Summary
# ---------------------------------------------------------------------------
echo "############################################################"
echo "  SIDERIUS — RUN SUMMARY: $RUN_NAME"
echo "  Finished   : $(date)"
echo "------------------------------------------------------------"
for group in "${MODEL_GROUPS[@]}"; do
    IFS=' ' read -r -a models <<< "$group"
    for model in "${models[@]}"; do
        echo "  ${model} : ${STATUS[$model]}"
    done
done
echo "############################################################"
