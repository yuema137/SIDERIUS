#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS prior-art baseline experiment (arXiv X9) — ONE entrypoint, TWO arms
# ---------------------------------------------------------------------------
# Role   : express both arms of the "with vs without prior art" experiment
#          from one launcher with ONE argument changed (--arm). Everything
#          the arm decides is stated EXPLICITLY on the chain's argv and is
#          pinned into the workspace's run_invariants_lock.json:
#
#            --arm with-prior-art
#                --ml_lit_review_enabled --experiment_arm with-prior-art
#            --arm without-prior-art
#                --no-ml_lit_review_enabled --experiment_arm without-prior-art
#                --baseline_isolation
#
#          The label (--experiment_arm) is OPAQUE provenance (ruling R2): it
#          drives nothing. The WITHOUT arm's behaviour is driven by its own
#          recorded flag, --baseline_isolation (ruling R6): no bundled
#          baseline description, no baseline-naming prompt literal, no
#          built-in candidate. The OFF arm is recorded POSITIVELY — the
#          negative lit-review flag is forwarded to the child argv rather
#          than inherited from the YAML's default.
#
# Wraps   : sdsc_submission_scripts/run_chain.sh — NEVER the tuner node CLI
#          (on the node CLI, omitting --is_trial silently falls into legacy
#          single-file mode; the chain path defaults --is_trial correctly).
#
# Advice  : NEITHER arm receives an advice file. The experiment's only
#          variable is the literature-review topology; a V20 explorer file
#          (advice/workflow/v20_*_explorer.json) names FCNet's 323 M scale
#          and would be a second variable in the WITH arm and a baseline
#          literal in the WITHOUT arm. --advice / --human_advice_file are
#          therefore REFUSED as passthrough in both arms.
#
# Usage:
#   bash sdsc_submission_scripts/launch_prior_baseline_experiment.sh \
#       --arm with-prior-art|without-prior-art \
#       --workspace DIR [--run_name NAME] [--mode lilab|sdsc] \
#       [--dry-run] [--h100] [passthrough run_chain.sh flags...]
#
#   --run_name defaults to the workspace basename. --dry-run runs
#   run_chain.sh --dry-run (exact child argv, no side effects) AND prints the
#   resolved launch configuration as one JSON object
#   (run_one_iteration.py --print_resolved_launch_config). --h100 sources
#   sdsc_submission_scripts/h100_posture.env (owned by the H100 posture
#   stream), which exports production env vars and defines the bash array
#   H100_CHAIN_ARGS that this launcher splats AFTER its own arguments; a
#   missing file is refused by name.
#
# Cold start: never pass --seed_paths. The cold-start checklist lives in
# docs/gates/gate_testing_standard.md ("Cold-start checklist").
# ---------------------------------------------------------------------------

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_CHAIN="${SCRIPT_DIR}/run_chain.sh"
RUNNER="${SCRIPT_DIR}/run_one_iteration.py"
H100_POSTURE_ENV="${SCRIPT_DIR}/h100_posture.env"

ARM=""
WORKSPACE=""
RUN_NAME=""
MODE="lilab"
DRY_RUN=0
H100=0
PASSTHROUGH=()

usage() {
    sed -n '2,52p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --arm)                 ARM="$2"; shift 2 ;;
        --workspace)           WORKSPACE="$2"; shift 2 ;;
        --run_name)            RUN_NAME="$2"; shift 2 ;;
        --mode)                MODE="$2"; shift 2 ;;
        --dry-run|--dry_run)   DRY_RUN=1; shift ;;
        --h100)                H100=1; shift ;;
        -h|--help)             usage; exit 0 ;;
        --advice|--human_advice_file)
            echo "ERROR: $1 is refused: neither arm receives an advice file" >&2
            echo "  (the experiment's only variable is the literature-review topology;" >&2
            echo "   a V20 explorer file names FCNet's 323 M scale)." >&2
            exit 1 ;;
        --ml_lit_review_enabled|--no-ml_lit_review_enabled|--experiment_arm|--baseline_isolation)
            echo "ERROR: $1 is decided by --arm and cannot be passed through" >&2
            exit 1 ;;
        --seed_paths)
            echo "ERROR: --seed_paths is refused: the experiment is cold-start (CLAUDE.md rule)" >&2
            exit 1 ;;
        *)                     PASSTHROUGH+=("$1"); shift ;;
    esac
done

if [ -z "$WORKSPACE" ]; then
    echo "Required: --workspace DIR" >&2
    exit 1
fi
[ -z "$RUN_NAME" ] && RUN_NAME="$(basename "$WORKSPACE")"

