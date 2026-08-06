#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS V20 — OFFICIAL PRODUCTION CAMPAIGN LAUNCHER
# ---------------------------------------------------------------------------
# Role   : the one repository-controlled entry point for a formal V20
#          scientific campaign. It carries the frozen production posture so
#          the posture is a property of the REPOSITORY, not of whether an
#          operator remembered a thirty-flag command line.
#
# Why this file exists (audit findings M1, M2, M4 — 2026-08-06):
#
#   M1  The hand-written launch command dropped every runtime safety control
#       V19 ran under: no trial/formal time budget, no watchdog, safety
#       factor 1.0 instead of 1.5/3.0/2.25/3.5, watchdog floor 60 s instead
#       of 120, no VRAM budgets. `--mode lilab` has no per-iteration
#       timeout and the LLM bridge retries quota exhaustion forever by
#       design, so nothing bounded a hung iteration.
#   M2  `run_chain.sh` writes no log. The monitoring instructions pointed at
#       a `<run>.log` that nothing created; on a disconnect the campaign's
#       whole stdout was lost.
#   M4  With no `--llm_config`, every node fell through to the parser
#       default `gemini-3.1-pro-preview`. V19 ran the OpenAI tiered config.
#
# Frozen posture: docs/design/v20_priorities/v20_prelaunch_completion_mandate.md
#                 Part II §10. Change it THERE first, then here.
#
# Usage:
#   bash sdsc_submission_scripts/launch_v20_campaign.sh \
#       --workspace /home/klz/Data/SIDEREIS_DATA/v20/<RUN> \
#       --run_name <RUN> \
#       --num_iterations <N>
#
#   Add --dry-run to print the exact chain command without side effects.
#   Add --foreground to run without screen (acceptance testing).
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

WORKSPACE=""
RUN_NAME=""
NUM_ITERATIONS=""
DRY_RUN=0
FOREGROUND=0
# Two V19 production features the operator's frozen §10 list does not
# mention. Defaulting them ON would silently pick a posture nobody froze;
# defaulting them OFF and hiding it would do the same. So they are explicit,
# OFF by default (matching §10 literally), and reported in the V19->V20
# parity table as needing an operator ruling.
LIT_REVIEW=0
STRUCTURED_HEALTH_FEEDBACK=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workspace)       WORKSPACE="$2"; shift 2 ;;
        --run_name)        RUN_NAME="$2"; shift 2 ;;
        --num_iterations)  NUM_ITERATIONS="$2"; shift 2 ;;
        --dry-run)         DRY_RUN=1; shift ;;
        --foreground)      FOREGROUND=1; shift ;;
        --ml_lit_review_enabled)             LIT_REVIEW=1; shift ;;
        --enable_structured_health_feedback) STRUCTURED_HEALTH_FEEDBACK=1; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$WORKSPACE" ] || [ -z "$RUN_NAME" ] || [ -z "$NUM_ITERATIONS" ]; then
    echo "Required: --workspace DIR --run_name NAME --num_iterations N" >&2
    exit 1
fi
if ! [[ "$NUM_ITERATIONS" =~ ^[0-9]+$ ]] || [ "$NUM_ITERATIONS" -lt 1 ]; then
    echo "--num_iterations must be a positive integer (got '$NUM_ITERATIONS')" >&2
    exit 1
fi

LLM_CONFIG="llm_configs/openai_tiered_pro.json"
if [ ! -f "${PROJECT_DIR}/${LLM_CONFIG}" ]; then
    # M4 is the whole point of this launcher: without the file the chain
    # would fall through to the Gemini default, which is the defect.
    echo "ERROR: frozen production LLM config missing: ${PROJECT_DIR}/${LLM_CONFIG}" >&2
    exit 1
fi

