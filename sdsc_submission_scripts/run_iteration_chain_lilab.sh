#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain Runner — LILAB (no Slurm)
# ---------------------------------------------------------------------------
# Full runbook (lilab + SDSC): docs/running_chain_test.md
# Shared logic: sdsc_submission_scripts/_chain_common.sh
# ---------------------------------------------------------------------------
# Lilab equivalent of run_iteration_chain.sh. Runs N iterations of the
# 5-agent workflow sequentially in the foreground using run_one_iteration.py
# as a Python subprocess. No Slurm.
#
# Iterations chain through manifest.json files exactly the same way as on
# SDSC — only the execution mechanism differs (foreground subprocess here,
# sbatch with --dependency=afterok on SDSC).
#
# Usage:
#   bash sdsc_submission_scripts/run_iteration_chain_lilab.sh \
#       --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
#       --num_iterations 2 \
#       --seed_paths /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
#       --max_rounds 5 \
#       --max_epochs 5 \
#       --human_advice_file sdsc_submission_scripts/human_advice_chain_test.json
# Optional flags for the tuner planner/reflector split:
#       --reflect_model_id gemini-2.5-flash    # cheaper model for the reflector
#       --reflect_provider openai            # entirely different provider for the reflector
#
# If iteration N fails, the chain stops immediately (set -e). Inspect
# ${WORKSPACE}/iter_NNN/ for the failure, fix, and rerun with a fresh
# --workspace (partial state can confuse manifest resolution).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_chain_common.sh"

PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNNER="${SCRIPT_DIR}/run_one_iteration.py"

# Choose Python interpreter: prefer `uv run python` (lilab dev setup),
# fall back to plain `python3` (when an activated venv has the deps).
if command -v uv >/dev/null 2>&1; then
    PY_CMD=(uv run python)
else
    PY_CMD=(python3)
fi

# Required by run_chain: execute one iteration in the foreground.
# SOURCE_PATHS and APP_ARGS are populated by the common framework.
submit_iteration() {
    local iter=$1
    (cd "$PROJECT_DIR" && "${PY_CMD[@]}" "$RUNNER" "${APP_ARGS[@]}")
}

parse_chain_args "$@"
load_advice_file
print_chain_header "LILAB (no Slurm)"
run_chain

echo ""
echo "############################################################"
echo "  CHAIN COMPLETE — ${NUM_ITERATIONS} iterations"
for ITER in $(seq 1 $NUM_ITERATIONS); do
    MANIFEST=$(printf "${WORKSPACE}/iter_%03d/manifest.json" "$ITER")
    if [ -f "$MANIFEST" ]; then
        echo "  iter $ITER → $MANIFEST"
    else
        echo "  iter $ITER → MISSING (this should not happen on a clean run)"
    fi
done
echo "############################################################"
