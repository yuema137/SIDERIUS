#!/bin/bash
# ---------------------------------------------------------------------------
# V19 Gate 0 pair runner — band 15-19, exactly two concurrent chains
# (${GATE_RUN_PREFIX}_arch_15_19 + ${GATE_RUN_PREFIX}_loss_15_19, default
# prefix v19_c14), 2 iterations each.
# Frozen Gate plan: reports/v19_gate0_20260729_2209.md; protocol:
# docs/design/v19_priorities/v19_launch_protocol.md.
#
# Hardened after Gate 0 attempt 1 (2026-07-29, FAIL — PRODUCTION PATH):
#   * Stagger health check: the loss chain launches ONLY if the arch chain
#     has not already failed during the 90 s stagger. An arch failure
#     before the stagger elapses stops the Gate (summary disposition
#     "arch_failed_before_stagger", loss never launched).
#   * Identifier capture: the wrapper-shell PID is self-reported from
#     INSIDE each chain screen (`$$` → <run>.wrapperpid — cannot depend
#     on `screen -ls` parsing); the screen session id is captured
#     separately and labelled as such. Neither is ever invented: a
#     capture failure records "unknown".
#   * Completion: authoritative terminal state is the per-chain exit
#     marker ($EXIT_DIR/<run>.exit, EXIT=<n>), exactly as in V18r/queue.
#     Screen liveness is only a liveness hint; a screen that dies without
#     writing its marker is recorded as exit -1 after a bounded grace
#     (never busy-waited forever).
#   * Exit handling: both exit codes are read independently; the pair
#     summary is ALWAYS written (trap on runner exit); the runner exits
#     non-zero if either chain failed; no trailing command masks status.
#   * Wall cap: past WALL_CAP_SECONDS the runner records disposition
#     "wall_cap_exceeded" and exits non-zero. It never kills the chains
#     itself (operator decision per the frozen Gate failure policy).
#
# Single source of truth for the frozen chain command: gate_chain_args().
# The launch path and the arch/loss parity tests both consume it, so the
# launched command can never drift from the tested one.
#
# Env consumed: GATE_ROOT (default /home/klz/Data/SIDEREIS_DATA/v19/gate0),
# EXIT_DIR (default /tmp — bounded status markers only, never full logs),
# STAGGER_SECONDS (default 90), POLL_SECONDS (default 60),
# WALL_CAP_SECONDS (default 21600 = frozen 6 h Gate cap).
# Test hook: V19_GATE0_NO_MAIN=1 source ... loads definitions only.
# Runs inside `screen -S v19_gate0`.
# ---------------------------------------------------------------------------
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE_ROOT="${GATE_ROOT:-/home/klz/Data/SIDEREIS_DATA/v19/gate0}"
EXIT_DIR="${EXIT_DIR:-/tmp}"
STAGGER_SECONDS="${STAGGER_SECONDS:-90}"
POLL_SECONDS="${POLL_SECONDS:-60}"
WALL_CAP_SECONDS="${WALL_CAP_SECONDS:-21600}"
LAUNCH_SETTLE_SECONDS="${LAUNCH_SETTLE_SECONDS:-3}"

# C14 (operator 2026-07-31): explicit C14 run names, so this Gate's
# workspaces can never be confused with the 2026-07-30 Gate-0 attempt
# (now archived) or with formal V19. Overridable for a re-run under a
# different label; the launcher derives EVERY name from it, so the
# summary, the markers and the chain argv cannot disagree.
# `${VAR-default}`, NOT `${VAR:-default}` (E-C5, the same correction
# E-C2b made for CAMPAIGN_ID). `:-` treats an explicitly EMPTY value
# like an unset one, so `GATE_RUN_PREFIX= bash …` would silently run
# as `v19_c14` — an operator who cleared the variable to avoid reusing
# a Gate label would get exactly the label they were avoiding, and
# would overwrite that run's summary. An empty prefix must reach the
# validator to be refused, and with `:-` it never could.
GATE_RUN_PREFIX="${GATE_RUN_PREFIX-v19_c14}"
ARCH_RUN="${GATE_RUN_PREFIX}_arch_15_19"
LOSS_RUN="${GATE_RUN_PREFIX}_loss_15_19"
# --- Gate artifact scoping (V20 PR E, E-C5) --------------------------------
# These used to be the fixed names `gate0_pair_summary.json` and
# `gate0_runner.log`, so two Gate runs under one GATE_ROOT overwrote each
# other's summary and interleaved their logs — the same defect class the
# queue runner had, one level down. The prefix already names every
# workspace, marker and screen session; it now names these too.
#
# A PREFIX, not a directory (D-E-4): `$GATE_ROOT/$GATE_RUN_PREFIX/...`
# would be a new directory model for the Gate, and the Gate does not have
# one. Historical `gate0_*` files keep their names and their bytes;
# nothing reads, moves or deletes them.
#
# GATE_RUN_PREFIX becomes a FILENAME here, so main() validates it through
# the shared path-component rule before any of these paths is used.
SUMMARY="$GATE_ROOT/${GATE_RUN_PREFIX}_pair_summary.json"
#: Per-chain admission cap, mirrored from gate_chain_args() so the
#: aggregate check and the launched command can never disagree.
PAIR_CAP_GIB="${PAIR_CAP_GIB:-12}"
RUNNER_LOG="$GATE_ROOT/${GATE_RUN_PREFIX}_runner.log"

