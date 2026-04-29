#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain — unified orchestrator (Phase 6.8 Commit 13)
# ---------------------------------------------------------------------------
# Full runbook: docs/running_chain_test.md
# Shared logic: sdsc_submission_scripts/_chain_common.sh
# ---------------------------------------------------------------------------
# This is the single user-facing entry point for chain runs. Backend is
# selected by --mode:
#
#   --mode lilab   foreground subprocess; suitable for dev / dev-GPU
#   --mode sdsc    sbatch + afterany dependency chain (Slurm HPC)
#
# Other behaviour is identical across modes: same flags, same defaults,
# same per-iter app-arg construction (all in _chain_common.sh).
#
# Useful flags:
#   --dry-run            walk the chain and print the exact commands
#                        without touching the workspace or submitting jobs
#   --workspace DIR      chain workspace root (required)
#   --num_iterations N   number of iterations to run (default 2)
#   --seed_paths P [P…]  one or more seed run_output JSONs (required)
#
# Usage examples:
#
#   bash sdsc_submission_scripts/run_chain.sh --mode lilab \
#       --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
#       --num_iterations 3 \
#       --seed_paths /path/to/seed.json
#
#   bash sdsc_submission_scripts/run_chain.sh --mode sdsc --dry-run \
#       --workspace /expanse/.../exploration_v1 \
#       --num_iterations 5 \
#       --seed_paths /scratch/.../seed.json \
#       --partition gpu-shared --time 06:00:00
#
# Auto-resume wiring (--auto_resume) lands in Commit 13.B. This file
# currently implements Tasks 1, 2, 5, and a basic slice of Task 6.

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNNER="${SCRIPT_DIR}/run_one_iteration.py"
SLURM_SCRIPT="${SCRIPT_DIR}/submit_one_iteration.slurm"

source "${SCRIPT_DIR}/_chain_common.sh"

# Resolve the lilab Python interpreter. Priority:
#   1. activated venv ($VIRTUAL_ENV)
#   2. project-local .venv (the canonical SIDERIUS dev setup)
#   3. uv run python (lilab fallback when no .venv exists)
#   4. system python3 (warns; reproducibility-hostile)
# Full version-guard hardening lives in 13.D; this slice is what the
# dry-run header needs to print a sensible "Python:" line.
resolve_py_cmd() {
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        PY_CMD=("$VIRTUAL_ENV/bin/python")
        PY_SOURCE="\$VIRTUAL_ENV ($VIRTUAL_ENV)"
    elif [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
        PY_CMD=("${PROJECT_DIR}/.venv/bin/python")
        PY_SOURCE="${PROJECT_DIR}/.venv"
    elif command -v uv >/dev/null 2>&1; then
        PY_CMD=(uv run --project "$PROJECT_DIR" python)
        PY_SOURCE="uv run"
    elif command -v python3 >/dev/null 2>&1; then
        PY_CMD=(python3)
        PY_SOURCE="system python3 (NO venv detected — reproducibility risk)"
        echo "WARNING: no .venv and no uv detected; falling back to system python3" >&2
    else
        echo "ERROR: no python interpreter found (no \$VIRTUAL_ENV, no .venv, no uv, no python3)" >&2
        exit 1
    fi
}

submit_iteration_lilab() {
    local iter=$1
    local cmd=( "${PY_CMD[@]}" "$RUNNER" "${APP_ARGS[@]}" )
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "  [DRY-RUN] would exec from $PROJECT_DIR:"
        printf '    '
        printf '%q ' "${cmd[@]}"
        echo
        return 0
    fi
    (cd "$PROJECT_DIR" && "${cmd[@]}")
}

submit_iteration_sdsc() {
    local iter=$1
    local sbatch_args=(
        --partition="$PARTITION"
        --nodes=1
        --ntasks=1
        --gpus="$GPUS"
        --mem="$MEM"
        --time="$TIME"
        --cpus-per-task="$CPUS"
    )
    if [ -n "$PREV_JOB_ID" ]; then
        # afterany — see run_iteration_chain.sh's commentary for why this is
        # not afterok. The OOM-tolerant tuner can finish a python-clean run
        # while Slurm still records OUT_OF_MEMORY in accounting state, which
        # would falsely cancel the next iter under afterok.
        sbatch_args+=( --dependency="afterany:${PREV_JOB_ID}" )
    fi
    local cmd=( sbatch "${sbatch_args[@]}" "$SLURM_SCRIPT" "${APP_ARGS[@]}" )
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "  [DRY-RUN] would submit:"
        printf '    '
        printf '%q ' "${cmd[@]}"
        echo
        if [ -n "$PREV_JOB_ID" ]; then
            echo "    (depends on previous job: $PREV_JOB_ID)"
        fi
        # Synthetic placeholder so the chain-link --dependency is visible
        # for iters >= 2 in dry-run output. Format mirrors what we would
        # parse from a real sbatch reply (digits-only would be misleading).
        PREV_JOB_ID="DRYRUN_$(printf 'iter_%03d' "$iter")"
        return 0
    fi
    local OUTPUT JOB_ID
    OUTPUT=$(sbatch "${sbatch_args[@]}" "$SLURM_SCRIPT" "${APP_ARGS[@]}")
    JOB_ID=$(echo "$OUTPUT" | grep -oP '\d+$')
    if [ -z "$JOB_ID" ]; then
        echo "[FAIL] could not parse job ID from sbatch output:" >&2
        echo "$OUTPUT" >&2
        exit 1
    fi
    echo "  Job ID: $JOB_ID"
    SUBMITTED_JOBS+=("$iter:$JOB_ID")
    PREV_JOB_ID="$JOB_ID"
}

# Required by run_chain (defined in _chain_common.sh): dispatch on $MODE.
submit_iteration() {
    case "$MODE" in
        lilab) submit_iteration_lilab "$1" ;;
        sdsc)  submit_iteration_sdsc  "$1" ;;
        *)     echo "ERROR: unknown --mode '$MODE'" >&2; exit 1 ;;
    esac
}

# --- Main ---

PREV_JOB_ID=""
SUBMITTED_JOBS=()

parse_chain_args "$@"
load_advice_file

if [ -z "$MODE" ]; then
    echo "Required: --mode {lilab,sdsc}" >&2
    exit 1
fi
case "$MODE" in
    lilab|sdsc) ;;
    *) echo "Invalid --mode '$MODE' (must be 'lilab' or 'sdsc')" >&2; exit 1 ;;
esac

if [ "$MODE" = "lilab" ]; then
    resolve_py_cmd
fi

case "$MODE" in
    lilab) HEADER_LABEL="LILAB (foreground)" ;;
    sdsc)  HEADER_LABEL="SDSC (Slurm afterany)" ;;
esac
print_chain_header "$HEADER_LABEL"
run_chain

echo ""
echo "############################################################"
if [ "$DRY_RUN" -eq 1 ]; then
    echo "  DRY-RUN COMPLETE — ${NUM_ITERATIONS} iterations walked, no side effects"
elif [ "$MODE" = "lilab" ]; then
    echo "  CHAIN COMPLETE — ${NUM_ITERATIONS} iterations"
    for ITER in $(seq 1 "$NUM_ITERATIONS"); do
        MANIFEST=$(printf "${WORKSPACE}/iter_%03d/manifest.json" "$ITER")
        if [ -f "$MANIFEST" ]; then
            echo "  iter $ITER → $MANIFEST"
        else
            echo "  iter $ITER → MISSING (this should not happen on a clean run)"
        fi
    done
else
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
fi
echo "############################################################"
