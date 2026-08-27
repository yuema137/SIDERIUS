#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Gold campaign — CANONICAL ENTRYPOINT (D-ARCH-1; exec, do not source)
# ---------------------------------------------------------------------------
# Role   : the ONE thin campaign launcher. Binds the frozen authorities at
#          the shared boundary (_gold_campaign_lib.sh), records the resolved
#          launch manifest, and DISPATCHES to the stage orchestrators. It
#          implements NO scientific workflow: the iteration unit is the
#          existing chain (run_chain.sh -> run_one_iteration.py), reused
#          unchanged.
#
# Hierarchy (v19/v20 style, not a monolith):
#   run_gold_campaign.sh                     this file — bind + dispatch
#     stage1_search.sh                       four bands, one GPU each
#       stage1_run_band.sh                   persisted-state band loop
#         run_chain.sh / _chain_common.sh    EXISTING iteration execution
#     stage2_strict_retrain.sh               4 designs x 4 bands = 16 units
#         run_chain.sh (--validation_fixed_candidate_plan seam)
#
# NOT this launcher: launch_prior_baseline_experiment.sh (X9's experiment —
# its arms are with/without-prior-art and it refuses advice BY DESIGN; it
# stays untouched for X9 reproducibility, operator ruling D-ARCH-1/F-LAUNCH-2).
#
# Usage:
#   bash sdsc_submission_scripts/run_gold_campaign.sh \
#       --workspace_root DIR --stage 1 \
#       --gold_advice_file ADVICE.json \
#       [--arm goldpod|blindpod] [--task_config PATH] \
#       [--fcnet_reference_json PATH] [--only 0-3,4-9] \
#       [--stagger-seconds S] [--dry-run] [passthrough run_chain.sh flags...]
#
#   bash sdsc_submission_scripts/run_gold_campaign.sh \
#       --workspace_root DIR --stage 2 --design_registry DIR \
#       --gold_advice_file ADVICE.json [--dry-run] [...]
#
# Frozen bindings (see _gold_campaign_lib.sh for the table + decisions):
#   * the thirteen chain-boundary values, typed, never defaulted;
#   * arm label goldpod|blindpod (X9 labels refused; R-ARM-STAMP-1);
#   * lit-review EXPLICITLY OFF in both arms (Q-LIT-1 = OFF, symmetric);
#   * the treatment boundary: --gold_advice_file -> --advice (goldpod only);
#   * band->GPU map 0-3->0, 4-9->1, 10-14->2, 15-19->3 (single_resident);
#   * R-RETENTION-1: --no-cleanup_denoised always; --cleanup_denoised refused.
#
# --dry-run prints the frozen table and every fully-resolved per-band (or
# per-unit) run_chain argv without launching anything or writing any file.
# ---------------------------------------------------------------------------

set -e
set -o pipefail

GOLD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_gold_campaign_lib.sh
source "${GOLD_SCRIPT_DIR}/_gold_campaign_lib.sh"

