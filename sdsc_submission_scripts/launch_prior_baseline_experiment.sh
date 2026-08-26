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
# Campaign band mode (arXiv launch topology, author ruling 2026-08-25):
#          the H100 campaign runs FOUR co-resident band chains per card
#          (GPU A = WITH arm, GPU B = WITHOUT arm, GPU C = calibration).
#          The old one-chain-per-card posture is SUPERSEDED.
#
#            --band 0-3|4-9|10-14|15-19
#                maps to the DS8-mandatory pair (gate_testing_standard.md
#                "Partial-scope rules"):
#                  --data_scope <band>  +  --health_gate_files <band files>
#                and enters the run identity: the derived run_name and the
#                per-chain workspace are "${ARM}_band${BAND}", so four
#                chains can never share a workspace.
#            --workspace-root DIR   (required with --band)
#                the PERSISTENT-VOLUME campaign root. Per-chain workspaces
#                are derived under it. Refused loudly if the directory does
#                not exist or is not writable — pod loss must not destroy
#                records/checkpoints/manifests/provenance, so the root must
#                be mounted storage, never pod-local scratch
#                (campaign_preflight.sh verifies the mount).
#            --data_scope / --health_gate_files are REFUSED as passthrough
#                in band mode: the band decides them (same rule as the
#                arm-decided flags).
#            With --h100, a banded launch additionally requires the posture
#                to carry a probe-measured H100_CORESIDENCY_FACTOR
#                (gpu_c_coresidency_probe.sh); an empty factor refuses the
#                launch by name.
#
# Fixed-candidate mode (post-freeze finalization retrains):
#            --fixed-candidate PLAN.json
#                forwards the chain's EXISTING single-candidate seam
#                (--validation_fixed_candidate_plan, V20 FU-D-11): the
#                proposer is bypassed and every downstream stage runs for
#                real on the operator-supplied ProposalOutput plan (the
#                frozen champion). The plan file must exist; provenance
#                (path + sha256 + resolved model) is recorded by
#                run_one_iteration.py in the iteration manifest. Unless the
#                caller passes --num_iterations explicitly, this mode pins
#                --num_iterations 1 (a retrain is one iteration; the
#                chain default of 2 would silently retrain twice).
#                Passing --validation_fixed_candidate_plan directly is
#                refused: on this launcher the mode has ONE spelling.
#
# Usage:
#   bash sdsc_submission_scripts/launch_prior_baseline_experiment.sh \
#       --arm with-prior-art|without-prior-art \
#       (--workspace DIR | --band B --workspace-root DIR) \
#       [--run_name NAME] [--mode lilab|sdsc] [--fixed-candidate PLAN.json] \
#       [--dry-run] [--h100] [passthrough run_chain.sh flags...]
#
#   --run_name defaults to the workspace basename (band mode: to
#   "${ARM}_band${BAND}"). --dry-run runs run_chain.sh --dry-run (exact
#   child argv, no side effects) AND prints the resolved launch
#   configuration as one JSON object
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
# P0 launch blocker (supervisor 2026-08-25, E1 trap): the venv's editable
# install maps packages to the MAIN checkout; a child whose cwd leaves this
# tree silently imports THAT tree's code. Pin resolution to THIS tree for
# every process this launcher spawns. Identical for both arms by
# construction (derived from the script's own location) — preflight R2b
# proves it live, R7 sees it symmetric.
export PYTHONPATH="${PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
RUN_CHAIN="${SCRIPT_DIR}/run_chain.sh"
RUNNER="${SCRIPT_DIR}/run_one_iteration.py"
H100_POSTURE_ENV="${SCRIPT_DIR}/h100_posture.env"
CORESIDENCY_PROBE="${SCRIPT_DIR}/gpu_c_coresidency_probe.sh"

ARM=""
WORKSPACE=""
WORKSPACE_ROOT=""
BAND=""
RUN_NAME=""
MODE="lilab"
DRY_RUN=0
H100=0
FIXED_CANDIDATE=""
PASSTHROUGH=()

