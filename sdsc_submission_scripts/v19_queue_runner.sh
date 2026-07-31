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
# VRAM: each chain carries a 12 GiB per-attempt admission cap
# (min(0.8 x physical, budget) in evaluate_vram_skill), and the PAIR is
# now admitted as a unit against an aggregate ceiling (operator decision
# 2026-07-31, core/runtime_control/pair_admission.py). 2 x 12 = 24 GiB
# sits below both the 28 GiB ceiling and this host's 29.30 GiB
# (30,000 MiB) per-user quota, so a pair at cap cannot trip the host
# watchdog. The earlier posture — 2 x 16 = 32 GiB with no combined-VRAM
# admission — assumed the card was the only limit; C12 measured the
# per-user quota being enforced by SIGTERM instead.
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
# Campaign identity (operator 2026-07-31). Every name the campaign
# produces derives from this one value — run names, workspaces, queue
# state, logs, summaries, screens — so a fresh campaign cannot collide
# with, or be mistaken for, the stopped uncalibrated-preflight campaign
# or any Gate. Required: there is no safe default, because a default
# would silently reuse someone else's identity.
CAMPAIGN_ID="${CAMPAIGN_ID:-v19}"
#: 10 iterations per chain (operator 2026-07-31), replacing the frozen
#: 20-iteration plan, to bound API cost, wall time and GPU use while
#: keeping multi-iteration scientific evolution.
#:
#: Deliberately NOT named NUM_ITERATIONS: this file sources
#: _chain_common.sh, which sets NUM_ITERATIONS=2 as its own default, so a
#: `${NUM_ITERATIONS:-10}` here silently resolved to 2. A campaign-scoped
#: name cannot be shadowed by a library default, now or later.
CAMPAIGN_ITERATIONS="${CAMPAIGN_ITERATIONS:-10}"
WS_ROOT="${WS_ROOT:-/home/klz/Data/SIDEREIS_DATA/v19}"
EXIT_DIR="${EXIT_DIR:-/tmp}"
MAX_CONC=2
LOGF="$WS_ROOT/${CAMPAIGN_ID}_queue_runner.log"
WAVE_STATE="$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl"
# C13: a wave cannot wait forever. On breach the queue STOPS and reports;
# it never kills a running chain on its own — that stays an operator act.
# 72 h per wave (operator 2026-07-31). The former 24 h was sized for a
# Gate; a formal wave at production portions runs far longer. This is a
# conservative safety bound, NOT a target — the 10-iteration treatment is
# expected to finish well inside it.
WAVE_WALL_SECONDS="${WAVE_WALL_SECONDS:-259200}"
#: 12 days for the whole campaign.
CAMPAIGN_WALL_SECONDS="${CAMPAIGN_WALL_SECONDS:-1036800}"
#: Hard token and estimated-cost ceilings for the campaign. Crossing
#: either stops the queue cleanly; neither may be raised mid-campaign
#: without explicit operator approval.
CAMPAIGN_TOKEN_CAP="${CAMPAIGN_TOKEN_CAP:-60000000}"
CAMPAIGN_COST_CAP_USD="${CAMPAIGN_COST_CAP_USD:-180}"
#: Conservative blended $/1M tokens used only when the ledger records no
#: billed cost, which it currently does not. Documented rather than
#: hidden, so the number in the report is auditable.
COST_PER_MTOK_USD="${COST_PER_MTOK_USD:-3.00}"
CAMPAIGN_START_EPOCH="$(date -u +%s)"
# C13: operator stop. Either touch this file or signal the runner; the
# queue then finishes what is already running and starts nothing new.
QUEUE_STOP_FILE="${QUEUE_STOP_FILE:-$WS_ROOT/STOP}"
#: Exit code a chain uses when it stopped on request (run_chain.sh).
CHAIN_STOP_EXIT_CODE=99
QUEUE_STOP_SIGNAL=""
#: Per-chain admission cap, mirrored from the frozen chain command so the
#: aggregate check and the launched command can never disagree.
PAIR_CAP_GIB="${PAIR_CAP_GIB:-12}"

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
  "${CAMPAIGN_ID}_arch_15_19:15-19:15,16,17,18,19:arch"
  "${CAMPAIGN_ID}_loss_15_19:15-19:15,16,17,18,19:loss"
  "${CAMPAIGN_ID}_arch_10_14:10-14:10,11,12,13,14:arch"
  "${CAMPAIGN_ID}_loss_10_14:10-14:10,11,12,13,14:loss"
  "${CAMPAIGN_ID}_arch_04_09:4-9:4,5,6,7,8,9:arch"
  "${CAMPAIGN_ID}_loss_04_09:4-9:4,5,6,7,8,9:loss"
  "${CAMPAIGN_ID}_arch_00_03:0-3:0,1,2,3:arch"
  "${CAMPAIGN_ID}_loss_00_03:0-3:0,1,2,3:loss"
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

