#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain Orchestrator — SDSC (Slurm)
# ---------------------------------------------------------------------------
# Full runbook (lilab + SDSC): docs/running_chain_test.md
# Shared logic: sdsc_submission_scripts/_chain_common.sh
# ---------------------------------------------------------------------------
# SDSC equivalent of run_iteration_chain_lilab.sh. Submits N iteration
# jobs in sequence using --dependency=afterok for automatic chaining.
# Each job's source paths = original seeds + all previous iterations'
# manifests (resolved at job execution time via the @manifest: prefix).
#
# Iterations chain through manifest.json files exactly the same way as
# on lilab — only the execution mechanism differs (sbatch with
# --dependency=afterok here, foreground subprocess on lilab).
#
# Usage:
#   bash sdsc_submission_scripts/run_iteration_chain.sh \
#       --workspace /expanse/lustre/projects/ddp433/ym137/exploration_v1 \
#       --num_iterations 10 \
#       --seed_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \
#       --max_rounds 5 \
#       --max_epochs 5 \
#       --human_advice_file sdsc_submission_scripts/human_advice_chain_test.json \
#       --partition gpu-shared \
#       --time 06:00:00 \
#       --mem 24G
#
# If iteration N fails, iterations N+1..M are blocked by --dependency=afterok
# and automatically cancelled by --kill-on-invalid-dep=yes. Resubmit them
# (with a fresh workspace) after fixing iteration N.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/_chain_common.sh"

PROJECT_DIR="/home/ym137/SIDERIUS"
SLURM_SCRIPT="${PROJECT_DIR}/sdsc_submission_scripts/submit_one_iteration.slurm"

# State carried across iterations: previous Slurm job id for dependency chain.
PREV_JOB_ID=""
SUBMITTED_JOBS=()

# Required by run_chain: submit one iteration as a Slurm job depending on
# the previous one. SOURCE_PATHS and APP_ARGS are populated by the common
# framework.
submit_iteration() {
    local iter=$1

    local SBATCH_ARGS=(
        --partition="$PARTITION"
        --nodes=1
        --ntasks=1
        --gpus="$GPUS"
        --mem="$MEM"
        --time="$TIME"
        --cpus-per-task="$CPUS"
    )

    if [ -n "$PREV_JOB_ID" ]; then
        # afterok: only run if the previous job succeeds.
        # kill-on-invalid-dep=yes: auto-cancel if previous job fails,
        # so we don't leave zombies in the queue.
        SBATCH_ARGS+=(--dependency="afterok:${PREV_JOB_ID}")
        SBATCH_ARGS+=(--kill-on-invalid-dep=yes)
        echo "  (depends on job $PREV_JOB_ID)"
    fi

    local OUTPUT JOB_ID
    OUTPUT=$(sbatch "${SBATCH_ARGS[@]}" "$SLURM_SCRIPT" "${APP_ARGS[@]}")
    JOB_ID=$(echo "$OUTPUT" | grep -oP '\d+$')
    if [ -z "$JOB_ID" ]; then
        echo "[FAIL] Could not parse job ID from sbatch output:" >&2
        echo "$OUTPUT" >&2
        exit 1
    fi

    echo "  Job ID: $JOB_ID"
    SUBMITTED_JOBS+=("$iter:$JOB_ID")
    PREV_JOB_ID="$JOB_ID"
}

parse_chain_args "$@"
load_advice_file
print_chain_header "SDSC (Slurm)"
echo "  Slurm: ${PARTITION}, ${GPUS} GPU, ${MEM}, ${TIME}, ${CPUS} CPUs"
run_chain

echo ""
echo "############################################################"
echo "  CHAIN SUBMITTED — ${NUM_ITERATIONS} iterations"
JOB_IDS_ONLY=()
for entry in "${SUBMITTED_JOBS[@]}"; do
    IFS=':' read -r ITER JOB_ID <<< "$entry"
    echo "  iter $ITER → job $JOB_ID"
    JOB_IDS_ONLY+=("$JOB_ID")
done
echo ""
echo "  Monitor with: squeue -u \$USER"
echo "  Cancel chain: scancel ${JOB_IDS_ONLY[*]}"
echo "############################################################"