# --- the frozen posture (mandate Part II §10) ------------------------------
CHAIN_ARGS=(
    --mode lilab
    --workspace "$WORKSPACE"
    --run_name "$RUN_NAME"
    --num_iterations "$NUM_ITERATIONS"
    --auto_resume

    # §10.1 LLM — explicit, never the parser default
    --llm_config "$LLM_CONFIG"

    # §10.2 scientific policy
    --healthgate_mode blocking
    --result_authority scientific
    --enable_chain_incumbent_formal_gates
    --skip_formal_min_delta -1.0
    --bypass_formal_time_budget_min_delta 0.5
    --order_strategy_override sequential

    # §10.4 production workload
    --max_rounds 3
    --max_epochs 1
    --max_proposal_attempts 3
    --trial_portion 0.1
    --train_portion 0.1
    --eval_portion 0.1
    --formal_portion 0.1
    --formal_train_portion 1.0
    --formal_eval_portion 1.0
    --formal_strategy snapshot
    --formal_round_strategy full_clone

    # §10.3 runtime safety posture, inherited from V19
    --trial_time_budget_minutes 20
    --formal_time_budget_minutes 120
    --runtime_watchdog
    --runtime_safety_factor 1.5
    --runtime_trial_safety_factor 3.0
    --runtime_formal_safety_factor 2.25
    --runtime_watchdog_safety_factor 3.5
    --runtime_watchdog_floor_seconds 120
    --trial_vram_budget_gb 12
    --formal_vram_budget_gb 12

    # M5 — a resource verdict stops the phase; an evidence gap is recorded
    --gpu_admission_enforcement enforce_resource_limits
)

[ "$LIT_REVIEW" -eq 1 ] && CHAIN_ARGS+=(--ml_lit_review_enabled)
[ "$STRUCTURED_HEALTH_FEEDBACK" -eq 1 ] && CHAIN_ARGS+=(--enable_structured_health_feedback)

# §10.5 validation-only features are absent BY CONSTRUCTION: this launcher
# has no flag that could emit --is_pseudo_llm, --is_pseudo_training,
# --validation_fixed_candidate_plan or --validation_max_portion. There is
# nothing to forget to turn off.

LOG_FILE="${WORKSPACE%/}.log"
SESSION="v20_${RUN_NAME}"

echo "############################################################"
echo "  SIDERIUS V20 PRODUCTION CAMPAIGN"
echo "  workspace   : $WORKSPACE"
echo "  run_name    : $RUN_NAME"
echo "  iterations  : $NUM_ITERATIONS"
echo "  llm_config  : $LLM_CONFIG"
echo "  logfile     : $LOG_FILE"
echo "  lit review  : $([ "$LIT_REVIEW" -eq 1 ] && echo on || echo off)"
echo "  health fb   : $([ "$STRUCTURED_HEALTH_FEEDBACK" -eq 1 ] && echo on || echo off)"
echo "  posture     : blocking + scientific, watchdog ON,"
echo "                trial<=20min formal<=120min, VRAM 12/12 GB,"
echo "                admission=enforce_resource_limits, order=sequential"
echo "############################################################"

if [ "$DRY_RUN" -eq 1 ]; then
    CHAIN_ARGS+=(--dry-run)
    echo "[DRY-RUN] chain command:"
    printf '  bash %s/run_chain.sh' "$SCRIPT_DIR"
    printf ' %q' "${CHAIN_ARGS[@]}"
    echo
    SIDERIUS_ALLOW_LAUNCH=1 bash "${SCRIPT_DIR}/run_chain.sh" "${CHAIN_ARGS[@]}"
    exit 0
fi

mkdir -p "$(dirname "$LOG_FILE")"

if [ "$FOREGROUND" -eq 1 ]; then
    # M2: still logged. `tee` keeps the operator's terminal live while the
    # durable copy is written, so a foreground acceptance run leaves the
    # same evidence a detached one does.
    bash "${SCRIPT_DIR}/run_chain.sh" "${CHAIN_ARGS[@]}" 2>&1 | tee -a "$LOG_FILE"
    exit "${PIPESTATUS[0]}"
fi

# M2: detached + logged. `screen -L -Logfile` is the mechanism V19 ran
# under; nothing new is introduced here, and logging stays out of the
# scientific runtime entirely.
touch "$LOG_FILE" || { echo "ERROR: log path not writable: $LOG_FILE" >&2; exit 1; }
screen -L -Logfile "$LOG_FILE" -dmS "$SESSION" bash -lc "
    cd '$PROJECT_DIR'
    bash '${SCRIPT_DIR}/run_chain.sh' $(printf '%q ' "${CHAIN_ARGS[@]}")
"
sleep 2
if screen -ls 2>/dev/null | grep -qF ".$SESSION"; then
    echo "LAUNCHED  session=$SESSION  log=$LOG_FILE"
    echo "  attach : screen -r $SESSION"
    echo "  follow : tail -f $LOG_FILE"
    echo "  stop   : touch $WORKSPACE/STOP"
    echo "  resume : re-run this script (auto-resume is on)"
else
    echo "ERROR: screen session did not start; see $LOG_FILE" >&2
    exit 1
fi
