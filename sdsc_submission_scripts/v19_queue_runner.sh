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
# Authoritative per-chain status:
# $WS_ROOT/$CAMPAIGN_ID/queue_state/wave_state.jsonl (one JSON line per
# finished chain attempt: run, wave, exit, start, end) — NOT log text.
# A campaign interrupted BEFORE the V20 PR E move may additionally read
# its own pre-move $WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl, read-only
# and only when its stamp recorded that adoption at first start (BC-2).
# Exit codes come from per-chain markers ($EXIT_DIR/<run>.exit,
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
#: This script's own filename, for the live-process guard's
#: self-exclusion (D-E-7). Parameter expansion rather than
#: `$(basename …)`: no subshell, so no `set -e` surface, and it
#: matches the form already used for the admission helper's
#: `--runner` argument.
RUNNER_BASENAME="${BASH_SOURCE[0]##*/}"
# shellcheck source=_chain_common.sh
source "$REPO/sdsc_submission_scripts/_chain_common.sh"
# Campaign identity (operator 2026-07-31). Every name the campaign
# produces derives from this one value — run names, workspaces, queue
# state, logs, summaries, screens — so a fresh campaign cannot collide
# with, or be mistaken for, the stopped uncalibrated-preflight campaign
# or any Gate.
#
# `${VAR-default}`, NOT `${VAR:-default}` (E-C2b). The two forms differ on
# exactly one input and it is the dangerous one:
#
#   CAMPAIGN_ID unset            -> `v19`, the compatibility default
#   CAMPAIGN_ID explicitly empty -> stays empty, and the validator refuses
#
# `:-` treats an explicit empty value as if the variable were never set,
# so `CAMPAIGN_ID= bash v19_queue_runner.sh` would silently become `v19`
# — an operator who cleared the variable to avoid reusing an identity
# would get exactly the identity they were avoiding, and would then write
# into that campaign's control state. D-E-9 requires an empty id to be
# REFUSED, and with `:-` it could never reach the validator to be refused.
CAMPAIGN_ID="${CAMPAIGN_ID-v19}"
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
# --- campaign path resolution (V20 PR E, E-C2) -----------------------------
# Campaign identity used to live in a FILENAME PREFIX
# (`${CAMPAIGN_ID}_wave_state.jsonl`) under a shared root, and a prefix is
# easy to forget: QUEUE_STOP_FILE omitted it entirely, so ONE campaign's
# STOP halted every campaign sharing that root. That is the 08:17 incident.
# A directory cannot be forgotten the way a prefix can.
#
# WS_ROOT is a campaign COLLECTION root — its default value happens to be
# named `v19`, which looks like a campaign but is not one. Two campaigns
# under one collection root is the normal case and the case that broke.
#
# CAMPAIGN_HOME is the ONE overridable root; it moves a campaign
# coherently. The three directories below derive from it and are
# deliberately NOT independently overridable: separate overrides would let
# two campaigns be pointed at a single state directory, recreating the
# cross-campaign authority defect this PR exists to remove. A
# configuration surface that can reconstruct the defect is not a
# configuration surface.
#
# No mkdir here, and nothing at definition scope touches the filesystem:
# test_source_safe_entry.py asserts that merely sourcing this file creates
# nothing, and that guard must keep holding. The directories are created
# by the admission guard in main(), which validates CAMPAIGN_ID FIRST —
# these expansions are just strings until then, so a `..` id resolves a
# path here but can never reach a `mkdir`.
#
# The three subdirectory names are also declared in
# `core/campaign_identity.py` (CAMPAIGN_SUBDIRS), which is what actually
# creates them. The duplication is unavoidable — LOGF must resolve before
# the runner may call Python — so a parity test pins the two lists
# together instead.
CAMPAIGN_HOME="${CAMPAIGN_HOME:-$WS_ROOT/$CAMPAIGN_ID}"
CAMPAIGN_CONTROL_DIR="$CAMPAIGN_HOME/control"
QUEUE_STATE_DIR="$CAMPAIGN_HOME/queue_state"
PAIR_SUMMARY_DIR="$CAMPAIGN_HOME/pair_summaries"
CAMPAIGN_STAMP="$CAMPAIGN_CONTROL_DIR/campaign.json"

