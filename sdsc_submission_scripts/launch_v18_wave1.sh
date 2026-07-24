#!/bin/bash
# ---------------------------------------------------------------------------
# V18r Wave-1 launcher — scientific Wave 1 in TWO execution phases
# (reports/v18_20260724.md; operator decision 2026-07-24: two-way
# parallelism to bound dynamic GPU timing contention).
#
#   Phase 1a: v18r_loss_04_09 + v18r_arch_04_09   (scope 4-9)
#   Phase 1b: v18r_loss_10_14 + v18r_arch_10_14   (scope 10-14;
#             launch ONLY after the Wave-1A checkpoint is approved)
#
# Usage:
#   bash sdsc_submission_scripts/launch_v18_wave1.sh 1a --dry-run  # verify
#   bash sdsc_submission_scripts/launch_v18_wave1.sh 1a            # LAUNCH 1a
#   bash sdsc_submission_scripts/launch_v18_wave1.sh 1b --dry-run
#   bash sdsc_submission_scripts/launch_v18_wave1.sh 1b            # LAUNCH 1b
#
# Environment overrides:
#   WS_ROOT      (default /workspace/DATA/SIDERIUS_DATA)
#   EXIT_DIR     (default /tmp)
#   V18_RESUME=1 allow reusing an existing workspace (intentional resume);
#                without it, an existing workspace ABORTS the launch.
#
# Guards implemented (audit §2/§8/§10):
#   * preflight: screen present, CUDA available, 20+20 TIDMAD files,
#     committed reference artifacts, LLM key loadable, disk space;
#   * stale exit markers removed BEFORE screen starts;
#   * explicit fresh-vs-resume decision per workspace (no silent reuse);
#   * duplicate screen-session names abort;
#   * each screen session is verified started before the 90 s stagger;
#   * chain exit code captured despite set -e and written as EXIT=<n>.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_ROOT="${WS_ROOT:-/workspace/DATA/SIDERIUS_DATA}"
EXIT_DIR="${EXIT_DIR:-/tmp}"
DATE="$(date +%Y%m%d_%H%M)"

fail() { echo "[LAUNCH-ABORT] $*" >&2; exit 1; }

# Phase argument is REQUIRED — there is no all-four invocation.
PHASE="${1:-}"
DRY_RUN=0
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1

# Rosters: run_name : scope : monitored(all in-scope) : advice flavor
# v18r_* = fresh relaunch campaign under the runtime-control protocol
# (reports/v18_20260724.md); the halted campaign is archived as legacy_v18_*.
WAVE1A=(
  "v18r_loss_04_09:4-9:4,5,6,7,8,9:loss"
  "v18r_arch_04_09:4-9:4,5,6,7,8,9:arch"
)
WAVE1B=(
  "v18r_loss_10_14:10-14:10,11,12,13,14:loss"
  "v18r_arch_10_14:10-14:10,11,12,13,14:arch"
)
case "$PHASE" in
  1a) ROSTER=("${WAVE1A[@]}") ;;
  1b) ROSTER=("${WAVE1B[@]}") ;;
  *)  fail "usage: launch_v18_wave1.sh {1a|1b} [--dry-run] — phase 1b requires an approved Wave-1A checkpoint" ;;
esac

preflight() {
  # screen is only needed for a real launch (documented prerequisite:
  # `apt-get install -y screen` on a fresh box); dry-run verifies commands.
  if [ "$DRY_RUN" = 0 ]; then
    command -v screen >/dev/null || fail "screen is not installed (apt-get install -y screen)"
  fi
  "$REPO/.venv/bin/python" - <<'PY' || fail "python preflight failed"
import glob, os, sys, torch
from execute_tools.data_paths import TIDMAD_DATA_DIR
assert torch.cuda.is_available(), "CUDA unavailable"
t = len(glob.glob(os.path.join(TIDMAD_DATA_DIR, "abra_training_????.h5")))
v = len(glob.glob(os.path.join(TIDMAD_DATA_DIR, "abra_validation_????.h5")))
assert t == 20 and v == 20, f"TIDMAD files incomplete: train={t} val={v}"
from execute_tools.build_anchor_map import default_anchor_map_path
assert os.path.isfile(default_anchor_map_path()), "committed anchor map missing"
from nodes.scoring_reference import load_reference_scores
load_reference_scores()  # raises if committed reference data unresolvable
from dotenv import dotenv_values
keys = dotenv_values(os.path.join(os.getcwd(), ".env"))
assert keys.get("OPENAI_API_KEY"), "OPENAI_API_KEY not present in .env"
print("preflight OK: CUDA + 20/20 data files + reference artifacts + LLM key")
PY
  mkdir -p "$WS_ROOT" || fail "cannot create WS_ROOT: $WS_ROOT"
  local free_gb
  free_gb=$(df --output=avail -BG "$WS_ROOT" | tail -1 | tr -dc '0-9')
  [ "$free_gb" -ge 200 ] || fail "less than 200G free at $WS_ROOT (${free_gb}G)"
  echo "[preflight] disk free at $WS_ROOT: ${free_gb}G"
}

