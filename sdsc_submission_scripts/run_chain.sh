#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Iteration Chain — ENTRY POINT (exec, do not source)
# ---------------------------------------------------------------------------
# Role   : single user-facing entry script for chain runs. Owns the
#          mode-aware pieces (python resolution, auto-resume, slurm vs
#          subprocess submission) and delegates the loop body to the
#          shared library.
# Library: sources sdsc_submission_scripts/_chain_common.sh, which owns
#          the mode-agnostic defaults / arg parser / iter loop body.
# Folder : see sdsc_submission_scripts/README.md for the full file map.
# Doc    : docs/running_chain_test.md is the operator runbook.
# ---------------------------------------------------------------------------
# What lives here (and not in _chain_common.sh):
#   * Python interpreter resolution (.venv > uv run > system python3) +
#     version guard (>= 3.10) + env passthrough for child processes
#   * --auto_resume — query scripts/inspect_run_state.py for --next-iter
#   * --force_fresh / stale-fresh safety guard
#   * --start_iter manual pin + idempotency check
#   * Mode-specific submit_iteration implementations:
#       submit_iteration_lilab : foreground subprocess (dev / dev-GPU)
#       submit_iteration_sdsc  : sbatch + afterany dependency chain (HPC)
#   * Final summary print (per-iter manifest / per-iter job ID)
#
# What does NOT live here (lives in _chain_common.sh instead):
#   * Default values, CLI parser, advice-file loader
#   * Per-iter app-arg construction (build_app_args)
#   * The iteration loop body (run_chain)
#
# Mode selection (required):
#   --mode lilab   foreground subprocess; suitable for dev / dev-GPU
#   --mode sdsc    sbatch + afterany dependency chain (Slurm HPC)
#
# Required flags:
#   --workspace DIR      chain workspace root
#   --seed_paths P [P…]  one or more seed run_output JSONs
#   --run_name NAME      chain-level run name (pins immutable run_id)
#
# Frequently-used flags:
#   --num_iterations N   number of iterations (default 2)
#   --dry-run            walk the chain, print exact commands, no side effects
#   --auto_resume        pick up where a partial chain left off (default ON)
#   --no_auto_resume     force fresh start regardless of workspace state
#   --start_iter N       manual pin (overrides auto-resume)
#   --task_composition F  YAML task-composition manifest. Omitted = the legacy
#                        un-composed run (byte-identical child argv). Supplying
#                        it binds the task's data path, dataset profile, metric,
#                        declared secondaries, Health family and task config for
#                        the whole run. Shipped: configs/task_composition/tidmad.yaml
#
# Usage examples:
#
#   bash sdsc_submission_scripts/run_chain.sh --mode lilab \
#       --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
#       --run_name lilab_v1 \
#       --num_iterations 3 \
#       --seed_paths /path/to/seed.json
#
#   bash sdsc_submission_scripts/run_chain.sh --mode sdsc --dry-run \
#       --workspace /expanse/.../exploration_v1 \
#       --run_name expanse_v1 \
#       --num_iterations 5 \
#       --seed_paths /scratch/.../seed.json \
#       --partition gpu-shared --time 06:00:00
#
#   # A COMPOSED run — the task is bound once, at the launcher edge:
#   bash sdsc_submission_scripts/run_chain.sh --mode lilab \
#       --workspace /home/klz/Data/SIDEREIS_DATA/composed_tidmad_v1 \
#       --run_name composed_tidmad_v1 \
#       --num_iterations 2 \
#       --task_composition configs/task_composition/tidmad.yaml
#
# History: introduced in Phase 6.8 Commit 13 to consolidate the legacy
# run_iteration_chain.sh (SDSC) and run_iteration_chain_lilab.sh (lilab)
# entries. Those stubs were removed once operators had migrated.

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNNER="${SCRIPT_DIR}/run_one_iteration.py"
SLURM_SCRIPT="${SCRIPT_DIR}/submit_one_iteration.slurm"