LOGF="$QUEUE_STATE_DIR/queue_runner.log"
WAVE_STATE="$QUEUE_STATE_DIR/wave_state.jsonl"
# --- pre-PR-E state, read only under adoption (E-C3, BC-2) -----------------
# Where this campaign's history lived before the move. It is READ-ONLY and
# only ever consulted when the campaign stamp records it as adopted; the
# interpolated ${CAMPAIGN_ID} is what keeps another campaign's file out of
# range. Nothing writes here, ever — BC-1.
LEGACY_WAVE_STATE="$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl"
# The legacy SHARED stop file. Observed and recorded at startup, never
# honoured and never deleted (BC-3): silently ignoring it would destroy
# the operator's ability to reconstruct the 08:17 incident, and honouring
# it would reproduce the defect.
LEGACY_GLOBAL_STOP="$WS_ROOT/STOP"
# Set from the admission decision in main(); empty means "no adoption",
# which is every campaign created after PR E.
ADOPTED_LEGACY_STATE=""
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
#
# BD-1: the DEFAULT moved into the campaign's own control directory
# (E-C2). It used to be `$WS_ROOT/STOP`, shared by every campaign under
# the root — stopping one stopped all of them. The explicit override
# survives for compatibility only: the docs table and
# test_c13_stop_semantics.py both pass it, and operator muscle memory
# expects it to work. It is NOT a general-purpose relocation knob, and a
# legacy `$WS_ROOT/STOP` is no longer consulted at all.
QUEUE_STOP_FILE="${QUEUE_STOP_FILE:-$CAMPAIGN_CONTROL_DIR/STOP}"
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

role_for_run() {  # RUN -> the role declared in the ROSTER, or fail
  # The ROSTER is the single source of truth for a chain's role: field 4 of
  # each entry. This looks it up instead of re-deriving it from the run
  # name.
  #
  # WHY THIS EXISTS. The wave path used to recover the role by stripping a
  # literal prefix:
  #
  #     FLAVOR="arch"; [ "${RUN#v19_loss_}" != "$RUN" ] && FLAVOR="loss"
  #
  # Run names are built from ${CAMPAIGN_ID}, so under any campaign id other
  # than "v19" the loss chain did not match, silently fell through to
  # "arch", and BOTH chains of every wave launched with
  # advice/workflow/v18r_arch_explorer.json (:271). The queue still showed
  # two chains, so the pair looked correct while both arms ran the same
  # treatment — a difference that would surface only at analysis time.
  # V20 launches with a new campaign id by definition, so it hit this on
  # wave 1.
  #
  # Note the fix is NOT s/v19_/v20_/. That would defer the same defect to
  # V21. The implicit name-encodes-role protocol is deleted: the role
  # travels from the roster to launch_chain and is never inferred.
  #
  # Fails closed. An unknown run or an empty role returns non-zero rather
  # than defaulting to "arch" — defaulting is exactly how the original
  # defect stayed invisible.
  local want="$1" spec name role
  for spec in "${ROSTER[@]}"; do
    IFS=: read -r name _ _ role <<< "$spec"
    if [ "$name" = "$want" ]; then
      [ -n "$role" ] || { echo "[role_for_run] roster entry for '$want' declares an empty role" >&2; return 1; }
      printf '%s\n' "$role"
      return 0
    fi
  done
  echo "[role_for_run] no roster entry for run '$want'" >&2
  return 1
}

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

# Authoritative completion check: a wave_state.jsonl record with
# "exit": 0 for this run name (persisted status, never log text).
#
# The predicate is byte-identical on both files (E-C3): the same
# `grep | grep -q` decides completion whether the evidence comes from
# this campaign's own state or from an adopted legacy file. Adoption may
# change WHICH file is readable; it must never change what "complete"
# means.
#
# The legacy read is gated on ADOPTED_LEGACY_STATE, which is set from the
# stamp at admission and is empty unless this campaign adopted a
# pre-PR-E file at its FIRST start (BC-2). It is deliberately NOT
# "consult legacy when the new state lacks a record": that per-record
# fallback would skip a launch on the strength of a file the campaign was
# never meant to obey, which is the §1 defect in a different costume.
# A campaign that was not granted adoption never opens a legacy path at
# all, however many records its own state is missing.
#
# An adopted file that is missing, unreadable or malformed yields no
# match and therefore no evidence — the chain is launched. Refusing here
# instead would hand a legacy file veto power over a new campaign.
_completed_in() {  # state_file run
  [ -f "$1" ] || return 1
  grep "\"run\": \"$2\"" "$1" | grep -q "\"exit\": 0"
}

chain_completed() {
  local RUN="$1"
  _completed_in "$WAVE_STATE" "$RUN" && return 0
  [ -n "$ADOPTED_LEGACY_STATE" ] || return 1
  _completed_in "$ADOPTED_LEGACY_STATE" "$RUN"
}

