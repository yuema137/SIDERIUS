#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain Orchestrator — SDSC (Slurm)
# ---------------------------------------------------------------------------
# Full runbook (lilab + SDSC): docs/running_chain_test.md
# Shared logic: sdsc_submission_scripts/_chain_common.sh
# ---------------------------------------------------------------------------
# SDSC equivalent of run_iteration_chain_lilab.sh. Submits N iteration
# jobs in sequence using --dependency=afterany for automatic chaining.
# Each job's source paths = original seeds + all previous iterations'
# manifests (resolved at job execution time via the @manifest: prefix).
#
# Iterations chain through manifest.json files exactly the same way as
# on lilab — only the execution mechanism differs (sbatch with
# --dependency=afterany here, foreground subprocess on lilab).
#
# Usage:
#   bash sdsc_submission_scripts/run_iteration_chain.sh \
#       --workspace /expanse/lustre/projects/ddp433/ym137/exploration_v1 \
#       --num_iterations 10 \
#       --seed_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \
#       --max_rounds 5 \
#       --max_epochs 5 \
#       --human_advice_file sdsc_submission_scripts/human_advice_chain_test.json \
#       --reflect_model_id gemini-2-flash  \  # optional: route the tuner's
#                                              # reflector sub-call to a cheaper
#                                              # model than the planner
#       --partition gpu-shared \
#       --time 06:00:00
#
# --mem defaults to 48G (host RAM cap). Do not set lower without
# understanding the OOM risk in the formal-round parallel scoring step.
#
# If iteration N fails *at the python level* (no manifest written, or
# manifest with status=failed), iteration N+1 will start anyway thanks to
# afterany — and will then error cleanly when run_one_iteration.py tries
# to resolve the @manifest: source path. The downstream iterations are
# NOT auto-cancelled; you have to scancel them manually if you want to
# stop the chain after a python-level failure. This is intentional: it
# lets the chain survive transient OOM events that the OOM-tolerant tuner
# can recover from on its own.

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
        # afterany: run iteration N+1 regardless of iteration N's slurm-level
        # exit state. The actual correctness check ('did iteration N produce
        # a valid manifest?') is done by run_one_iteration.py at job start
        # via the @manifest: indirection — if iteration N's manifest exists
        # with status=completed, source-path resolution succeeds and the run
        # proceeds; if it doesn't, the runner errors cleanly.
        #
        # Why not afterok: the SIDERIUS tuner is OOM-tolerant (catches OOM
        # in any single training round, records error_training_oom, and
        # continues with the next round). When this happens, the python
        # workflow finishes cleanly and writes a valid manifest, but slurm
        # permanently records OUT_OF_MEMORY in the job's accounting state.
        # afterok would then incorrectly cancel the next iteration even
        # though the python-level work succeeded. afterany sidesteps this
        # by deferring the success check to the python layer where it
        # belongs.
        SBATCH_ARGS+=(--dependency="afterany:${PREV_JOB_ID}")
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
