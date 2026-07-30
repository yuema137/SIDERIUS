#!/bin/bash
# ---------------------------------------------------------------------------
# V19 serial queue runner — single RTX 5090, eight chains, one at a time
# (frozen plan: reports/v19_20260729_2136.md; protocol:
# docs/design/v19_priorities/v19_launch_protocol.md).
#
# Scientific matrix: 4 bands x 2 advice families. Frozen order (operator
# 2026-07-29): all four ARCH chains first (one chain of evidence per band
# early, covering the never-run bands 0-3 and 15-19), then the four LOSS
# chains. Arch and loss chains are fully independent (separate workspaces,
# separate incumbent state, no shared artifacts) — audited before freezing.
#
# V19 deltas from the V18r command (everything else V18r-identical):
#   * --enable_chain_incumbent_formal_gates          (PR 1 coupling ON)
#   * --order_strategy_override sequential
#     --file_order_override <ascending band files>   (PR 2, explicit)
#   * --enable_structured_health_feedback
#     --health_feedback_history_window_iterations 3
#     --health_feedback_history_max_entries_per_model 8   (PR 3 ON)
#   * --runtime_watchdog_safety_factor 3.5           (5090 watchdog-only
#     override; admission factors stay trial 3.0 / formal 2.0 — the V19
#     runtime split keeps admission byte-identical to V18)
#
# Concurrency: MAX_CONC=1 — the 5090 (32 GB) fits ONE 16 GB-budget chain;
# V18r's 4-way rolling topology was sized for the H100 80 GB box.
#
# Selective runs: V19 O2 —
#   bash sdsc_submission_scripts/v19_queue_runner.sh --only v19_arch_10_14
# filters the queue (canonical order, unknown/duplicate/blank names fail
# before anything launches). Omitting --only runs the full frozen queue.
#
# Runs inside its own screen session (siderius-v19queue — deliberately NO
# underscore after "v19" so running_count, which greps "siderius-v19_",
# never counts the runner itself).
#
# Restart semantics: progress index in $STATE advances after every launch
# attempt (even guarded skips — never loops on a blocked entry); restarting
# the runner resumes from the first not-yet-attempted chain. A chain that
# must be re-run after review: V19_RESUME=1 + --only <run_name> (resume
# uses --auto_resume inside the chain; the run-invariants lock rejects any
# changed policy on resume).
#
# Log: $WS_ROOT/v19_queue_runner.log   State: $WS_ROOT/v19_queue_state
# ---------------------------------------------------------------------------
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=_chain_common.sh
source "$REPO/sdsc_submission_scripts/_chain_common.sh"
WS_ROOT="${WS_ROOT:-/home/klz/Data/SIDEREIS_DATA/v19}"
EXIT_DIR="${EXIT_DIR:-/tmp}"
MAX_CONC=1
LOGF="$WS_ROOT/v19_queue_runner.log"
STATE="$WS_ROOT/v19_queue_state"

# Frozen queue (operator 2026-07-29): run_name : scope : monitored : advice
QUEUE=(
  "v19_arch_00_03:0-3:0,1,2,3:arch"
  "v19_arch_04_09:4-9:4,5,6,7,8,9:arch"
  "v19_arch_10_14:10-14:10,11,12,13,14:arch"
  "v19_arch_15_19:15-19:15,16,17,18,19:arch"
  "v19_loss_00_03:0-3:0,1,2,3:loss"
  "v19_loss_04_09:4-9:4,5,6,7,8,9:loss"
  "v19_loss_10_14:10-14:10,11,12,13,14:loss"
  "v19_loss_15_19:15-19:15,16,17,18,19:loss"
)

# Explicit ascending file order per scope (PR 2: the resolved list is an
# EXPLICIT launch value, not an implicit sorted default).
file_order_for_scope() {
  case "$1" in
    0-3)   echo "0,1,2,3" ;;
    4-9)   echo "4,5,6,7,8,9" ;;
    10-14) echo "10,11,12,13,14" ;;
    15-19) echo "15,16,17,18,19" ;;
    *)     echo ""; return 1 ;;
  esac
}

log() { echo "$(date -u '+%Y-%m-%d %H:%M:%S') $*" >> "$LOGF"; }

next_index() { [ -f "$STATE" ] && cat "$STATE" || echo 0; }