record_chain() {  # run wave exit start end [pid]
  printf '{"run": "%s", "wave": %s, "exit": %s, "start": "%s", "end": "%s", "pid": "%s"}\n' \
    "$1" "$2" "$3" "$4" "$5" "${6:-unknown}" >> "$WAVE_STATE"
}

# Record one wave: canonical JSONL first, then the derived per-wave view.
#
#   record_wave_summary <wave> <band> <band_tag> <start> <end> <disposition> <run>...
#
# Delegated to Python (D-E-3). The eleven-positional `printf` this
# replaces could describe exactly two chains called arch and loss; a
# positional shell formatter cannot emit a variable-length array, and a
# shell that hand-builds nested JSON is the hazard `campaign_spend` was
# already moved out of shell to avoid.
#
# The role comes from the ROSTER, never from the run name (D-E-6). When
# it cannot be resolved the field is left EMPTY and becomes `null` — a
# gap, never a guess. Such a record simply gets no arch/loss
# compatibility mirror, which is correct: an invented `arch_exit` is
# worse than an absent one, because a report would show it.
#
# Resolution failures here must not be able to destroy the summary
# itself. This function is called on EVERY wave exit path including the
# aborted-launch one, and the launcher's own rule is that an aborted wave
# must not be the one case that leaves no summary.
record_wave_summary() {  # wave band band_tag start end disposition run...
  local WAVE="$1" BAND="$2" TAG="$3" START="$4" END="$5" DISPOSITION="$6"; shift 6
  local args=() RUN ROLE PID CODE
  for RUN in "$@"; do
    ROLE=""; ROLE="$(role_for_run "$RUN")" || ROLE=""
    PID="unknown"; PID="$(chain_pid "$RUN")" || PID="unknown"
    CODE="missing"; CODE="$(marker_exit "$RUN")" || CODE="missing"
    args+=(--chain "$RUN:$ROLE:$PID:${CODE/missing/-1}")
  done

  # `set -e` is in effect and this function is called BARE, so errexit is
  # NOT suspended inside it. The guarded form is mandatory (§3a.4): a
  # plain assignment would terminate the runner at the failure, before
  # any of the classification below could run.
  local OUT="" RC=0
  OUT="$("$REPO/.venv/bin/python" "$REPO/scripts/record_wave_summary.py" \
      --canonical "$WAVE_STATE" \
      --derived-dir "$PAIR_SUMMARY_DIR" \
      --campaign-id "$CAMPAIGN_ID" \
      --wave "$WAVE" \
      --band "$BAND" \
      --band-tag "$TAG" \
      --start "$START" \
      --end "$END" \
      --disposition "$DISPOSITION" \
      "${args[@]}")" || RC=$?
  if [ "$RC" -eq 0 ]; then
    log "WAVE $WAVE summary recorded: $OUT"
    return 0
  fi

  # The two failures are NOT the same event and are not reported as one.
  # Exit 3 means the append-only evidence survived and only the derived
  # view is missing; exit 2 means nothing was written at all.
  log "WAVE $WAVE: FAILED to record the wave summary (rc=$RC)"
  log "  command: scripts/record_wave_summary.py --canonical $WAVE_STATE ... (reason on stderr)"
  if [ "$RC" -eq 3 ]; then
    log "  the CANONICAL record IS written; the derived per-wave summary is NOT."
    log "  the evidence is intact and $PAIR_SUMMARY_DIR can be rebuilt from $WAVE_STATE"
    record_queue_stop "wave_summary_derived_write_failed" "$WAVE" \
      "canonical record preserved; derived summary under $PAIR_SUMMARY_DIR not written"
  else
    log "  NOTHING was written for this wave summary."
    record_queue_stop "wave_summary_write_failed" "$WAVE" \
      "record_wave_summary.py exited $RC; no wave record persisted"
  fi
  exit 1
}

chain_screen_alive() { screen -ls 2>/dev/null | grep -qF ".siderius-$1"$'\t'; }