usage() {
    sed -n '2,96p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --arm)                 ARM="$2"; shift 2 ;;
        --workspace)           WORKSPACE="$2"; shift 2 ;;
        --workspace-root|--workspace_root) WORKSPACE_ROOT="$2"; shift 2 ;;
        --band)                BAND="$2"; shift 2 ;;
        --run_name)            RUN_NAME="$2"; shift 2 ;;
        --mode)                MODE="$2"; shift 2 ;;
        --fixed-candidate|--fixed_candidate) FIXED_CANDIDATE="$2"; shift 2 ;;
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
        --validation_fixed_candidate_plan)
            echo "ERROR: $1 is decided by --fixed-candidate and cannot be passed through" >&2
            echo "  (one spelling per mode on this launcher: --fixed-candidate PLAN.json" >&2
            echo "   validates the file, records provenance and pins --num_iterations 1)." >&2
            exit 1 ;;
        --seed_paths)
            echo "ERROR: --seed_paths is refused: the experiment is cold-start (CLAUDE.md rule)" >&2
            exit 1 ;;
        *)                     PASSTHROUGH+=("$1"); shift ;;
    esac
done

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

# --- Campaign band mode (author ruling 2026-08-25) --------------------------
# The band decides the DS8-mandatory --data_scope + --health_gate_files pair
# and enters the run identity (run_name + per-chain workspace). The mapping
# below is the ONE authority for the four campaign bands; the fleet script
# iterates these same four literals and an unknown band refuses here.
BAND_ARGS=()
if [ -n "$BAND" ]; then
    case "$BAND" in
        0-3)   BAND_HEALTH_FILES="0,1,2,3" ;;
        4-9)   BAND_HEALTH_FILES="4,5,6,7,8,9" ;;
        10-14) BAND_HEALTH_FILES="10,11,12,13,14" ;;
        15-19) BAND_HEALTH_FILES="15,16,17,18,19" ;;
        *)
            echo "ERROR: unknown --band '$BAND' (expected 0-3, 4-9, 10-14 or 15-19)" >&2
            exit 1 ;;
    esac
    for _tok in ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}; do
        case "$_tok" in
            --data_scope|--health_gate_files)
                echo "ERROR: $_tok is decided by --band and cannot be passed through" >&2
                echo "  (DS8 pairing: --band $BAND maps to --data_scope $BAND" >&2
                echo "   --health_gate_files $BAND_HEALTH_FILES)" >&2
                exit 1 ;;
        esac
    done
    if [ -n "$WORKSPACE" ]; then
        echo "ERROR: --workspace and --band are mutually exclusive: band mode derives the" >&2
        echo "  per-chain workspace under --workspace-root so four chains never share one." >&2
        exit 1
    fi
    if [ -z "$WORKSPACE_ROOT" ]; then
        echo "ERROR: --band requires --workspace-root DIR (the persistent-volume campaign root)" >&2
        exit 1
    fi
    if [ ! -d "$WORKSPACE_ROOT" ]; then
        echo "ERROR: --workspace-root does not exist: $WORKSPACE_ROOT" >&2
        echo "  The campaign root must be an EXISTING persistent-volume mount: pod loss" >&2
        echo "  must not destroy records/checkpoints/manifests/provenance. Create/mount" >&2
        echo "  it first (and see campaign_preflight.sh for the mount check)." >&2
        exit 1
    fi
    if [ ! -w "$WORKSPACE_ROOT" ]; then
        echo "ERROR: --workspace-root is not writable: $WORKSPACE_ROOT" >&2
        exit 1
    fi
    WORKSPACE="${WORKSPACE_ROOT%/}/${ARM}_band${BAND}"
    [ -z "$RUN_NAME" ] && RUN_NAME="${ARM}_band${BAND}"
    # Fleet ruling 2026-08-25 (#259 comment): the X9 campaign's regression
    # contract. Pinned IDENTICALLY in both arms (the #255 symmetry condition);
    # the knob now exists (--allowed_output_types, arXiv #259) and the
    # proposer's schema gate enforces it deterministically.
    BAND_ARGS=(--data_scope "$BAND" --health_gate_files "$BAND_HEALTH_FILES"
               --allowed_output_types regressor)
elif [ -n "$WORKSPACE_ROOT" ]; then
    echo "ERROR: --workspace-root is campaign-band mode only; without --band pass --workspace DIR" >&2
    exit 1
fi

if [ -z "$WORKSPACE" ]; then
    echo "Required: --workspace DIR (or campaign band mode: --band B --workspace-root DIR)" >&2
    exit 1
fi
[ -z "$RUN_NAME" ] && RUN_NAME="$(basename "$WORKSPACE")"