source "${SCRIPT_DIR}/_chain_common.sh"

# Resolve the Python interpreter. Priority (canonical SIDERIUS dev setup
# hardened in 13.D):
#   1. activated venv ($VIRTUAL_ENV)         — operator-asserted env
#   2. project-local ${PROJECT_DIR}/.venv    — the standard repo layout
#   3. uv run python                          — lilab fallback when no .venv
#   4. system python3                         — last resort, prominent warn
# After resolution, two guards run unconditionally:
#   - enforce_py_version_guard: SIDERIUS requires Python 3.10+
#   - setup_py_env_passthrough: ensure subprocesses inherit the same venv
# Sets PY_CMD (array) + PY_SOURCE (label) + PY_VENV_ROOT (path or empty).
# PY_VENV_ROOT empty means "no venv to passthrough" (uv or system python3).
resolve_py_cmd() {
    PY_VENV_ROOT=""
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        PY_CMD=("$VIRTUAL_ENV/bin/python")
        PY_SOURCE="\$VIRTUAL_ENV ($VIRTUAL_ENV)"
        PY_VENV_ROOT="$VIRTUAL_ENV"
    elif [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
        PY_CMD=("${PROJECT_DIR}/.venv/bin/python")
        PY_SOURCE="${PROJECT_DIR}/.venv"
        PY_VENV_ROOT="${PROJECT_DIR}/.venv"
    elif command -v uv >/dev/null 2>&1; then
        PY_CMD=(uv run --project "$PROJECT_DIR" python)
        PY_SOURCE="uv run"
        # uv injects its own env per invocation; we leave PY_VENV_ROOT empty.
    elif command -v python3 >/dev/null 2>&1; then
        PY_CMD=(python3)
        PY_SOURCE="system python3 (NO venv detected — reproducibility risk)"
        echo "############################################################" >&2
        echo "WARNING: falling back to SYSTEM python3" >&2
        echo "  No \$VIRTUAL_ENV, no ${PROJECT_DIR}/.venv, no 'uv' available." >&2
        echo "  System python may be stale or missing required packages." >&2
        echo "  This path is reproducibility-hostile — fix by:" >&2
        echo "    cd ${PROJECT_DIR} && python3.10 -m venv .venv" >&2
        echo "    .venv/bin/pip install -e ." >&2
        echo "############################################################" >&2
    else
        echo "ERROR: no python interpreter found (no \$VIRTUAL_ENV, no .venv, no uv, no python3)" >&2
        exit 1
    fi
}

# Enforce SIDERIUS's Python ≥ 3.10 floor. Runs the resolved interpreter
# itself (not the parent shell's python) so this catches all four
# resolution paths, including uv-managed interpreters.
enforce_py_version_guard() {
    if "${PY_CMD[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        return 0
    fi
    local version
    version=$("${PY_CMD[@]}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null) \
        || version="unknown"
    echo "ERROR: SIDERIUS requires Python 3.10+. Current: $version" >&2
    echo "  Resolved interpreter: ${PY_CMD[*]}  (source: $PY_SOURCE)" >&2
    exit 1
}

# Make sure subprocesses spawned by run_one_iteration.py (training workers,
# torch DataLoader workers, plugin imports) inherit the same Python
# environment as the orchestrator. When we resolved to a venv but the
# parent shell never activated it, VIRTUAL_ENV is unset and PATH won't
# have .venv/bin first — fix that here.
setup_py_env_passthrough() {
    if [ -z "$PY_VENV_ROOT" ]; then
        # uv-run or system python3 paths — nothing to passthrough.
        return 0
    fi
    export VIRTUAL_ENV="$PY_VENV_ROOT"
    case ":$PATH:" in
        *":$PY_VENV_ROOT/bin:"*) ;;  # already first or present; idempotent
        *) export PATH="$PY_VENV_ROOT/bin:$PATH" ;;
    esac
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
        # afterany (not afterok): the OOM-tolerant tuner can finish a
        # python-clean run while Slurm still records OUT_OF_MEMORY in
        # accounting state, which would falsely cancel the next iter
        # under afterok.
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

# Resolve the Python interpreter for both modes. Lilab uses it to run
# run_one_iteration.py directly; SDSC only uses it on the submission node
# to run scripts/inspect_run_state.py for auto-resume. The SDSC iteration
# jobs themselves use whatever python is configured inside submit_one_iteration.slurm.
resolve_py_cmd
# 13.D — version + env-passthrough guards. Both run unconditionally so
# the SDSC submission node and lilab orchestrator agree on the contract.
enforce_py_version_guard
setup_py_env_passthrough

# --- 13.B: Auto-resume + safety guard + idempotency ---

resolve_start_iter() {
    if [ -n "$START_ITER" ]; then
        echo "Start: --start_iter manually pinned to $START_ITER"
        return 0
    fi
    if [ "$AUTO_RESUME" -ne 1 ]; then
        START_ITER=1
        echo "Start: auto-resume disabled — defaulting to 1"
        return 0
    fi
    if [ ! -d "$WORKSPACE" ]; then
        START_ITER=1
        echo "Start: workspace does not exist yet — fresh chain at 1"
        return 0
    fi
    # Inspector emits a single integer on stdout when successful, or a
    # human-readable error on stderr with non-zero exit (legacy layout,
    # non-contiguous gap, ...). We let stderr flow through naturally and
    # halt with a wrapper-level message so operators see both signals.
    if ! START_ITER=$("${PY_CMD[@]}" "${PROJECT_DIR}/scripts/inspect_run_state.py" \
            --layout chain --workspace "$WORKSPACE" --next-iter); then
        echo "ERROR: inspector refused to compute --next-iter for workspace $WORKSPACE (see error above)" >&2
        exit 1
    fi
    echo "Start: auto-resume — inspector computed START_ITER=$START_ITER"
}

check_idempotency() {
    if [ "$START_ITER" -gt "$NUM_ITERATIONS" ]; then
        echo "All ${NUM_ITERATIONS} iterations are already complete. Nothing to do."
        exit 0
    fi
}

# Refuses to start a fresh chain (START_ITER==1) on a non-empty workspace
# unless --force_fresh is set. This is the stale-fresh safety guard: it
# catches the common accident of pointing the chain at the wrong workspace
# and silently overwriting unrelated work.
check_stale_fresh_guard() {
    if [ "$START_ITER" -ne 1 ]; then
        return 0
    fi
    if [ ! -d "$WORKSPACE" ]; then
        return 0
    fi
    if [ -z "$(ls -A "$WORKSPACE" 2>/dev/null)" ]; then
        return 0
    fi
    if [ "$FORCE_FRESH" -eq 1 ]; then
        echo "WARNING: --force_fresh set — proceeding from iter 1 in non-empty workspace $WORKSPACE"
        return 0
    fi
    echo "ERROR: Workspace at $WORKSPACE is not empty. Use --force_fresh to clobber existing data, or specify --start_iter N to resume from a specific point." >&2
    exit 1
}

resolve_start_iter
check_idempotency
check_stale_fresh_guard

case "$MODE" in
    lilab) HEADER_LABEL="LILAB (foreground)" ;;
    sdsc)  HEADER_LABEL="SDSC (Slurm afterany)" ;;
esac
print_chain_header "$HEADER_LABEL"
CHAIN_STATUS=0
run_chain || CHAIN_STATUS=$?

# An operator-stopped chain reports the stop as its own outcome: it did
# NOT complete, and printing a completion banner would misreport it.
# run_chain has already written the stopped-chain state record.
if [ "$CHAIN_STATUS" -ne 0 ]; then
    exit "$CHAIN_STATUS"
fi

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