# Campaign spend, summed from every chain's own token ledger. Returns
# "<tokens> <estimated_usd>". Reading the ledgers rather than keeping a
# running total means a queue restart cannot lose what was already spent.
campaign_spend() {
  # Delegated to Python: a ledger record nests BOTH a token total and a
  # character total, so a shell scan for "total" silently inflates the
  # number the cost cap depends on.
  #
  # MEMBERSHIP COMES FROM THE ROSTER, explicitly. It used to be inferred
  # inside the Python from a `${CAMPAIGN_ID}_*` glob, which absorbed any
  # campaign whose id extended this one with an underscore -- `v20` counted
  # `v20_extra_*` as its own, and that total is what `token_cap_reached`
  # acts on. The ROSTER already declares exactly which runs a campaign has;
  # passing them removes the guess, exactly as `role_for_run` did for the
  # chain role.
  local args=() spec name
  for spec in "${ROSTER[@]}"; do
    IFS=: read -r name _ _ _ <<< "$spec"
    args+=(--run-name "$name")
  done
  #
  # FAIL-CLOSED. This used to end `2>/dev/null || echo "0 0.00"`, so ANY
  # failure of the accounting helper -- a missing interpreter, an unreadable
  # root, a refused membership list -- became "zero spent". Zero does not
  # read as "unknown": it reads as budget available, and it silently
  # disarms both the token and the cost cap. The queue would then launch
  # more work with no authoritative accounting behind it.
  #
  # The exit status and stderr are now preserved for the caller to act on.
  # Deciding what to do about a failure is the caller's job, not this
  # function's.
  "$REPO/.venv/bin/python" "$REPO/scripts/campaign_spend.py" \
      --root "$WS_ROOT" --campaign-id "$CAMPAIGN_ID" "${args[@]}" \
      --cost-per-mtok "$COST_PER_MTOK_USD"
}