# --- Fixed-candidate mode (post-freeze finalization retrains) ---------------
FIXED_ARGS=()
if [ -n "$FIXED_CANDIDATE" ]; then
    if [ ! -f "$FIXED_CANDIDATE" ]; then
        echo "ERROR: --fixed-candidate plan file not found: $FIXED_CANDIDATE" >&2
        exit 1
    fi
    FIXED_CANDIDATE_ABS="$(cd "$(dirname "$FIXED_CANDIDATE")" && pwd)/$(basename "$FIXED_CANDIDATE")"
    FIXED_ARGS=(--validation_fixed_candidate_plan "$FIXED_CANDIDATE_ABS")
    # A finalization retrain is ONE iteration; run_chain.sh defaults to 2.
    # An explicit passthrough --num_iterations wins (stated later on argv).
    _HAS_NUM_ITERATIONS=0
    for _tok in ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}; do
        [ "$_tok" = "--num_iterations" ] && _HAS_NUM_ITERATIONS=1
    done
    if [ "$_HAS_NUM_ITERATIONS" -eq 0 ]; then
        FIXED_ARGS+=(--num_iterations 1)
    fi
fi

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
    # H100_CORESIDENCY_FACTOR is unset for the same reason: a stale value in
    # the caller's environment must not satisfy the probe-evidence check.
    unset H100_CHAIN_ARGS
    unset H100_CORESIDENCY_FACTOR
    # shellcheck disable=SC1090
    source "$H100_POSTURE_ENV"
    if ! declare -p H100_CHAIN_ARGS >/dev/null 2>&1; then
        echo "ERROR: $H100_POSTURE_ENV did not define the H100_CHAIN_ARGS array" >&2
        exit 1
    fi
    if [ -n "$BAND" ]; then
        # Four co-resident chains multiply every wall time; the watchdog and
        # time budgets are only meaningful once the 4-way slowdown factor has
        # been MEASURED on the campaign card. The stale 5090 pairwise figure
        # (1.85-2.13x) is a lower bound and must never be reused.
        if [ -z "${H100_CORESIDENCY_FACTOR:-}" ]; then
            echo "ERROR: campaign band mode with --h100 requires a probe-measured" >&2
            echo "  H100_CORESIDENCY_FACTOR in $H100_POSTURE_ENV." >&2
            echo "  Run the GPU-C calibration probe first and copy the derived factor" >&2
            echo "  from gpu_c_probe_result.json into the posture (version bump):" >&2
            echo "    bash $CORESIDENCY_PROBE" >&2
            exit 1
        fi
        echo "[prior-baseline] coresidency_factor=${H100_CORESIDENCY_FACTOR} (probe-measured, posture v${H100_POSTURE_VERSION:-?})"
    fi
fi

CHAIN_ARGS=(
    --mode "$MODE"
    --workspace "$WORKSPACE"
    --run_name "$RUN_NAME"
    "${ARM_ARGS[@]}"
)
if [ "${#BAND_ARGS[@]}" -gt 0 ]; then
    CHAIN_ARGS+=("${BAND_ARGS[@]}")
fi
if [ "${#FIXED_ARGS[@]}" -gt 0 ]; then
    CHAIN_ARGS+=("${FIXED_ARGS[@]}")
fi
CHAIN_ARGS+=(${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"})
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
            --data_dir|--llm_config|--execution_regime)
                IDENTITY_FLAGS+=("${args[$i]}" "${args[$((i+1))]}"); i=$((i+2)) ;;
            --enable_chain_incumbent_formal_gates)
                IDENTITY_FLAGS+=("${args[$i]}"); i=$((i+1)) ;;
            *) i=$((i+1)) ;;
        esac
    done
}

echo "[prior-baseline] arm=$ARM workspace=$WORKSPACE run_name=$RUN_NAME mode=$MODE h100=$H100 dry_run=$DRY_RUN${BAND:+ band=$BAND}${FIXED_CANDIDATE:+ fixed_candidate=$FIXED_CANDIDATE}"
echo "[prior-baseline] pythonpath_pin=${PROJECT_DIR}"

if [ "$DRY_RUN" -eq 1 ]; then
    resolve_python
    identity_flags ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} ${H100_CHAIN_ARGS[@]+"${H100_CHAIN_ARGS[@]}"}
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
        "${ARM_ARGS[@]}" ${BAND_ARGS[@]+"${BAND_ARGS[@]}"} "${IDENTITY_FLAGS[@]}")
    exec bash "$RUN_CHAIN" "${CHAIN_ARGS[@]}" --dry-run
fi

exec bash "$RUN_CHAIN" "${CHAIN_ARGS[@]}"