log() { echo "$(date -u '+%Y-%m-%d %H:%M:%S') $*" >> "$RUNNER_LOG"; }

# Frozen Gate 0 chain arguments (one per line, after `run_chain.sh`).
# ONLY three fields differ between the two chains: workspace, run_name,
# advice path. Everything else is byte-identical by construction.
gate_chain_args() {  # flavor (arch|loss)
  local FLAVOR="$1"
  local RUN="${GATE_RUN_PREFIX}_${FLAVOR}_15_19"
  cat <<EOF
--mode
lilab
--workspace
$GATE_ROOT/$RUN
--run_name
$RUN
--num_iterations
2
--auto_resume
--max_rounds
2
--max_proposal_attempts
3
--max_epochs
1
--data_scope
15-19
--health_gate_files
15,16,17,18,19
--enable_chain_incumbent_formal_gates
--order_strategy_override
sequential
--file_order_override
15,16,17,18,19
--enable_structured_health_feedback
--health_feedback_history_window_iterations
3
--health_feedback_history_max_entries_per_model
8
--skip_formal_min_delta
0.0
--bypass_formal_time_budget_min_delta
0.5
--trial_portion
0.02
--train_portion
1.0
--eval_portion
0.01
--formal_portion
0.02
--formal_train_portion
1.0
--formal_eval_portion
0.01
--trial_time_budget_minutes
5
--formal_time_budget_minutes
30
--trial_vram_budget_gb
12
--formal_vram_budget_gb
12
--runtime_watchdog
--runtime_safety_factor
1.5
--runtime_trial_safety_factor
3.0
--runtime_formal_safety_factor
2.25
--runtime_watchdog_safety_factor
3.5
--runtime_watchdog_floor_seconds
120
--formal_strategy
snapshot
--formal_round_strategy
inherit_best_trial
--exploration_mode
explore
--ml_lit_review_enabled
--llm_config
llm_configs/openai_tiered_v1.json
--advice
advice/workflow/v19_gate0_${FLAVOR}.json
--health_checks_config
configs/health_checks_baseline_observe_mode.yaml
EOF
}

gate_screen_alive() {  # run
  screen -ls 2>/dev/null | grep -qE "[0-9]+\.siderius-$1[[:space:]]"
}

gate_screen_session() {  # run -> screen session id (pid part) or "unknown"
  local SID
  SID="$(screen -ls 2>/dev/null | grep -E "[0-9]+\.siderius-$1[[:space:]]" \
        | grep -oE '[0-9]+' | head -1)"
  echo "${SID:-unknown}"
}

marker_exit() {  # run -> exit code, or "missing"
  local MARKER="$EXIT_DIR/$1.exit"
  if [ -f "$MARKER" ]; then sed -n 's/^EXIT=//p' "$MARKER" | head -1; else echo "missing"; fi
}

wrapper_pid() {  # run -> self-reported wrapper-shell PID or "unknown"
  local F="$EXIT_DIR/$1.wrapperpid"
  if [ -s "$F" ]; then head -1 "$F"; else echo "unknown"; fi
}