_queue_note_signal() {
  QUEUE_STOP_SIGNAL="$1"
  log "STOP: $1 received — no further wave will be launched"
}
trap '_queue_note_signal SIGTERM' TERM
trap '_queue_note_signal SIGINT'  INT
trap '_queue_note_signal SIGHUP'  HUP

queue_stop_requested() {
  [ -n "$QUEUE_STOP_SIGNAL" ] && return 0
  [ -e "$QUEUE_STOP_FILE" ] && return 0
  return 1
}

# Explicit stopped-wave state, written on every stop path so the reason
# is a record rather than something inferred from log text.
record_queue_stop() {  # reason wave detail
  printf '{"queue_stopped": true, "reason": "%s", "signal": "%s", "wave": "%s", "detail": "%s", "stopped_at": "%s", "runner_pid": %s, "respawn": false}\n' \
    "$1" "${QUEUE_STOP_SIGNAL:-none}" "$2" "$3" \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$$" >> "$WAVE_STATE"
  log "QUEUE STOPPED ($1) at wave $2: $3"
}

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

# Campaign spend, summed from every chain's own token ledger. Returns
# "<tokens> <estimated_usd>". Reading the ledgers rather than keeping a
# running total means a queue restart cannot lose what was already spent.
campaign_spend() {
  # Delegated to Python: a ledger record nests BOTH a token total and a
  # character total, so a shell scan for "total" silently inflates the
  # number the cost cap depends on.
  "$REPO/.venv/bin/python" "$REPO/scripts/campaign_spend.py" \
      --root "$WS_ROOT" --campaign-id "$CAMPAIGN_ID" \
      --cost-per-mtok "$COST_PER_MTOK_USD" 2>/dev/null || echo "0 0.00"
}

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
      --num_iterations $CAMPAIGN_ITERATIONS \
      --auto_resume \
      --max_rounds 3 \
      --max_proposal_attempts 3 \
      --max_epochs 1 \
      --trial_portion 0.1 \
      --train_portion 0.1 \
      --eval_portion 0.1 \
      --formal_portion 0.1 \
      --formal_train_portion 1.0 \
      --formal_eval_portion 1.0 \
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
      --trial_vram_budget_gb 12 \
      --formal_vram_budget_gb 12 \
      --runtime_watchdog \
      --runtime_safety_factor 1.5 \
      --runtime_trial_safety_factor 3.0 \
      --runtime_formal_safety_factor 2.25 \
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
  local WAITED=0
  while true; do
    local alive=0 r
    for r in "${RUNS[@]}"; do chain_screen_alive "$r" && alive=1; done
    [ "$alive" = 0 ] && break
    if [ "$WAITED" -ge "$WAVE_WALL_SECONDS" ]; then
      # Bounded, and deliberately non-destructive: the chains keep running
      # and keep their workspaces; the QUEUE stops so an operator decides.
      record_queue_stop "wave_wall_cap_exceeded" "$WAVE" \
        "waited ${WAITED}s (cap ${WAVE_WALL_SECONDS}s) for: ${RUNS[*]}"
      return 1
    fi
    sleep 60
    WAITED=$(( WAITED + 60 ))
  done
  local END; END="$(date -u '+%Y-%m-%dT%H:%M:%S')"
  local all_ok=1
  for r in "${RUNS[@]}"; do
    local code; code="$(marker_exit "$r")"
    [ "$code" = "0" ] || all_ok=0
    if [ "$code" = "$CHAIN_STOP_EXIT_CODE" ]; then
      # The chain stopped on request. That is not a fault to restart from.
      log "WAVE $WAVE chain $r STOPPED on request (EXIT=$code) — no restart suggested"
      QUEUE_STOP_SIGNAL="${QUEUE_STOP_SIGNAL:-chain_stop_$r}"
    fi
    record_chain "$r" "$WAVE" "${code/missing/-1}" "$START" "$END" "$(chain_pid "$r")"
    log "WAVE $WAVE chain $r finished: EXIT=$code"
  done
  return $(( 1 - all_ok ))
}