running_count() { screen -ls 2>/dev/null | grep -c "siderius-v19_" || true; }

launch_chain() {
  local RUN="$1" SCOPE="$2" FILES="$3" FLAVOR="$4"
  local WS="$WS_ROOT/$RUN"
  local LOG="$WS_ROOT/${RUN}_$(date +%Y%m%d_%H%M).log"
  local MARKER="$EXIT_DIR/${RUN}.exit"
  local SESSION="siderius-$RUN"
  local ORDER
  ORDER="$(file_order_for_scope "$SCOPE")" || { log "ERROR $RUN: unknown scope $SCOPE"; return 1; }

  # Duplicate-run guards (never launch over an existing run). Cold-start
  # contract: an existing workspace is only reused under explicit
  # V19_RESUME=1 (the chain's --auto_resume + run-invariants lock then
  # govern the resume).
  if [ -e "$WS" ] && [ "${V19_RESUME:-0}" != "1" ]; then
    log "ERROR $RUN: workspace exists — SKIPPED (set V19_RESUME=1 with --only $RUN for an intentional resume)"; return 1
  fi
  if screen -ls 2>/dev/null | grep -qF ".$SESSION"$'\t'; then log "ERROR $RUN: screen $SESSION already exists — SKIPPED"; return 1; fi
  if ps -eo args | grep -v grep | grep -v v19_queue_runner | grep -qF "$WS_ROOT/$RUN"; then
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
      --enable_chain_incumbent_formal_gates \
      --order_strategy_override sequential \
      --file_order_override '$ORDER' \
      --enable_structured_health_feedback \
      --health_feedback_history_window_iterations 3 \
      --health_feedback_history_max_entries_per_model 8 \
      --skip_formal_min_delta 0.0 \
      --bypass_formal_time_budget_min_delta 0.5 \
      --trial_time_budget_minutes 20 \
      --formal_time_budget_minutes 120 \
      --trial_vram_budget_gb 16 \
      --formal_vram_budget_gb 16 \
      --runtime_watchdog \
      --runtime_safety_factor 1.5 \
      --runtime_trial_safety_factor 3.0 \
      --runtime_formal_safety_factor 2.0 \
      --runtime_watchdog_safety_factor 3.5 \
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
    log "LAUNCHED $RUN scope=$SCOPE monitored=$FILES order=$ORDER log=$LOG"
    return 0
  fi
  log "ERROR $RUN: screen did not start"
  return 1
}

# Test hook: `V19_QUEUE_NO_MAIN=1 source v19_queue_runner.sh` loads the
# queue definition and functions without parsing args or launching.
if [ "${V19_QUEUE_NO_MAIN:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

# --- V19 O2 selective launching -------------------------------------------
ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --only)
      [ -n "${2:-}" ] || { echo "[v19-queue] --only requires a name list" >&2; exit 1; }
      ONLY="$2"; shift 2 ;;
    *) echo "[v19-queue] unknown argument: $1 (usage: v19_queue_runner.sh [--only <names>])" >&2; exit 1 ;;
  esac
done
SELECTED=()
while IFS= read -r line; do SELECTED+=("$line"); done < <(
  filter_roster "$ONLY" "${QUEUE[@]}"
)
[ "${#SELECTED[@]}" -gt 0 ] || { echo "[v19-queue] selection resolved to nothing (see error above)" >&2; exit 1; }
QUEUE=("${SELECTED[@]}")
if [ -n "$ONLY" ]; then
  # Targeted runs get their OWN transient progress file: the persistent
  # full-queue index (possibly already at queue end) must never suppress
  # an explicit --only retry, and a targeted run must never advance the
  # full queue's restart position.
  STATE="$WS_ROOT/v19_queue_state_only.$$"
  rm -f "$STATE"
fi

mkdir -p "$WS_ROOT"
log "v19 queue runner started: MAX_CONC=$MAX_CONC queue_from_index=$(next_index) queue_len=${#QUEUE[@]} only='${ONLY:-<full>}'"
while true; do
  idx=$(next_index)
  if [ "$idx" -ge "${#QUEUE[@]}" ]; then
    if [ "$(running_count)" -eq 0 ]; then
      log "ALL DONE: queue empty and no v19 chains running — exiting"
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
    sleep 90
  fi
  sleep 60
done