case "$ARM" in
    with-prior-art)
        ARM_ARGS=(--ml_lit_review_enabled --experiment_arm with-prior-art)
        ;;
    without-prior-art)
        ARM_ARGS=(--no-ml_lit_review_enabled --experiment_arm without-prior-art --baseline_isolation)
        ;;
    "")
        echo "Required: --arm with-prior-art|without-prior-art" >&2
        exit 1 ;;
    *)
        echo "ERROR: unknown --arm '$ARM' (expected with-prior-art or without-prior-art)" >&2
        exit 1 ;;
esac

# --- H100 posture (owned by the H100 posture stream; sourced, never defined) --
H100_CHAIN_ARGS=()
if [ "$H100" -eq 1 ]; then
    if [ ! -f "$H100_POSTURE_ENV" ]; then
        echo "ERROR: --h100 requested but the posture file is missing: $H100_POSTURE_ENV" >&2
        echo "  It must export the production env vars and define the bash array" >&2
        echo "  H100_CHAIN_ARGS (chain flags splatted after this launcher's own)." >&2
        exit 1
    fi
    # Unset first so `declare -p` below tests what the POSTURE FILE defined,
    # not this launcher's own initialisation (a vacuous check otherwise).
    unset H100_CHAIN_ARGS
    # shellcheck disable=SC1090
    source "$H100_POSTURE_ENV"
    if ! declare -p H100_CHAIN_ARGS >/dev/null 2>&1; then
        echo "ERROR: $H100_POSTURE_ENV did not define the H100_CHAIN_ARGS array" >&2
        exit 1
    fi
fi

CHAIN_ARGS=(
    --mode "$MODE"
    --workspace "$WORKSPACE"
    --run_name "$RUN_NAME"
    "${ARM_ARGS[@]}"
)
CHAIN_ARGS+=("${PASSTHROUGH[@]}")
if [ "${#H100_CHAIN_ARGS[@]}" -gt 0 ]; then
    CHAIN_ARGS+=("${H100_CHAIN_ARGS[@]}")
fi

# --- Python for the resolved-config print (dry-run only) --------------------
resolve_python() {
    if [ -n "${SIDERIUS_PYTHON:-}" ]; then
        PY="$SIDERIUS_PYTHON"
    elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        PY="$VIRTUAL_ENV/bin/python"
    elif [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
        PY="${PROJECT_DIR}/.venv/bin/python"
    else
        PY="python3"
    fi
}

# The identity-relevant subset of the chain flags, forwarded to the print so
# it resolves exactly what the iteration will resolve. Chain-level flags the
# runner does not accept (--num_iterations, --partition, ...) are skipped.
identity_flags() {
    local args=("$@")
    local i=0
    IDENTITY_FLAGS=()
    while [ $i -lt ${#args[@]} ]; do
        case "${args[$i]}" in
            --task_composition|--ml_lit_review_config|--healthgate_mode|--result_authority|\
            --health_checks_config|--skip_formal_min_delta|--bypass_formal_time_budget_min_delta|\
            --data_dir|--llm_config)
                IDENTITY_FLAGS+=("${args[$i]}" "${args[$((i+1))]}"); i=$((i+2)) ;;
            --enable_chain_incumbent_formal_gates)
                IDENTITY_FLAGS+=("${args[$i]}"); i=$((i+1)) ;;
            *) i=$((i+1)) ;;
        esac
    done
}

echo "[prior-baseline] arm=$ARM workspace=$WORKSPACE run_name=$RUN_NAME mode=$MODE h100=$H100 dry_run=$DRY_RUN"

if [ "$DRY_RUN" -eq 1 ]; then
    resolve_python
    identity_flags "${PASSTHROUGH[@]}" "${H100_CHAIN_ARGS[@]}"
    echo "[prior-baseline] resolved launch configuration:"
    # PYTHONPATH pins THIS checkout: with a shared venv whose editable
    # install points at another clone, a bare script invocation would
    # import that clone's modules — the CLAUDE.md portability failure —
    # and the printed configuration would describe code this launcher is
    # not launching.
    (cd "$PROJECT_DIR" && \
        PYTHONPATH="${PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
        "$PY" "$RUNNER" --print_resolved_launch_config \
        --workspace "$WORKSPACE" --run_name "$RUN_NAME" --start_iteration 1 \
        "${ARM_ARGS[@]}" "${IDENTITY_FLAGS[@]}")
    exec bash "$RUN_CHAIN" "${CHAIN_ARGS[@]}" --dry-run
fi

exec bash "$RUN_CHAIN" "${CHAIN_ARGS[@]}"
