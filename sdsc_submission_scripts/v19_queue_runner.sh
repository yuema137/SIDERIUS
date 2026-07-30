#!/bin/bash
# ---------------------------------------------------------------------------
# V19 pairwise queue runner — single RTX 5090, four waves of TWO chains
# (operator revision 2026-07-29: pairwise per-band concurrency, reversed
# band order; supersedes the serial eight-chain schedule, which was never
# launched). Frozen plan: reports/v19_20260729_2136.md; protocol:
# docs/design/v19_priorities/v19_launch_protocol.md.
#
# Execution waves (frozen; a later wave starts only after BOTH chains of
# the current wave reach a terminal state under the continuation policy):
#   Wave 1: v19_arch_15_19 + v19_loss_15_19    (band 15-19)
#   Wave 2: v19_arch_10_14 + v19_loss_10_14    (band 10-14)
#   Wave 3: v19_arch_04_09 + v19_loss_04_09    (band 4-9)
#   Wave 4: v19_arch_00_03 + v19_loss_00_03    (band 0-3)
# Concurrency: exactly the two chains of the active wave (one arch + one
# loss, SAME band) — never chains from different bands, never more than 2.
#
# VRAM: each chain carries a 16 GB per-attempt admission cap
# (min(0.8 x physical, budget) in evaluate_vram_skill). Aggregate
# 2 x 16 GB equals the 5090's 32 GB — there is NO combined-VRAM admission
# (operator decision; V18r-measured models ran far below cap). An
# aggregate OOM is handled by the continuation policy: preserve both
# workspaces/logs, identify the failed process, restart ONLY the failed
# chain via --only, record the contention event.
#
# Continuation policy (frozen):
#   both EXIT=0            -> next wave
#   one/both chain failed  -> STOP before the next wave; report per-chain
#                             status; targeted restart via
#                             V19_RESUME=1 ... --only <run_name>; on queue
#                             restart, completed chains are skipped from
#                             the authoritative wave-state record and the
#                             earliest incomplete wave resumes.
#   HealthGate-invalid rounds / per-candidate admission rejections /
#   watchdog kills that the chain survives: normal in-chain outcomes,
#   never queue events. A watchdog/API failure that makes the chain
#   process terminal follows the chain-failure rule above.
#
# Authoritative per-chain status: $WS_ROOT/v19_wave_state.jsonl (one JSON
# line per finished chain attempt: run, wave, exit, start, end) — NOT log
# text. Exit codes come from per-chain markers ($EXIT_DIR/<run>.exit,
# EXIT=<n>) written inside each chain screen exactly as in V18r.
#
# Selective/targeted runs (V19 O2):
#   V19_RESUME=1 bash sdsc_submission_scripts/v19_queue_runner.sh --only v19_loss_15_19
# --only executions run the selection SERIALLY (one chain at a time) —
# targeted recovery never needs pairing and serial is always
# cross-band-safe. Unknown/duplicate/blank names fail before any launch.
#
# Runs inside screen -S v19_queue (session name deliberately without the
# "v19_" prefix pattern used by chain screens, so running_count never
# counts the runner). Env consumed: WS_ROOT (default
# /home/klz/Data/SIDEREIS_DATA/v19), EXIT_DIR (default /tmp),
# V19_RESUME (default 0). No other hidden state.
# ---------------------------------------------------------------------------
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=_chain_common.sh
source "$REPO/sdsc_submission_scripts/_chain_common.sh"
WS_ROOT="${WS_ROOT:-/home/klz/Data/SIDEREIS_DATA/v19}"
EXIT_DIR="${EXIT_DIR:-/tmp}"
MAX_CONC=2
LOGF="$WS_ROOT/v19_queue_runner.log"
WAVE_STATE="$WS_ROOT/v19_wave_state.jsonl"

# Frozen waves (operator 2026-07-29): wave : scope : monitored files.
# Chain names derive as v19_{arch,loss}_<band-tag>; both families of a
# wave launch together.
WAVES=(
  "1:15-19:15,16,17,18,19"
  "2:10-14:10,11,12,13,14"
  "3:4-9:4,5,6,7,8,9"
  "4:0-3:0,1,2,3"
)

# Full roster in wave order (for --only validation + targeted serial runs).
ROSTER=(
  "v19_arch_15_19:15-19:15,16,17,18,19:arch"
  "v19_loss_15_19:15-19:15,16,17,18,19:loss"
  "v19_arch_10_14:10-14:10,11,12,13,14:arch"
  "v19_loss_10_14:10-14:10,11,12,13,14:loss"
  "v19_arch_04_09:4-9:4,5,6,7,8,9:arch"
  "v19_loss_04_09:4-9:4,5,6,7,8,9:loss"
  "v19_arch_00_03:0-3:0,1,2,3:arch"
  "v19_loss_00_03:0-3:0,1,2,3:loss"
)

