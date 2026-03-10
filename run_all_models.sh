#!/bin/bash
# run_all_models.sh
#
# Runs the full baseline + 50-round agent comparison for all 5 TIDMAD models,
# one at a time. Each model gets its own named screen session. The orchestrator
# waits for each screen to exit before creating the next, so the GPU is never
# shared between runs.
#
# Two-layer structure:
#   Orchestrator screen  (siderius-orchestrator)
#     └── spawns model screens one by one, waits for each to exit:
#           siderius-fcnet
#           siderius-punet
#           siderius-transformer
#           siderius-wavenet
#           siderius-rnn
#
# Each model screen uses 'screen -L' (built-in logging) so:
#   - stdout goes directly to screen's PTY → tqdm progress bars animate fully
#   - screen simultaneously writes everything to the log file
#
# Usage:
#   screen -S siderius-orchestrator
#   bash run_all_models.sh
#   Ctrl+A D   (detach — orchestrator keeps running)
#
# See live progress bars for the running model:
#   screen -r siderius-fcnet
#   Ctrl+A D   (detach without stopping it)
#
# Monitor log (raw, with escape codes — readable in terminal):
#   tail -f /home/klz/Data/SIDEREIS_DATA/logs/fcnet_v1.log
#
# Get a clean log after the run (strips tqdm escape codes):
#   col -b < /home/klz/Data/SIDEREIS_DATA/logs/fcnet_v1.log > fcnet_v1_clean.log
#
# Check orchestrator progress:
#   screen -r siderius-orchestrator

set -euo pipefail

SIDERIUS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/home/klz/Data/SIDEREIS_DATA/logs"
PYTHON="$SIDERIUS_DIR/.venv/bin/python"
MODELS=("fcnet" "punet" "transformer" "wavenet" "rnn")
RUN_NAME="v1"
MAX_ROUNDS=50
POLL_INTERVAL=30   # seconds between checks for screen exit

mkdir -p "$LOG_DIR"

declare -A STATUS

echo ""
echo "############################################################"
echo "  SIDERIUS — Full Comparison Run (all models)"
echo "  Started    : $(date)"
echo "  Log dir    : $LOG_DIR"
echo "  Rounds     : $MAX_ROUNDS per model"
echo "  Poll every : ${POLL_INTERVAL}s"
echo "############################################################"
echo ""

for model in "${MODELS[@]}"; do
    SCREEN_NAME="siderius-${model}"
    LOG_FILE="$LOG_DIR/${model}_${RUN_NAME}.log"
    EXIT_CODE_FILE="/tmp/siderius_${model}_exit"

    # Guard: abort if a stale screen with this name already exists
    if screen -list | grep -q "${SCREEN_NAME}"; then
        echo "  [WARN] Screen '${SCREEN_NAME}' already exists — killing it before restarting."
        screen -S "${SCREEN_NAME}" -X quit || true
        sleep 2
    fi
    rm -f "${EXIT_CODE_FILE}"

    echo "============================================================"
    echo "  LAUNCHING : ${model}  |  $(date)"
    echo "  Screen    : ${SCREEN_NAME}"
    echo "  Log       : ${LOG_FILE}"
    echo "============================================================"

    # Launch the model in its own detached screen.
    # -L -Logfile: screen's built-in logging — stdout goes to the PTY (tqdm animates)
    #              while screen simultaneously writes everything to LOG_FILE.
    # The inner command writes its exit code to a temp file for the orchestrator.
    screen -L -Logfile "${LOG_FILE}" -dmS "${SCREEN_NAME}" bash -c "
        \"${PYTHON}\" \"${SIDERIUS_DIR}/run_comparison.py\" \
            --model \"${model}\" \
            --max_rounds \"${MAX_ROUNDS}\" \
            --run_name \"${RUN_NAME}\" \
            --progress_bar
        echo \$? > \"${EXIT_CODE_FILE}\"
    "

    echo "  Screen '${SCREEN_NAME}' started. Waiting for completion..."
    echo "  (attach with: screen -r ${SCREEN_NAME})"
    echo ""

    # Poll until the screen session disappears (job finished)
    while screen -list | grep -q "${SCREEN_NAME}"; do
        sleep "${POLL_INTERVAL}"
    done

    # Read exit code written by the inner script
    if [ -f "${EXIT_CODE_FILE}" ]; then
        EXIT_CODE=$(cat "${EXIT_CODE_FILE}")
    else
        # File missing means the screen was killed externally
        EXIT_CODE=1
    fi
    rm -f "${EXIT_CODE_FILE}"

    if [ "${EXIT_CODE}" -eq 0 ]; then
        STATUS[$model]="SUCCESS"
        echo "  ✓ ${model} DONE at $(date)"
    else
        STATUS[$model]="FAILED (exit code ${EXIT_CODE})"
        echo "  ✗ ${model} FAILED at $(date) — see ${LOG_FILE}"
    fi
    echo ""
done

# Final summary
echo "############################################################"
echo "  SIDERIUS — All Models Complete"
echo "  Finished: $(date)"
echo "------------------------------------------------------------"
for model in "${MODELS[@]}"; do
    echo "  ${model} : ${STATUS[$model]}"
done
echo "############################################################"
