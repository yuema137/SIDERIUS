#!/bin/bash
# ---------------------------------------------------------------------------
# V18r rolling-queue runner (operator decision 2026-07-24).
#
# Keeps up to MAX_CONC v18r chains running. Whenever a running chain fully
# finishes (its screen session ends), launches the next chain from QUEUE in
# order. Duplicate-run guards: skips (with an ERROR log line) if the target
# workspace, screen session, or a live process for the run already exists.
#
# Runs inside its own screen session (siderius-v18rqueue — deliberately NO
# underscore after "v18r" so the concurrency count, which greps for
# "siderius-v18r_", never counts the runner itself).
#
# Log: $WS_ROOT/v18r_queue_runner.log   State: $WS_ROOT/v18r_queue_state
# ---------------------------------------------------------------------------
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_ROOT="${WS_ROOT:-/workspace/DATA/SIDERIUS_DATA}"
EXIT_DIR="${EXIT_DIR:-/tmp}"
MAX_CONC=4
LOGF="$WS_ROOT/v18r_queue_runner.log"
STATE="$WS_ROOT/v18r_queue_state"

# Launch order (operator, 2026-07-24): 15-19 loss, 15-19 arch, 0-3 loss, 0-3 arch.
QUEUE=(
  "v18r_loss_15_19:15-19:15,16,17,18,19:loss"
  "v18r_arch_15_19:15-19:15,16,17,18,19:arch"
  "v18r_loss_00_03:0-3:0,1,2,3:loss"
  "v18r_arch_00_03:0-3:0,1,2,3:arch"
)

log() { echo "$(date -u '+%Y-%m-%d %H:%M:%S') $*" >> "$LOGF"; }

next_index() { [ -f "$STATE" ] && cat "$STATE" || echo 0; }

running_count() { screen -ls 2>/dev/null | grep -c "siderius-v18r_" || true; }

launch_chain() {
  local RUN="$1" SCOPE="$2" FILES="$3" FLAVOR="$4"
  local WS="$WS_ROOT/$RUN"
  local LOG="$WS_ROOT/${RUN}_$(date +%Y%m%d_%H%M).log"
  local MARKER="$EXIT_DIR/${RUN}.exit"
  local SESSION="siderius-$RUN"

  # Duplicate-run guards (never launch over an existing run).
  if [ -e "$WS" ]; then log "ERROR $RUN: workspace exists — SKIPPED (advance queue manually after review)"; return 1; fi
  if screen -ls 2>/dev/null | grep -qF ".$SESSION"$'\t'; then log "ERROR $RUN: screen $SESSION already exists — SKIPPED"; return 1; fi
  if ps -eo args | grep -v grep | grep -v v18r_queue_runner | grep -qF "$WS_ROOT/$RUN"; then
    log "ERROR $RUN: live process referencing $WS_ROOT/$RUN — SKIPPED"; return 1
  fi

  rm -f "$MARKER"
  touch "$LOG" || { log "ERROR $RUN: log path not writable"; return 1; }
  screen -L -Logfile "$LOG" -dmS "$SESSION" bash -lc "
    set -euo pipefail
    cd '$REPO'
    .venv/bin/python -c 'import torch; assert torch.cuda.is_available()'
    set +e
    bash sdsc_submission_scripts/run_chain.sh \
      --mode lilab \
      --workspace '$WS' \
      --run_name '$RUN' \
      --num_iterations 20 \
      --auto_resume \
      --max_rounds 3 \
      --max_epochs 1 \
      --data_scope '$SCOPE' \
      --health_gate_files '$FILES' \
      --skip_formal_min_delta 0.0 \
      --bypass_formal_time_budget_min_delta 0.5 \
      --trial_time_budget_minutes 20 \
      --formal_time_budget_minutes 120 \
      --trial_vram_budget_gb 16 \
      --formal_vram_budget_gb 16 \
      --runtime_watchdog \
      --runtime_safety_factor 1.5 \
      --runtime_trial_safety_factor 2.0 \
      --runtime_watchdog_floor_seconds 120 \
      --formal_strategy snapshot \
      --formal_round_strategy inherit_best_trial \
      --exploration_mode explore \
      --ml_lit_review_enabled \
      --llm_config llm_configs/openai_tiered_v1.json \
      --advice 'advice/workflow/v18r_${FLAVOR}_explorer.json' \
      --health_checks_config configs/health_checks_baseline_observe_mode.yaml
    status=\$?
    set -e
    printf 'EXIT=%s\n' \"\$status\" > '$MARKER'
    exit \"\$status\"
  "
  sleep 3
  if screen -ls 2>/dev/null | grep -qF ".$SESSION"$'\t'; then
    log "LAUNCHED $RUN scope=$SCOPE monitored=$FILES log=$LOG"
    return 0
  fi
  log "ERROR $RUN: screen did not start"
  return 1
}

log "queue runner started: MAX_CONC=$MAX_CONC queue_from_index=$(next_index) queue_len=${#QUEUE[@]}"
while true; do
  idx=$(next_index)
  if [ "$idx" -ge "${#QUEUE[@]}" ]; then
    if [ "$(running_count)" -eq 0 ]; then
      log "ALL DONE: queue empty and no v18r chains running — exiting"
      exit 0
    fi
    sleep 120
    continue
  fi
  if [ "$(running_count)" -lt "$MAX_CONC" ]; then
    IFS=: read -r RUN SCOPE FILES FLAVOR <<< "${QUEUE[$idx]}"
    log "slot free ($(running_count)/$MAX_CONC running) — launching queue[$idx]=$RUN"
    launch_chain "$RUN" "$SCOPE" "$FILES" "$FLAVOR"
    echo $((idx + 1)) > "$STATE"   # advance even on guarded skip: never loop on a blocked entry
    sleep 90                        # stagger before the next possible launch
  fi
  sleep 60
done