band_tag() {  # 15-19 -> 15_19
  echo "${1//-/_}" | awk -F_ '{ printf "%02d_%02d", $1, $2 }'
}

# Explicit ascending file order per scope (PR 2: an EXPLICIT launch value).
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

# Authoritative completion check: a v19_wave_state.jsonl record with
# "exit": 0 for this run name (persisted status, never log text).
chain_completed() {
  local RUN="$1"
  [ -f "$WAVE_STATE" ] || return 1
  grep "\"run\": \"$RUN\"" "$WAVE_STATE" | grep -q "\"exit\": 0"
}

record_chain() {  # run wave exit start end [pid]
  printf '{"run": "%s", "wave": %s, "exit": %s, "start": "%s", "end": "%s", "pid": "%s"}\n' \
    "$1" "$2" "$3" "$4" "$5" "${6:-unknown}" >> "$WAVE_STATE"
}

record_wave_summary() {  # wave band arch_run loss_run arch_pid loss_pid arch_exit loss_exit start end disposition
  printf '{"wave_summary": %s, "band": "%s", "arch_run": "%s", "loss_run": "%s", "arch_pid": "%s", "loss_pid": "%s", "arch_exit": %s, "loss_exit": %s, "start": "%s", "end": "%s", "disposition": "%s"}\n' \
    "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "${11}" >> "$WAVE_STATE"
}

chain_screen_alive() { screen -ls 2>/dev/null | grep -qF ".siderius-$1"$'\t'; }

# Launch one chain in its own screen; marker carries the exit code.
launch_chain() {
  local RUN="$1" SCOPE="$2" FILES="$3" FLAVOR="$4"
  local WS="$WS_ROOT/$RUN"
  local LOG="$WS_ROOT/${RUN}_$(date +%Y%m%d_%H%M).log"
  local MARKER="$EXIT_DIR/${RUN}.exit"
  local SESSION="siderius-$RUN"
  local ORDER
  ORDER="$(file_order_for_scope "$SCOPE")" || { log "ERROR $RUN: unknown scope $SCOPE"; return 1; }

  if [ -e "$WS" ] && [ "${V19_RESUME:-0}" != "1" ]; then
    log "ERROR $RUN: workspace exists — NOT launched (set V19_RESUME=1 for an intentional resume; completed chains are skipped automatically)"; return 1
  fi
  if chain_screen_alive "$RUN"; then log "ERROR $RUN: screen $SESSION already exists — NOT launched"; return 1; fi
  if ps -eo args | grep -v grep | grep -v v19_queue_runner | grep -qF "$WS_ROOT/$RUN"; then
    log "ERROR $RUN: live process referencing $WS_ROOT/$RUN — NOT launched"; return 1
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
  if chain_screen_alive "$RUN"; then
    local SPID
    SPID="$(screen -ls 2>/dev/null | grep -F ".$SESSION"$'\t' | grep -oE '^[[:space:]]*[0-9]+' | tr -d '[:space:]')"
    echo "$SPID" > "$EXIT_DIR/${RUN}.pid"
    log "LAUNCHED $RUN scope=$SCOPE monitored=$FILES order=$ORDER screen_pid=${SPID:-unknown} log=$LOG"
    return 0
  fi
  log "ERROR $RUN: screen did not start"
  return 1
}

chain_pid() {  # run -> recorded screen pid or "unknown"
  local F="$EXIT_DIR/$1.pid"
  if [ -f "$F" ]; then cat "$F"; else echo "unknown"; fi
}

marker_exit() {  # run -> exit code or "missing"
  local MARKER="$EXIT_DIR/$1.exit"
  if [ -f "$MARKER" ]; then sed -n 's/^EXIT=//p' "$MARKER" | head -1; else echo "missing"; fi
}

# Wait for a set of chains to finish; record each individually.
wait_and_record() {  # wave start_ts run1 [run2]
  local WAVE="$1" START="$2"; shift 2
  local RUNS=("$@")
  while true; do
    local alive=0 r
    for r in "${RUNS[@]}"; do chain_screen_alive "$r" && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 60
  done
  local END; END="$(date -u '+%Y-%m-%dT%H:%M:%S')"
  local all_ok=1
  for r in "${RUNS[@]}"; do
    local code; code="$(marker_exit "$r")"
    [ "$code" = "0" ] || all_ok=0
    record_chain "$r" "$WAVE" "${code/missing/-1}" "$START" "$END" "$(chain_pid "$r")"
    log "WAVE $WAVE chain $r finished: EXIT=$code"
  done
  return $(( 1 - all_ok ))
}

# Test hook: V19_QUEUE_NO_MAIN=1 source ... loads definitions only.
if [ "${V19_QUEUE_NO_MAIN:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

# --- argument parsing / O2 selection ---------------------------------------
ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --only)
      [ -n "${2:-}" ] || { echo "[v19-queue] --only requires a name list" >&2; exit 1; }
      ONLY="$2"; shift 2 ;;
    *) echo "[v19-queue] unknown argument: $1 (usage: v19_queue_runner.sh [--only <names>])" >&2; exit 1 ;;
  esac