# Admit this campaign to its home, or refuse. Prints "<outcome> <stamp>".
#
# Delegated to Python because the ORDER is the guarantee and one function
# has to own it: validate the id -> inspect the home -> validate any
# existing stamp -> create the directories -> publish the stamp. Two of
# those steps are refusals that must happen before a specific side effect
# (an invalid id before ANY mkdir; a foreign stamp before ANY write), and
# an order split between a shell script and a helper is not checkable.
#
# It also needs the `os.link` publish that makes "first writer wins" true
# under concurrency, which shell has no clean equivalent for.
admit_campaign() {
  "$REPO/.venv/bin/python" "$REPO/scripts/campaign_admission.py" \
      --campaign-id "$CAMPAIGN_ID" \
      --ws-root "$WS_ROOT" \
      --campaign-home "$CAMPAIGN_HOME" \
      --runner "${BASH_SOURCE[0]##*/}" \
      --runner-pid "$$" \
      --wave-state "$WAVE_STATE" \
      --legacy-wave-state "$LEGACY_WAVE_STATE"
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
  # The runner must not see ITSELF as a live process holding this
  # workspace. The exclusion used to be the literal string
  # `v19_queue_runner`, so a renamed or copied runner stopped excluding
  # itself and refused to launch anything — the same "the current
  # campaign's name is baked into generic logic" defect as D-E-6, one
  # level down (D-E-7).
  #
  # `-F` is not cosmetic. The basename contains a `.`, which as a REGEX
  # matches any character, so a plain `grep -v` would also exclude a
  # process named `v19_queue_runnerXsh` — widening the exclusion to
  # processes that are not this runner, which is the direction that
  # silently skips the guard. Fixed-string on both sides.
  if ps -eo args | grep -v grep | grep -vF -- "$RUNNER_BASENAME" | grep -qF -- "$WS_ROOT/$RUN"; then
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

# --- campaign admission (V20 PR E, E-C2) -----------------------------------
# The first thing main() does after parsing arguments, and BEFORE any
# state write, any STOP read, any log line and any launch. Nothing above
# this point touches the filesystem: argument parsing reports with
# `echo … >&2`, never `log`, because LOGF now lives in a directory this
# guard is what creates.
#
# FAIL-CLOSED, deliberately, and recorded as such (E-C2 §3). The sibling
# helper `campaign_spend` once ended `|| echo "0 0.00"`, and a swallowed
# failure there produced a zero spend that read as "budget available".
# Swallowing a failure HERE would be worse: it would skip the guard
# entirely and launch a campaign into a directory whose owner was never
# proven. There is no safe default identity, so an unusable answer refuses.
#
# `set -e` is in effect (`_chain_common.sh:40`, sourced at :61), so a bare
# `VAR="$(admit_campaign)"` would terminate the shell at the failure —
# before the diagnostic below could run. `|| ADMIT_RC=$?` makes the
# assignment part of a compound command, which `set -e` does not act on,
# so the refusal is reachable. (§3a.4)
#
# The reason is reported to STDERR and is deliberately NOT appended to the
# wave state: writing a record about campaign A's refused launch into
# whatever state lives at campaign B's home is exactly the cross-campaign
# write this PR removes — and on a refusal the state directory may not
# exist at all.
ADMIT_OUT=""
ADMIT_RC=0
ADMIT_OUT="$(admit_campaign)" || ADMIT_RC=$?
if [ "$ADMIT_RC" -ne 0 ]; then
  echo "[v19-queue] campaign admission REFUSED (rc=$ADMIT_RC)" >&2
  echo "[v19-queue]   campaign_id=$CAMPAIGN_ID" >&2
  echo "[v19-queue]   campaign_home=$CAMPAIGN_HOME" >&2
  echo "[v19-queue]   command: scripts/campaign_admission.py (reason above)" >&2
  echo "[v19-queue]   no directory created by this run, no chain launched" >&2
  exit 1
fi

# Line 1 is "<outcome> <stamp path>"; line 2 is the adopted legacy state
# or "-". Two lines, not three fields, because a path may contain a space.
# Pure parameter expansion — no subshell, so no `set -e` surface. The
# helper always prints both lines, and spells "none" as `-`, because
# command substitution strips trailing newlines and an empty line 2 would
# be indistinguishable from a missing one.
ADMIT_SUMMARY="${ADMIT_OUT%%$'\n'*}"
ADOPTED_LEGACY_STATE="${ADMIT_OUT#*$'\n'}"
if [ "$ADOPTED_LEGACY_STATE" = "-" ]; then ADOPTED_LEGACY_STATE=""; fi

# WS_ROOT holds the chain workspaces, which stay flat and are NOT scoped
# by campaign (§4.4 — run names already carry the id, and moving them
# would break campaign_spend.py and every historical report path).
mkdir -p "$WS_ROOT"

# BD-1 is operator-visible, so the resolved paths are logged at startup:
# an operator who touches the old shared STOP must be able to see, from
# the log alone, which file this campaign actually reads.
log "campaign admission: $ADMIT_SUMMARY"
log "  campaign_home=$CAMPAIGN_HOME"
log "  stop file=$QUEUE_STOP_FILE"
log "  wave state=$WAVE_STATE"
if [ -n "$ADOPTED_LEGACY_STATE" ]; then
  log "  legacy state ADOPTED (read-only, completion evidence only): $ADOPTED_LEGACY_STATE"
else
  log "  legacy state: not adopted — no pre-PR-E file is consulted"
fi

# BC-3: a legacy SHARED stop file is observed and recorded, never
# honoured and never deleted.
#
# It is the file that halted an unrelated campaign in the 08:17 incident.
# Silently ignoring it would destroy the operator's ability to
# reconstruct that; honouring it would reproduce the defect. Recording it
# is the only option that does neither, and archiving it stays a manual
# operator act (D-E-5).
#
# The record goes into the NEW wave state, so the observation belongs to
# the campaign that made it rather than to the shared root.
if [ -e "$LEGACY_GLOBAL_STOP" ]; then
  LEGACY_STOP_MTIME="$(stat -c %Y "$LEGACY_GLOBAL_STOP" 2>/dev/null || echo unknown)"
  log "LEGACY GLOBAL STOP observed: $LEGACY_GLOBAL_STOP (mtime=$LEGACY_STOP_MTIME)"
  log "  it has NO authority over this campaign and has NOT been removed;"
  log "  this campaign stops only on $QUEUE_STOP_FILE"
  printf '{"legacy_global_stop_observed": true, "path": "%s", "mtime": "%s", "observed_at": "%s", "runner_pid": %s, "honoured": false, "removed": false}\n' \
    "$LEGACY_GLOBAL_STOP" "$LEGACY_STOP_MTIME" \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$$" >> "$WAVE_STATE"
fi

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
# `MAX_CONC=2` used to appear here. It was deleted (D-E-3): it gated
# nothing — the wave roster is what decides how many chains launch — but
# a variable in a log line READS as a control, which is worse than
# absent. The line now reports `chains_per_wave` per wave, a measured
# fact, from the set actually launched.
log "v19 pairwise queue started: waves=${#WAVES[@]} resume=${V19_RESUME:-0}"
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
  # Budget accounting is a PRECONDITION for launching more work, so an
  # unreadable answer refuses the wave. It is deliberately NOT reported as
  # `token_cap_reached`: that would blame the campaign's own spend for an
  # infrastructure failure, and would tell an operator to raise a cap that
  # was never reached. The shape follows
  # `pair_infeasible_under_host_quota` -- a precondition the queue could
  # not satisfy, recorded and exited 1. Exit 99 would be wrong: it means
  # "stopped on request", which this is not.
  # `set -e` is in effect here -- `_chain_common.sh:40` sets it and this
  # runner sources it at :61. A bare `VAR="$(cmd)"` whose command fails
  # therefore terminates the shell IMMEDIATELY, before any check runs. An
  # earlier draft of this fix did exactly that: the queue still refused to
  # launch, but it died with no diagnostic, no `record_queue_stop` and no
  # recorded reason -- fail-closed by accident rather than by design, and
  # indistinguishable in the artifacts from a crash.
  #
  # `|| SPEND_RC=$?` makes the assignment part of a compound command, which
  # `set -e` does not act on, so the refusal below is reachable.
  SPEND_OUT=""
  SPEND_RC=0
  SPEND_OUT="$(campaign_spend)" || SPEND_RC=$?
  if [ "$SPEND_RC" -ne 0 ] || ! [[ "$SPEND_OUT" =~ ^[0-9]+[[:space:]]+[0-9]+\.[0-9]{2}$ ]]; then
    log "WAVE $WAVE: budget accounting UNAVAILABLE (rc=$SPEND_RC, output='${SPEND_OUT}')"
    log "  command: scripts/campaign_spend.py --root $WS_ROOT --campaign-id $CAMPAIGN_ID ..."
    log "  refusing to launch further work without authoritative spend"
    record_queue_stop "budget_accounting_unavailable" "$WAVE" \
      "campaign_spend exited $SPEND_RC with output '${SPEND_OUT}'; no chain launched"
    exit 1
  fi
  read -r SPENT_TOKENS SPENT_COST <<< "$SPEND_OUT"
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
    # D-B4 (V20). Fail-CLOSED by default: the aggregate check must pass or
    # the wave does not launch. Previously `:-1` meant "allow" unless the
    # operator said otherwise, so an infeasible pair proceeded silently and
    # the host watchdog was the first component to notice -- during C12 it
    # was, and what it produced was a kill.
    #
    # The override survives, but it must be asked for, it is announced, and
    # it is recorded. It is forbidden in the formal V20 Gate.
    if [ "${ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-0}" != "1" ]; then
      record_queue_stop "pair_infeasible_under_host_quota" "$WAVE" \
        "configured caps for $ARCH_RUN + $LOSS_RUN exceed the aggregate ceiling"
      exit 1
    fi
    log "  !! OVERRIDE ACTIVE: ALLOW_PAIR_CAP_OVERSUBSCRIPTION=1 -- the"
    log "  !! aggregate ceiling is knowingly oversubscribed (D-B4 default"
    log "  !! is fail-closed). The BINDING guard is now only the"
    log "  !! per-attempt predicted-peak check inside each chain."
    PAIR_OVERSUBSCRIPTION_OVERRIDE=1
  else
    while IFS= read -r line; do log "  $line"; done <<< "$PAIR_CHECK"
  fi

  log "WAVE $WAVE (band $SCOPE): launching ${NEEDED[*]} (chains_per_wave=${#NEEDED[@]})"
  START="$(date -u '+%Y-%m-%dT%H:%M:%S')"
  LAUNCHED=()
  for RUN in "${NEEDED[@]}"; do
    if ! FLAVOR="$(role_for_run "$RUN")"; then
      log "WAVE $WAVE: $RUN has no resolvable role in the ROSTER — stopping the queue for operator review"
      record_queue_stop "unresolvable_chain_role" "$WAVE" \
        "role_for_run failed for $RUN; refusing to launch rather than defaulting to arch"
      exit "$CHAIN_STOP_EXIT_CODE"
    fi
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
      record_wave_summary "$WAVE" "$SCOPE" "$TAG" \
        "$START" "$(date -u '+%Y-%m-%dT%H:%M:%S')" "launch_failed" \
        "$ARCH_RUN" "$LOSS_RUN"
      exit 1
    fi
  done

  if wait_and_record "$WAVE" "$START" "${LAUNCHED[@]}"; then
    DISPOSITION="complete"
  else
    DISPOSITION="failed"
  fi
  END_TS="$(date -u '+%Y-%m-%dT%H:%M:%S')"
  record_wave_summary "$WAVE" "$SCOPE" "$TAG" \
    "$START" "$END_TS" "$DISPOSITION" \
    "$ARCH_RUN" "$LOSS_RUN"
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
