#!/bin/bash
# run_all_models.sh
#
# Runs the full baseline + agent comparison for all 5 TIDMAD models.
# Models are organized into groups. Within a group, all models run in
# parallel (each in its own screen). Groups run sequentially — the next
# group only starts after every screen in the current group has exited.
#
# Adjust MODEL_GROUPS to balance GPU memory across parallel runs.
# Estimated baseline VRAM per model (batch_size=1):
#   punet       0.29 GB   wavenet  0.12 GB   rnn   0.22 GB
#   fcnet       4.89 GB   transformer  6.06 GB
#
# Two-layer structure:
#   Orchestrator screen  (siderius-orchestrator)
#     └── Group 1: siderius-punet + siderius-wavenet  (parallel)
#     └── Group 2: siderius-rnn                       (alone)
#     └── Group 3: siderius-fcnet                     (alone)
#     └── Group 4: siderius-transformer               (alone)
#
# Usage:
#   screen -S siderius-orchestrator
#   bash run_all_models.sh
#   Ctrl+A D   (detach)
#
# Monitor a running model:
#   screen -r siderius-punet-{RUN_NAME}
#   Ctrl+A D
#
# Follow a log live:
#   tail -f /home/klz/Data/SIDEREIS_DATA/logs/punet_{RUN_NAME}.log
#
# Clean a log after run (strip tqdm escape codes):
#   col -b < punet_v1.log > punet_v1_clean.log

set -euo pipefail

SIDERIUS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$(python3 -c "import json; print(json.load(open('tidmad_data_config.json'))['siderius_data_dir'])" 2>/dev/null || echo '/home/klz/Data/SIDEREIS_DATA')/logs"
PYTHON="$SIDERIUS_DIR/.venv/bin/python"
RUN_NAME="v3_file6"
MAX_ROUNDS=20
FILE_INDEX=6
PROVIDER="gemini"
MODEL_ID="gemini-3.1-flash-lite-preview"
POLL_INTERVAL=30   # seconds between checks for screen exit

# ---------------------------------------------------------------------------
# Define model groups.
# Each element is a space-separated list of models that run in parallel.
# Groups themselves run sequentially.
# ---------------------------------------------------------------------------
MODEL_GROUPS=(
    "punet wavenet fcnet"          # Group 1 — light models (run in parallel)
    "transformer"     # Group 2 — attention-heavy (~6 GB)
    "rnn"             # Group 3 — separate to avoid concurrent GPU OOM
)

mkdir -p "$LOG_DIR"
declare -A STATUS

echo ""
echo "############################################################"
echo "  SIDERIUS — Full Comparison Run (grouped parallel)"
echo "  Started    : $(date)"
echo "  Log dir    : $LOG_DIR"
echo "  Rounds     : $MAX_ROUNDS per model"
echo "  File index : $FILE_INDEX"
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

    # Kill any stale screen with this name
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
            --file_index \"${FILE_INDEX}\" \
            --provider \"${PROVIDER}\" \
            --model_id \"${MODEL_ID}\" \
            --progress_bar
        echo \$? > \"${EXIT_CODE_FILE}\"
    "
}

# ---------------------------------------------------------------------------
# Helper: wait for all models in a group to finish, then collect exit codes
# ---------------------------------------------------------------------------
wait_for_group() {
    local models=("$@")

    echo ""
    echo "  Waiting for group [${models[*]}] to complete..."
    echo "  (attach to any screen with: screen -r siderius-<model>)"
    echo ""

    # Poll until ALL screens in the group have exited
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

    # Collect exit codes
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

    # Launch all models in this group in parallel
    for model in "${models[@]}"; do
        launch_model "$model"
    done

    # Wait for the entire group to finish before proceeding
    wait_for_group "${models[@]}"
    echo ""
done

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
echo "############################################################"
echo "  SIDERIUS — All Groups Complete"
echo "  Finished: $(date)"
echo "------------------------------------------------------------"
for group in "${MODEL_GROUPS[@]}"; do
    IFS=' ' read -r -a models <<< "$group"
    for model in "${models[@]}"; do
        echo "  ${model} : ${STATUS[$model]}"
    done
done
echo "############################################################"