launch_gate_chain() {  # flavor (arch|loss)
  local FLAVOR="$1"
  local RUN="${GATE_RUN_PREFIX}_${FLAVOR}_15_19"
  local WS="$GATE_ROOT/$RUN"
  local LOG="$GATE_ROOT/${RUN}_$(date +%Y%m%d_%H%M).log"
  local SESSION="siderius-$RUN"

  if [ -e "$WS" ] && [ "${V19_GATE0_RESUME:-0}" != "1" ]; then
    log "ERROR $RUN: workspace exists — NOT launched (cold start required)"; return 1
  fi
  if gate_screen_alive "$RUN"; then
    log "ERROR $RUN: screen $SESSION already exists — NOT launched"; return 1
  fi
  if ps -eo args | grep -v grep | grep -v gate0_pair_runner | grep -qF "$GATE_ROOT/$RUN"; then
    log "ERROR $RUN: live process referencing $WS — NOT launched"; return 1
  fi

  rm -f "$EXIT_DIR/$RUN.exit" "$EXIT_DIR/$RUN.wrapperpid"
  touch "$LOG" || { log "ERROR $RUN: log path not writable"; return 1; }

  local CMD="bash sdsc_submission_scripts/run_chain.sh"
  local a
  while IFS= read -r a; do CMD+=" $(printf '%q' "$a")"; done < <(gate_chain_args "$FLAVOR")

  screen -L -Logfile "$LOG" -dmS "$SESSION" bash -lc "
    echo \$\$ > '$EXIT_DIR/$RUN.wrapperpid'
    set -euo pipefail
    cd '$REPO'
    .venv/bin/python -c 'import torch; assert torch.cuda.is_available()'
    set +e
    $CMD
    status=\$?
    set -e
    printf 'EXIT=%s\n' \"\$status\" > '$EXIT_DIR/$RUN.exit'
    exit \"\$status\"
  "
  sleep "$LAUNCH_SETTLE_SECONDS"
  if gate_screen_alive "$RUN" || [ -f "$EXIT_DIR/$RUN.exit" ]; then
    log "LAUNCHED $RUN session_id=$(gate_screen_session "$RUN") wrapper_pid=$(wrapper_pid "$RUN") log=$LOG"
    return 0
  fi
  log "ERROR $RUN: screen did not start"
  return 1
}

# Stagger health check: wait STAGGER_SECONDS in short steps; fail fast if
# the arch chain reaches a FAILED terminal state meanwhile. Returns 0 if
# the loss launch may proceed (arch alive, or arch already finished OK).
stagger_health_check() {
  local waited=0 step=5 code
  [ "$step" -gt "$STAGGER_SECONDS" ] && step="$STAGGER_SECONDS"
  while [ "$waited" -lt "$STAGGER_SECONDS" ]; do
    sleep "$step"; waited=$(( waited + step ))
    code="$(marker_exit "$ARCH_RUN")"
    if [ "$code" != "missing" ]; then
      if [ "$code" = "0" ]; then
        log "STAGGER: arch already finished OK (EXIT=0) — proceeding"; return 0
      fi
      log "STAGGER: arch FAILED during stagger (EXIT=$code) — loss NOT launched"; return 1
    fi
    if ! gate_screen_alive "$ARCH_RUN"; then
      log "STAGGER: arch screen gone without exit marker — loss NOT launched"; return 1
    fi
  done
  log "STAGGER: arch healthy after ${STAGGER_SECONDS}s"
  return 0
}

# Wait until every launched chain has an exit marker. A screen that dies
# without a marker gets a bounded grace (3 polls) then counts as exit -1.
# Past WALL_CAP_SECONDS the wait stops (chains are never killed here).
WALL_CAP_HIT=0
wait_for_markers() {  # run...
  local deadline=$(( $(date +%s) + WALL_CAP_SECONDS ))
  declare -A grace=()
  while :; do
    local pending=0 r code
    for r in "$@"; do
      code="$(marker_exit "$r")"
      [ "$code" != "missing" ] && continue
      if gate_screen_alive "$r"; then
        grace[$r]=0; pending=1
      else
        grace[$r]=$(( ${grace[$r]:-0} + 1 ))
        if [ "${grace[$r]}" -lt 3 ]; then pending=1; else
          log "WARN $r: screen gone, no exit marker after grace — recording exit -1"
        fi
      fi
    done
    [ "$pending" = 0 ] && return 0
    if [ "$(date +%s)" -ge "$deadline" ]; then
      WALL_CAP_HIT=1
      log "WALL CAP: ${WALL_CAP_SECONDS}s exceeded — stopping wait (chains NOT killed)"
      return 1
    fi
    sleep "$POLL_SECONDS"
  done
}

