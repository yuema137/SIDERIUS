#!/usr/bin/env bash
# launch_v11_v4.sh — V4-locked launch wrapper for SIDERIUS V11 chains.
#
# Encapsulates the V4 contract so the execution environment cannot drift
# from the guidance in tuner_advice/{explore_novel,exploit_cnn}_v4.json:
# every constant in the V4 contract block below is hardcoded and not
# overrideable from the call site. Mode-dependent values (workspace, advice
# path, run name) are derived from the two positional arguments.
#
# Usage:
#   bash sdsc_submission_scripts/launch_v11_v4.sh <MODE> <TAG>
#
# MODE: "explore" or "exploit"
# TAG:  short identifier (e.g. 0503_v4); used in run_name and workspace.
#
# Examples:
#   bash sdsc_submission_scripts/launch_v11_v4.sh explore 0503_v4
#   bash sdsc_submission_scripts/launch_v11_v4.sh exploit 0503_v4

set -euo pipefail

MODE="${1:-}"
TAG="${2:-}"

if [[ -z "$MODE" || -z "$TAG" ]]; then
    echo "Usage: $0 <explore|exploit> <TAG>" >&2
    echo "  e.g.: $0 explore 0503_v4" >&2
    exit 2
fi

case "$MODE" in
    explore)
        ADVICE="tuner_advice/explore_novel_v4.json"
        RUN_NAME="explore_novel_${TAG}"
        ;;
    exploit)
        ADVICE="tuner_advice/exploit_cnn_v4.json"
        RUN_NAME="exploit_cnn_${TAG}"
        ;;
    *)
        echo "Error: MODE must be 'explore' or 'exploit', got '$MODE'" >&2
        exit 2
        ;;
esac

WORKSPACE="/home/klz/Data/SIDEREIS_DATA/exploration_${RUN_NAME}"

# Resolve repo root from the script's own location so the launcher works
# regardless of the caller's cwd.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"
RUNNER="$REPO_ROOT/run_exploration_adaptive.py"

if [[ ! -x "$PYTHON" ]]; then
    echo "Error: project venv python not found at $PYTHON" >&2
    exit 3
fi
if [[ ! -f "$ADVICE" ]]; then
    echo "Error: advice file not found at $ADVICE" >&2
    exit 3
fi

echo "================================================================"
echo "SIDERIUS V11 — V4-locked launch"
echo "  MODE:               $MODE"
echo "  TAG:                $TAG"
echo "  RUN_NAME:           $RUN_NAME"
echo "  WORKSPACE:          $WORKSPACE"
echo "  ADVICE:             $ADVICE"
echo "  llm_config:         llm_configs/openai_tiered_v1.json"
echo "  --- V4 contract ---"
echo "  max_iterations:               30"
echo "  max_rounds:                   6"
echo "  trial_portion:                0.05"
echo "  eval_portion:                 0.1"
echo "  trial_time_budget_minutes:    20"
echo "  formal_time_budget_minutes:   180"
echo "  formal_round_strategy:        inherit_best_trial"
echo "  exploration_mode:             $MODE"
echo "================================================================"

exec "$PYTHON" "$RUNNER" \
    --run_name "$RUN_NAME" \
    --workspace "$WORKSPACE" \
    --advice "$ADVICE" \
    --llm_config "llm_configs/openai_tiered_v1.json" \
    --max_iterations 30 \
    --max_rounds 6 \
    --trial_portion 0.05 \
    --eval_portion 0.1 \
    --trial_time_budget_minutes 20 \
    --formal_time_budget_minutes 180 \
    --formal_round_strategy inherit_best_trial \
    --exploration_mode "$MODE"
