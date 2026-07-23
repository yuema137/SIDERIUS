#!/bin/bash
# ---------------------------------------------------------------------------
# V18 Wave-1 launcher — 4 split-scope chains (docs/v18_split_run_plan.md,
# reports/v18_20260723.md). Audited per the 2026-07-23 pre-launch audit.
#
# Usage:
#   bash sdsc_submission_scripts/launch_v18_wave1.sh --dry-run   # verify only
#   bash sdsc_submission_scripts/launch_v18_wave1.sh             # LAUNCH
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
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

# Wave-1 roster: run_name : scope : monitored(all in-scope) : advice flavor
WAVE1=(
  "v18_loss_04_09:4-9:4,5,6,7,8,9:loss"
  "v18_arch_04_09:4-9:4,5,6,7,8,9:arch"
  "v18_loss_10_14:10-14:10,11,12,13,14:loss"
  "v18_arch_10_14:10-14:10,11,12,13,14:arch"
)

fail() { echo "[LAUNCH-ABORT] $*" >&2; exit 1; }

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
        --trial_time_budget_minutes 12 --formal_time_budget_minutes 120 \
        --trial_vram_budget_gb 10 --formal_vram_budget_gb 12 \
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
      --trial_time_budget_minutes 12 \
      --formal_time_budget_minutes 120 \
      --trial_vram_budget_gb 10 \
      --formal_vram_budget_gb 12 \
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
for spec in "${WAVE1[@]}"; do
  IFS=: read -r RUN SCOPE FILES FLAVOR <<< "$spec"
  launch_one "$RUN" "$SCOPE" "$FILES" "$FLAVOR"
  if [ "$DRY_RUN" = 0 ] && [ "$spec" != "${WAVE1[-1]}" ]; then
    echo "[stagger] 90 s before next launch"
    sleep 90
  fi
done
if [ "$DRY_RUN" = 1 ]; then echo "[done] wave-1 dry-run complete"; else echo "[done] wave-1 launch complete"; fi