# Pair summary — ALWAYS written on runner exit, whatever the path.
START_TS=""
LOSS_LAUNCHED=0
DISPOSITION="runner_error"
SUMMARY_WRITTEN=0
write_summary() {
  [ "$SUMMARY_WRITTEN" = 1 ] && return 0
  SUMMARY_WRITTEN=1
  local END_TS AE LE LL
  END_TS="$(date -u '+%Y-%m-%dT%H:%M:%S')"
  AE="$(marker_exit "$ARCH_RUN")"; AE="${AE/missing/-1}"
  if [ "$LOSS_LAUNCHED" = 1 ]; then
    LE="$(marker_exit "$LOSS_RUN")"; LE="${LE/missing/-1}"; LL=true
  else
    LE=null; LL=false
  fi
  # `"gate"` was the literal "v19_gate0" regardless of which Gate run
  # produced the file, so two summaries were indistinguishable by their
  # own contents. It is the resolved prefix (D-E-4).
  printf '{"gate": "%s", "band": "15-19", "arch_run": "%s", "loss_run": "%s", "arch_wrapper_pid": "%s", "loss_wrapper_pid": "%s", "arch_screen_session": "%s", "loss_screen_session": "%s", "loss_launched": %s, "arch_exit": %s, "loss_exit": %s, "start": "%s", "end": "%s", "disposition": "%s"}\n' \
    "$GATE_RUN_PREFIX" "$ARCH_RUN" "$LOSS_RUN" \
    "$(wrapper_pid "$ARCH_RUN")" "$(wrapper_pid "$LOSS_RUN")" \
    "${ARCH_SESSION_ID:-unknown}" "${LOSS_SESSION_ID:-unknown}" \
    "$LL" "$AE" "$LE" "${START_TS:-unknown}" "$END_TS" "$DISPOSITION" > "$SUMMARY"
  log "SUMMARY written: arch_exit=$AE loss_exit=$LE disposition=$DISPOSITION"
}