launch_one() {
  local RUN="$1" SCOPE="$2" FILES="$3" FLAVOR="$4"
  local WS="$WS_ROOT/$RUN"
  local LOG="$WS_ROOT/${RUN}_${DATE}.log"
  local MARKER="$EXIT_DIR/${RUN}.exit"
  local SESSION="siderius-$RUN"

  # Fresh-vs-resume: explicit decision, never silent reuse (audit §8).
  if [ -e "$WS" ] && [ "${V18_RESUME:-0}" != "1" ]; then
    fail "workspace $WS already exists — set V18_RESUME=1 for an intentional resume, or remove/rename it for a fresh start"
  fi
  # Duplicate screen-session guard (audit §8/§10).
  if screen -ls 2>/dev/null | grep -qF ".$SESSION"$'\t'; then
    fail "a screen session named $SESSION already exists — quit it first"
  fi

  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] $RUN scope=$SCOPE monitored=$FILES advice=v17_${FLAVOR}_explorer.json"
    ( cd "$REPO" && bash sdsc_submission_scripts/run_chain.sh --mode lilab --dry-run \
        --workspace "$WS" --run_name "$RUN" \
        --num_iterations 20 --auto_resume --max_rounds 3 --max_epochs 1 \
        --data_scope "$SCOPE" --health_gate_files "$FILES" \
        --skip_formal_min_delta 0.0 --bypass_formal_time_budget_min_delta 0.5 \
        --trial_time_budget_minutes 20 --formal_time_budget_minutes 120 \
        --trial_vram_budget_gb 16 --formal_vram_budget_gb 16 \
        --runtime_watchdog --runtime_safety_factor 1.5 \
        --runtime_watchdog_floor_seconds 120 \
        --formal_strategy snapshot --formal_round_strategy inherit_best_trial \
        --exploration_mode explore --ml_lit_review_enabled \
        --llm_config llm_configs/openai_tiered_v1.json \
        --advice "advice/workflow/v17_${FLAVOR}_explorer.json" \
        --health_checks_config configs/health_checks_baseline_observe_mode.yaml \
        | grep -E "Data scope|HealthGate       |DRY-RUN COMPLETE" )
    return 0
  fi

  # Stale exit marker removed BEFORE screen starts (audit §2).
  rm -f "$MARKER"
  touch "$LOG" || fail "log path not writable: $LOG"

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
      --runtime_watchdog_floor_seconds 120 \
      --formal_strategy snapshot \
      --formal_round_strategy inherit_best_trial \
      --exploration_mode explore \
      --ml_lit_review_enabled \
      --llm_config llm_configs/openai_tiered_v1.json \
      --advice 'advice/workflow/v17_${FLAVOR}_explorer.json' \
      --health_checks_config configs/health_checks_baseline_observe_mode.yaml
    status=\$?
    set -e
    printf 'EXIT=%s\n' \"\$status\" > '$MARKER'
    exit \"\$status\"
  "
  # Verify the session actually started before staggering (audit §10).
  sleep 2
  screen -ls | grep -qF ".$SESSION"$'\t' || fail "screen session $SESSION did not start"
  echo "[launched] $SESSION  log=$LOG  marker=$MARKER"
}

preflight
for spec in "${ROSTER[@]}"; do
  IFS=: read -r RUN SCOPE FILES FLAVOR <<< "$spec"
  launch_one "$RUN" "$SCOPE" "$FILES" "$FLAVOR"
  if [ "$DRY_RUN" = 0 ] && [ "$spec" != "${ROSTER[-1]}" ]; then
    echo "[stagger] 90 s before next launch"
    sleep 90
  fi
done
if [ "$DRY_RUN" = 1 ]; then echo "[done] wave-$PHASE dry-run complete"; else echo "[done] wave-$PHASE launch complete"; fi