# --- entry point ------------------------------------------------------------
# Everything above is definitions. main() below is the ONLY thing that
# touches the filesystem or launches a chain; the source-safe guard at
# the bottom of this file runs it on direct execution only.
main() {
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

  # Campaign wall cap.
  ELAPSED=$(( $(date -u +%s) - CAMPAIGN_START_EPOCH ))
  if [ "$ELAPSED" -ge "$CAMPAIGN_WALL_SECONDS" ]; then
    record_queue_stop "campaign_wall_cap_exceeded" "$WAVE" \
      "elapsed ${ELAPSED}s of ${CAMPAIGN_WALL_SECONDS}s before wave $WAVE"
    exit 1
  fi

  # Token / cost caps. Counted from the per-chain ledgers rather than a
  # running total the queue keeps, so a restart cannot lose the spend.
  read -r SPENT_TOKENS SPENT_COST <<< "$(campaign_spend)"
  log "WAVE $WAVE budget: ${SPENT_TOKENS} tokens (cap ${CAMPAIGN_TOKEN_CAP}), \$${SPENT_COST} (cap \$${CAMPAIGN_COST_CAP_USD}), elapsed ${ELAPSED}s of ${CAMPAIGN_WALL_SECONDS}s"
  if [ "$SPENT_TOKENS" -ge "$CAMPAIGN_TOKEN_CAP" ]; then
    record_queue_stop "token_cap_reached" "$WAVE" \
      "${SPENT_TOKENS} tokens >= cap ${CAMPAIGN_TOKEN_CAP}"
    exit 1
  fi
  if [ "$(printf '%.0f' "$SPENT_COST")" -ge "$CAMPAIGN_COST_CAP_USD" ]; then
    record_queue_stop "cost_cap_reached" "$WAVE" \
      "estimated \$${SPENT_COST} >= cap \$${CAMPAIGN_COST_CAP_USD}"
    exit 1
  fi

  # C13: an operator stop ends the QUEUE LOOP, not just one chain.
  if queue_stop_requested; then
    record_queue_stop "operator_stop_requested" "$WAVE" \
      "stop observed before wave $WAVE (band $SCOPE) was launched"
    exit "$CHAIN_STOP_EXIT_CODE"
  fi
  TAG="$(band_tag "$SCOPE")"
  ARCH_RUN="${CAMPAIGN_ID}_arch_$TAG"
  LOSS_RUN="${CAMPAIGN_ID}_loss_$TAG"

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

  # Host-aware aggregate admission — the same rule the Gate applies.
  # Per-chain caps bound one attempt; the host quota bounds the SUM.
  if ! PAIR_CHECK="$(.venv/bin/python -m core.runtime_control.pair_admission \
        --caps "$ARCH_RUN=$PAIR_CAP_GIB,$LOSS_RUN=$PAIR_CAP_GIB" 2>&1)"; then
    log "WAVE $WAVE PAIR ADMISSION: configured caps can exceed the ceiling"
    while IFS= read -r line; do log "  $line"; done <<< "$PAIR_CHECK"
    if [ "${ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-1}" != "1" ]; then
      record_queue_stop "pair_infeasible_under_host_quota" "$WAVE" \
        "configured caps for $ARCH_RUN + $LOSS_RUN exceed the aggregate ceiling"
      exit 1
    fi
    log "  proceeding: the BINDING guard is the per-attempt predicted-peak check"
  else
    while IFS= read -r line; do log "  $line"; done <<< "$PAIR_CHECK"
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
      # C13: a pair summary on EVERY exit path, including this one — an
      # aborted wave must not be the one case that leaves no summary.
      record_wave_summary "$WAVE" "$SCOPE" "$ARCH_RUN" "$LOSS_RUN" \
        "$(chain_pid "$ARCH_RUN")" "$(chain_pid "$LOSS_RUN")" \
        "$(marker_exit "$ARCH_RUN" | sed 's/missing/-1/')" \
        "$(marker_exit "$LOSS_RUN" | sed 's/missing/-1/')" \
        "$START" "$(date -u '+%Y-%m-%dT%H:%M:%S')" "launch_failed"
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
  if queue_stop_requested && [ "$DISPOSITION" != "complete" ]; then
    record_queue_stop "operator_stop_requested" "$WAVE" \
      "wave $WAVE ended under an operator stop — no further wave launched"
    exit "$CHAIN_STOP_EXIT_CODE"
  fi
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
}

# Source-safe entry guard. Sourcing this file for tests or to inspect the
# frozen command must NEVER launch a wave. `V19_QUEUE_NO_MAIN` is still
# honoured for existing callers, but it is no longer what protects us —
# an environment-only opt-out is one forgotten variable away from
# executing a launch path.
if [[ "${BASH_SOURCE[0]}" == "$0" ]] && [ "${V19_QUEUE_NO_MAIN:-0}" != "1" ]; then
  main "$@"
fi