done

mkdir -p "$WS_ROOT"

if [ -n "$ONLY" ]; then
  # Targeted SERIAL recovery: validate against the roster, then run the
  # selected chains one at a time (never pairs — always cross-band-safe).
  SELECTED=()
  while IFS= read -r line; do SELECTED+=("$line"); done < <(
    filter_roster "$ONLY" "${ROSTER[@]}"
  )
  [ "${#SELECTED[@]}" -gt 0 ] || { echo "[v19-queue] selection resolved to nothing (see error above)" >&2; exit 1; }
  log "targeted serial run: $ONLY"
  for spec in "${SELECTED[@]}"; do
    IFS=: read -r RUN SCOPE FILES FLAVOR <<< "$spec"
    if chain_completed "$RUN"; then log "SKIP $RUN: already completed (wave-state)"; continue; fi
    START="$(date -u '+%Y-%m-%dT%H:%M:%S')"
    if launch_chain "$RUN" "$SCOPE" "$FILES" "$FLAVOR"; then
      wait_and_record "only" "$START" "$RUN" || { log "targeted chain $RUN failed — stopping"; exit 1; }
    else
      log "targeted chain $RUN could not be launched — stopping"; exit 1
    fi
  done
  log "targeted serial run complete"
  exit 0
fi

# --- pairwise wave loop ----------------------------------------------------
log "v19 pairwise queue started: waves=${#WAVES[@]} max_conc=$MAX_CONC resume=${V19_RESUME:-0}"
for wave_spec in "${WAVES[@]}"; do
  IFS=: read -r WAVE SCOPE FILES <<< "$wave_spec"
  TAG="$(band_tag "$SCOPE")"
  ARCH_RUN="v19_arch_$TAG"
  LOSS_RUN="v19_loss_$TAG"

  NEEDED=()
  for RUN in "$ARCH_RUN" "$LOSS_RUN"; do
    if chain_completed "$RUN"; then
      log "WAVE $WAVE: $RUN already completed (wave-state) — skipped"
    else
      NEEDED+=("$RUN")
    fi
  done
  if [ "${#NEEDED[@]}" -eq 0 ]; then
    log "WAVE $WAVE (band $SCOPE): both chains already complete — next wave"
    continue
  fi

  log "WAVE $WAVE (band $SCOPE): launching ${NEEDED[*]}"
  START="$(date -u '+%Y-%m-%dT%H:%M:%S')"
  LAUNCHED=()
  for RUN in "${NEEDED[@]}"; do
    FLAVOR="arch"; [ "${RUN#v19_loss_}" != "$RUN" ] && FLAVOR="loss"
    if launch_chain "$RUN" "$SCOPE" "$FILES" "$FLAVOR"; then
      LAUNCHED+=("$RUN")
      sleep 90   # stagger the pair (V18r posture: bounded startup contention)
    else
      log "WAVE $WAVE: $RUN could not be launched — stopping the queue for operator review"
      log "  targeted restart: V19_RESUME=1 bash sdsc_submission_scripts/v19_queue_runner.sh --only $RUN"
      # Any already-launched partner keeps running; wait for it so its
      # status is recorded before the queue exits.
      [ "${#LAUNCHED[@]}" -gt 0 ] && wait_and_record "$WAVE" "$START" "${LAUNCHED[@]}"
      exit 1
    fi
  done

  if wait_and_record "$WAVE" "$START" "${LAUNCHED[@]}"; then
    DISPOSITION="complete"
  else
    DISPOSITION="failed"
  fi
  END_TS="$(date -u '+%Y-%m-%dT%H:%M:%S')"
  record_wave_summary "$WAVE" "$SCOPE" "$ARCH_RUN" "$LOSS_RUN" \
    "$(chain_pid "$ARCH_RUN")" "$(chain_pid "$LOSS_RUN")" \
    "$(marker_exit "$ARCH_RUN" | sed 's/missing/-1/')" \
    "$(marker_exit "$LOSS_RUN" | sed 's/missing/-1/')" \
    "$START" "$END_TS" "$DISPOSITION"
  if [ "$DISPOSITION" = "complete" ]; then
    log "WAVE $WAVE (band $SCOPE): both chains EXIT=0 — proceeding"
  else
    log "WAVE $WAVE (band $SCOPE): chain failure — QUEUE STOPPED before the next wave (frozen continuation policy)"
    log "  review logs, then: V19_RESUME=1 bash sdsc_submission_scripts/v19_queue_runner.sh --only <failed_run>"
    log "  after recovery, rerun the queue: completed chains are skipped and the earliest incomplete wave resumes"
    exit 1
  fi
done
log "ALL WAVES COMPLETE — v19 campaign queue finished"
exit 0
