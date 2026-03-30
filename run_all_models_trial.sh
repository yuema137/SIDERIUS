#!/bin/bash
# run_all_models_trial.sh
#
# Runs the agent in trial mode for all 5 TIDMAD models.
# Trial mode uses multi-file sparse sampling — no file_index needed.
# The final round of each run is forced to formal mode (all 20 files).
#
# Models are organized into groups to balance GPU memory.
# Within a group, all models run in parallel.
#
# Usage:
#   screen -S siderius-orchestrator
#   bash run_all_models_trial.sh
#   Ctrl+A D   (detach)

set -euo pipefail

SIDERIUS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/home/klz/Data/SIDEREIS_DATA/logs"
PYTHON="$SIDERIUS_DIR/.venv/bin/python"
RUN_NAME="small_sample_trial_v0"
MAX_ROUNDS=20
PROVIDER="gemini"
MODEL_ID="gemini-3.1-flash-lite-preview"
POLL_INTERVAL=30

# ---------------------------------------------------------------------------
# Model groups — same as run_all_models.sh
# ---------------------------------------------------------------------------
MODEL_GROUPS=(
    "punet wavenet fcnet"    # Group 1 — light models (parallel)
    "transformer"            # Group 2 — attention-heavy (~6 GB)
    "rnn"                    # Group 3 — separate to avoid concurrent GPU OOM
)

mkdir -p "$LOG_DIR"
declare -A STATUS

echo ""
echo "############################################################"
echo "  SIDERIUS — Trial Mode Run (multi-file sparse sampling)"
echo "  Started    : $(date)"
echo "  Run name   : $RUN_NAME"
echo "  Log dir    : $LOG_DIR"
echo "  Rounds     : $MAX_ROUNDS per model (final round = formal)"
echo "  Mode       : trial (is_trial=True)"
echo "  Provider   : $PROVIDER / $MODEL_ID"
echo "  Groups     : ${#MODEL_GROUPS[@]}"
for i in "${!MODEL_GROUPS[@]}"; do
    echo "    Group $((i+1)): ${MODEL_GROUPS[$i]}"
done
echo "############################################################"
echo ""

# ---------------------------------------------------------------------------
# Helper: launch one model in its own detached screen
# ---------------------------------------------------------------------------
launch_model() {
    local model="$1"
    local SCREEN_NAME="siderius-${model}-${RUN_NAME}"
    local LOG_FILE="$LOG_DIR/${model}_${RUN_NAME}.log"
    local EXIT_CODE_FILE="/tmp/siderius_${model}_exit"

    if screen -list | grep -q "${SCREEN_NAME}"; then
        echo "  [WARN] Stale screen '${SCREEN_NAME}' found — killing it."
        screen -S "${SCREEN_NAME}" -X quit || true
        sleep 2
    fi
    rm -f "${EXIT_CODE_FILE}"

    echo "  LAUNCHING : ${model}  |  screen=${SCREEN_NAME}  |  log=${LOG_FILE}"

    screen -L -Logfile "${LOG_FILE}" -dmS "${SCREEN_NAME}" bash -c "
        \"${PYTHON}\" \"${SIDERIUS_DIR}/run_comparison.py\" \
            --model \"${model}\" \
            --max_rounds \"${MAX_ROUNDS}\" \
            --run_name \"${RUN_NAME}\" \
            --is_trial \
            --provider \"${PROVIDER}\" \
            --model_id \"${MODEL_ID}\" \
            --progress_bar
        echo \$? > \"${EXIT_CODE_FILE}\"
    "
}

# ---------------------------------------------------------------------------
# Helper: wait for all models in a group to finish
# ---------------------------------------------------------------------------
wait_for_group() {
    local models=("$@")

    echo ""
    echo "  Waiting for group [${models[*]}] to complete..."
    echo "  (attach to any screen with: screen -r siderius-<model>-${RUN_NAME})"
    echo ""

    local all_done=false
    while [ "$all_done" = false ]; do
        all_done=true
        for model in "${models[@]}"; do
            if screen -list | grep -q "siderius-${model}-${RUN_NAME}"; then
                all_done=false
                break
            fi
        done
        [ "$all_done" = false ] && sleep "${POLL_INTERVAL}"
    done

    for model in "${models[@]}"; do
        local EXIT_CODE_FILE="/tmp/siderius_${model}_exit"
        local EXIT_CODE=1
        if [ -f "${EXIT_CODE_FILE}" ]; then
            EXIT_CODE=$(cat "${EXIT_CODE_FILE}")
            rm -f "${EXIT_CODE_FILE}"
        fi
        if [ "${EXIT_CODE}" -eq 0 ]; then
            STATUS[$model]="SUCCESS"
            echo "  ✓ ${model} DONE at $(date)"
        else
            STATUS[$model]="FAILED (exit code ${EXIT_CODE})"
            echo "  ✗ ${model} FAILED at $(date) — see $LOG_DIR/${model}_${RUN_NAME}.log"
        fi
    done
}

# ---------------------------------------------------------------------------
# Main: iterate over groups
# ---------------------------------------------------------------------------
for i in "${!MODEL_GROUPS[@]}"; do
    group_num=$((i + 1))
    IFS=' ' read -r -a models <<< "${MODEL_GROUPS[$i]}"

    echo "============================================================"
    echo "  GROUP ${group_num}/${#MODEL_GROUPS[@]}: [${models[*]}]  |  $(date)"
    echo "============================================================"

    for model in "${models[@]}"; do
        launch_model "$model"
    done

    wait_for_group "${models[@]}"
    echo ""
done

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
echo "############################################################"
echo "  SIDERIUS — Trial Mode Run Complete"
echo "  Run name : $RUN_NAME"
echo "  Finished : $(date)"
echo "------------------------------------------------------------"
for group in "${MODEL_GROUPS[@]}"; do
    IFS=' ' read -r -a models <<< "$group"
    for model in "${models[@]}"; do
        echo "  ${model} : ${STATUS[$model]}"
    done
done
echo "############################################################"