# --- entry point ------------------------------------------------------------
# Everything above is definitions. main() below is the ONLY thing that
# touches the filesystem or launches a chain, and it runs only on direct
# execution (see the source-safe guard at the bottom of this file).
main() {
# --- GATE_RUN_PREFIX validation (V20 PR E, E-C5) ---------------------------
# The prefix names this Gate's workspaces, markers, screen sessions, log
# and summary, so an unsafe value would put a Gate artifact outside
# GATE_ROOT. Validated through the SAME rule the campaign id uses
# (`core.campaign_identity.validate_path_component`) — reached via a
# helper rather than re-spelled as a shell `case`, because a second copy
# of a security rule is how the two drift.
#
# THIS RUNNER HAS NO `errexit` (only `set -u`, :42 — unlike the queue
# runner, which inherits `-e` from _chain_common.sh). A failing command
# here does NOT terminate the shell, so the status must be checked
# explicitly. `if ! cmd` does that under either setting.
#
# Placed before `mkdir` and before the EXIT trap, deliberately. A refusal
# must not run `write_summary`, because `$SUMMARY`'s own path is built
# from the value being refused. A startup refusal therefore leaves no
# artifacts at all, which is the accurate representation: nothing ran.
if ! "$REPO/.venv/bin/python" "$REPO/scripts/validate_path_component.py" \
      --value "$GATE_RUN_PREFIX" --kind "GATE_RUN_PREFIX"; then
  echo "[v19-gate0] REFUSED: GATE_RUN_PREFIX is not a safe path component" >&2
  echo "[v19-gate0]   value: '$GATE_RUN_PREFIX'" >&2
  echo "[v19-gate0]   it names this Gate's workspaces, log and summary" >&2
  echo "[v19-gate0]   nothing was created and no chain was launched" >&2
  exit 2
fi

mkdir -p "$GATE_ROOT"
trap write_summary EXIT

# Host-aware aggregate admission (operator decision 2026-07-31). The
# per-chain cap answers "does one attempt fit the device"; on a shared
# host the binding limit is the per-user TOTAL. Asked here, before
# anything launches, so the host watchdog is never the first component
# to notice — during C12 it was, and what it produced was a kill.
if ! PAIR_CHECK="$(.venv/bin/python -m core.runtime_control.pair_admission \
      --caps "$ARCH_RUN=$PAIR_CAP_GIB,$LOSS_RUN=$PAIR_CAP_GIB" 2>&1)"; then
  log "PAIR ADMISSION: configured caps can exceed the aggregate ceiling"
  while IFS= read -r line; do log "  $line"; done <<< "$PAIR_CHECK"
  # D-B4 (V20). Fail-CLOSED by default: the aggregate check must pass or
  # the wave does not launch. Previously `:-1` meant "allow" unless the
  # operator said otherwise, so an infeasible pair proceeded silently and
  # the host watchdog was the first component to notice -- during C12 it
  # was, and what it produced was a kill.
  #
  # The override survives, but it must be asked for, it is announced, and
  # it is recorded. It is forbidden in the formal V20 Gate.
  if [ "${ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-0}" != "1" ]; then
    DISPOSITION="pair_infeasible_under_host_quota"; exit 1
  fi
  # D-B4: the override is FORBIDDEN in the formal V20 Gate. A Gate run
  # exists to produce a comparable, defensible result; one that knowingly
  # oversubscribes the host is neither, and allowing it here would mean
  # the strictest context in the project had the weakest guarantee.
  log "PAIR ADMISSION: override refused -- this is the formal V20 Gate"
  log "  ALLOW_PAIR_CAP_OVERSUBSCRIPTION may not be used here. Reduce the"
  log "  per-chain caps, or run this pair outside the Gate."
  DISPOSITION="pair_oversubscription_override_forbidden_in_gate"; exit 1
  log "  !! OVERRIDE ACTIVE: ALLOW_PAIR_CAP_OVERSUBSCRIPTION=1 -- the"
  log "  !! aggregate ceiling is knowingly oversubscribed (D-B4 default"
  log "  !! is fail-closed). The BINDING guard is now only the"
  log "  !! per-attempt predicted-peak check inside each chain."
  PAIR_OVERSUBSCRIPTION_OVERRIDE=1
else
  while IFS= read -r line; do log "  $line"; done <<< "$PAIR_CHECK"
fi
START_TS="$(date -u '+%Y-%m-%dT%H:%M:%S')"

if ! launch_gate_chain arch; then
  DISPOSITION="arch_launch_error"; exit 1
fi
ARCH_SESSION_ID="$(gate_screen_session "$ARCH_RUN")"

if ! stagger_health_check; then
  wait_for_markers "$ARCH_RUN" || true
  DISPOSITION="arch_failed_before_stagger"; exit 1
fi

if ! launch_gate_chain loss; then
  wait_for_markers "$ARCH_RUN" || true
  DISPOSITION="loss_launch_error"; exit 1
fi
LOSS_LAUNCHED=1
LOSS_SESSION_ID="$(gate_screen_session "$LOSS_RUN")"

if ! wait_for_markers "$ARCH_RUN" "$LOSS_RUN"; then
  [ "$WALL_CAP_HIT" = 1 ] && DISPOSITION="wall_cap_exceeded"
  exit 1
fi

AE="$(marker_exit "$ARCH_RUN")"; LE="$(marker_exit "$LOSS_RUN")"
if [ "$AE" = "0" ] && [ "$LE" = "0" ]; then
  DISPOSITION="pass_pending_analysis"
  log "GATE PAIR DONE: arch=0 loss=0"
  exit 0
fi
DISPOSITION="chain_failure"
log "GATE PAIR DONE: arch=$AE loss=$LE disposition=chain_failure"
exit 1
}

# Source-safe entry guard. Sourcing this file — for tests, or to inspect
# the frozen command with gate_chain_args — must NEVER launch anything.
# This replaced an environment-only opt-out that was easy to forget:
# on 2026-07-31 the runner was sourced without it while diffing the argv
# and executed its whole launch path. Nothing launched (the
# workspace-exists guard refused) but the pair summary was overwritten.
# `V19_GATE0_NO_MAIN` is still honoured so existing callers keep working,
# but it is no longer what protects us.
if [[ "${BASH_SOURCE[0]}" == "$0" ]] && [ "${V19_GATE0_NO_MAIN:-0}" != "1" ]; then
  main "$@"
fi