gold_usage() {
    sed -n '2,50p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

gold_main() {
    local WORKSPACE_ROOT="" STAGE="" ARM="goldpod" ADVICE_FILE=""
    local TASK_CONFIG="${GOLD_PROJECT_DIR}/configs/task_config.yaml"
    local DESIGN_REGISTRY="" FCNET_REFERENCE_JSON="" ONLY="" STAGGER=60
    local DRY_RUN=0
    local PASSTHROUGH=()

    while [[ $# -gt 0 ]]; do
        case $1 in
            --workspace_root|--workspace-root) WORKSPACE_ROOT="$2"; shift 2 ;;
            --stage)               STAGE="$2"; shift 2 ;;
            --arm)                 ARM="$2"; shift 2 ;;
            --gold_advice_file)    ADVICE_FILE="$2"; shift 2 ;;
            --task_config)         TASK_CONFIG="$2"; shift 2 ;;
            --design_registry)     DESIGN_REGISTRY="$2"; shift 2 ;;
            --fcnet_reference_json) FCNET_REFERENCE_JSON="$2"; shift 2 ;;
            --only)                ONLY="$2"; shift 2 ;;
            --stagger-seconds|--stagger_seconds) STAGGER="$2"; shift 2 ;;
            --dry-run|--dry_run)   DRY_RUN=1; shift ;;
            -h|--help)             gold_usage; return 0 ;;
            *)                     PASSTHROUGH+=("$1"); shift ;;
        esac
    done

    # Boundary refusals BEFORE any work: retention (R-RETENTION-1) and every
    # frozen/arm/band-decided flag, by name.
    gold_refuse_reserved_passthrough ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} || return 1
    gold_workspace_root_check "$WORKSPACE_ROOT" || return 1
    gold_arm_args "$ARM" "$ADVICE_FILE" || return 1
    gold_bind_task_config "$TASK_CONFIG" || return 1
    if [ -n "$FCNET_REFERENCE_JSON" ] && [ ! -f "$FCNET_REFERENCE_JSON" ]; then
        echo "ERROR: --fcnet_reference_json not found: $FCNET_REFERENCE_JSON" >&2
        return 1
    fi

    case "$STAGE" in
        1|2) ;;
        "")
            echo "Required: --stage 1 (per-band search) or --stage 2 (strict retrain)" >&2
            return 1 ;;
        *)
            echo "ERROR: unknown --stage '$STAGE' (expected 1 or 2)" >&2
            return 1 ;;
    esac
    if [ "$STAGE" = "2" ] && [ -z "$DESIGN_REGISTRY" ]; then
        echo "ERROR: --stage 2 requires --design_registry DIR (the four frozen design plans" >&2
        echo "  produced by the Stage-1 freeze; one <design>.json ProposalOutput plan each)." >&2
        return 1
    fi

    echo "[gold-campaign] arm=$ARM stage=$STAGE workspace_root=$WORKSPACE_ROOT dry_run=$DRY_RUN"
    echo "[gold-campaign] task_config=$GOLD_TASK_CONFIG_ABS sha256=$GOLD_TASK_CONFIG_SHA256"
    if [ "$ARM" = "goldpod" ]; then
        echo "[gold-campaign] treatment: advice=$ADVICE_FILE (goldpod, injected every proposer round)"
    else
        echo "[gold-campaign] treatment: advice=EXPLICIT_NONE (blindpod, named absence)"
    fi
    echo "[gold-campaign] lit_review=OFF (operator Q-LIT-1; explicit --no-ml_lit_review_enabled, symmetric)"
    gold_print_frozen_table

    # The resolved launch manifest — every behaviorally relevant value the
    # entrypoint bound, as one record beside the campaign data (golden
    # notebook section 8: no silent mutable defaults). Dry-runs write nothing.
    if [ "$DRY_RUN" -ne 1 ]; then
        local MANIFEST="${WORKSPACE_ROOT%/}/gold_campaign_launch_$(date -u +%Y%m%dT%H%M%SZ)_stage${STAGE}.json"
        {
            echo "{"
            echo "  \"entrypoint\": \"run_gold_campaign.sh\","
            echo "  \"stage\": ${STAGE},"
            echo "  \"arm\": \"${ARM}\","
            echo "  \"advice_file\": $(if [ -n "$ADVICE_FILE" ]; then printf '"%s"' "$ADVICE_FILE"; else printf '"EXPLICIT_NONE"'; fi),"
            echo "  \"lit_review\": \"OFF (Q-LIT-1, explicit --no-ml_lit_review_enabled, symmetric)\","
            echo "  \"task_config\": \"${GOLD_TASK_CONFIG_ABS}\","
            echo "  \"task_config_sha256\": \"${GOLD_TASK_CONFIG_SHA256}\","
            echo "  \"fcnet_reference_json\": $(if [ -n "$FCNET_REFERENCE_JSON" ]; then printf '"%s"' "$FCNET_REFERENCE_JSON"; else printf 'null'; fi),"
            echo "  \"frozen_values\": {"
            local row first=1
            for row in "${GOLD_FROZEN_ROWS[@]}"; do
                [ "$first" -eq 0 ] && echo ","
                first=0
                printf '    "%s": "%s"' "${row%%=*}" "${row#*=}"
            done
            echo ""
            echo "  },"
            echo "  \"stage2_num_iterations\": ${GOLD_STAGE2_NUM_ITERATIONS},"
            echo "  \"retention\": \"--no-cleanup_denoised (R-RETENTION-1)\","
            echo "  \"gpu_map\": {\"0-3\": 0, \"4-9\": 1, \"10-14\": 2, \"15-19\": 3},"
            echo "  \"launched_utc\": \"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\""
            echo "}"
        } > "$MANIFEST"
        echo "[gold-campaign] launch manifest: $MANIFEST"
    fi

    local COMMON=(
        --workspace_root "$WORKSPACE_ROOT"
        --arm "$ARM"
    )
    [ -n "$ADVICE_FILE" ] && COMMON+=(--gold_advice_file "$ADVICE_FILE")
    [ "$DRY_RUN" -eq 1 ] && COMMON+=(--dry-run)

    case "$STAGE" in
        1)
            local S1=("${COMMON[@]}" --stagger-seconds "$STAGGER")
            [ -n "$ONLY" ] && S1+=(--only "$ONLY")
            [ -n "$FCNET_REFERENCE_JSON" ] && S1+=(--fcnet_reference_json "$FCNET_REFERENCE_JSON")
            exec bash "${GOLD_SCRIPT_DIR}/stage1_search.sh" "${S1[@]}" \
                ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
            ;;
        2)
            exec bash "${GOLD_SCRIPT_DIR}/stage2_strict_retrain.sh" "${COMMON[@]}" \
                --design_registry "$DESIGN_REGISTRY" \
                ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
            ;;
    esac
}

# Source-safe entry guard (house convention; see
# tests/unit/sdsc_submission_scripts/test_source_safe_entry.py rationale).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    gold_main "$@"
    exit $?
fi
