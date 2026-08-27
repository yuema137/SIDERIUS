#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Gold campaign — STAGE 2 strict retrain (exec, do not source)
# ---------------------------------------------------------------------------
# Role   : the frozen-design retrains (D-ARCH-1 stage_2; plan section
#          20A.10): 4 designs x 4 target bands = 16 independent units.
#          The DESIGN is frozen, never the Stage-1 weights — each unit
#          trains from scratch through the chain's EXISTING
#          --validation_fixed_candidate_plan seam (the proposer is
#          bypassed; the plan file is the frozen ProposalOutput champion),
#          pinned to ONE iteration (D-ARCH-2). No search is reopened.
#
# Waves  : wave k = design k across all four bands IN PARALLEL, one band
#          per GPU (the frozen single-resident map); waves run
#          SEQUENTIALLY. Wave membership is launcher policy (contract
#          section 2), so changing it is a launcher edit, not a layout one.
#
# Layout : per contract section 2 —
#            {workspace_root}/stage2/{design}_{band}/workspace/     (chain ws)
#            {workspace_root}/stage2/{design}_{band}/deliverables/  (target-band copies: 4/6/5/5)
#            {workspace_root}/stage2/{design}_{band}/COMPLETE.json  (atomic, LAST)
#          A unit whose COMPLETE.json exists is SKIPPED (idempotent
#          resume; Stage-3 polls only the marker).
#
# Registry: --design_registry DIR must hold exactly FOUR <design>.json
#          plan files (the campaign's frozen design registry; contract
#          section 2 fixes 16 units).
#
# --dry-run prints the frozen table and all 16 fully-resolved per-unit
# run_chain argvs (or SKIP lines), launches nothing, writes nothing.
# ---------------------------------------------------------------------------

set -e
set -o pipefail

GOLD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_gold_campaign_lib.sh
source "${GOLD_SCRIPT_DIR}/_gold_campaign_lib.sh"

stage2_main() {
    local WORKSPACE_ROOT="" ARM="goldpod" ADVICE_FILE="" ADVICE_SHA256="" DESIGN_REGISTRY=""
    local DRY_RUN=0
    # F-PROFILE-WIRE-1 — command-line only; never inherited from the shell.
    GOLD_REQUIRED_RUNTIME_PROFILE_PATH=""
    GOLD_REQUIRED_RUNTIME_PROFILE=""
    GOLD_REQUIRED_RUNTIME_PROFILE_SHA256=""
    # D-HW-6 — command-line only; never inherited from the shell.
    GOLD_TRIAL_VRAM_BUDGET_GB=""
    GOLD_FORMAL_VRAM_BUDGET_GB=""
    local PASSTHROUGH=()

    while [[ $# -gt 0 ]]; do
        case $1 in
            --workspace_root|--workspace-root) WORKSPACE_ROOT="$2"; shift 2 ;;
            --arm)               ARM="$2"; shift 2 ;;
            --gold_advice_file)  ADVICE_FILE="$2"; shift 2 ;;
            --gold_advice_sha256) ADVICE_SHA256="$2"; shift 2 ;;
            --gold_required_runtime_profile_path) GOLD_REQUIRED_RUNTIME_PROFILE_PATH="$2"; shift 2 ;;
            --gold_required_runtime_profile) GOLD_REQUIRED_RUNTIME_PROFILE="$2"; shift 2 ;;
            --gold_required_runtime_profile_sha256) GOLD_REQUIRED_RUNTIME_PROFILE_SHA256="$2"; shift 2 ;;
            --gold_trial_vram_budget_gb) GOLD_TRIAL_VRAM_BUDGET_GB="$2"; shift 2 ;;
            --gold_formal_vram_budget_gb) GOLD_FORMAL_VRAM_BUDGET_GB="$2"; shift 2 ;;
            --design_registry)   DESIGN_REGISTRY="$2"; shift 2 ;;
            --dry-run|--dry_run) DRY_RUN=1; shift ;;
            *)                   PASSTHROUGH+=("$1"); shift ;;
        esac
    done

    gold_refuse_reserved_passthrough ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} || return 1
    gold_workspace_root_check "$WORKSPACE_ROOT" || return 1
    # NOTE (flagged for supervisor review in the F-LAUNCH-1 PR body): the
    # arm's treatment condition is kept UNIFORM across its own campaign —
    # goldpod Stage-2 units carry the same --advice artifact its Stage-1
    # chains carried (the retrain bypasses the proposer, so the artifact
    # reaches only the non-proposer roles that already saw it in Stage-1).
    # The campaign's ONE observed treatment identity (empty when this
    # script was invoked directly): gold_arm_args refuses when its own
    # read of the artifact disagrees.
    gold_arm_args "$ARM" "$ADVICE_FILE" "$ADVICE_SHA256" || return 1
    # F-GENLIB-WIRE-1: enforced in EVERY stage, not only the entrypoint —
    # a stage script invoked directly must refuse the same undeclared
    # library root, and this is what makes GOLD_GENERATED_LIBRARY_DIR
    # populated for the dry-run row in this process.
    gold_require_generated_library || return 1
    gold_frozen_chain_args stage2 || return 1

    if [ -z "$DESIGN_REGISTRY" ] || [ ! -d "$DESIGN_REGISTRY" ]; then
        echo "ERROR: --design_registry must be an existing directory of frozen design plans: '${DESIGN_REGISTRY}'" >&2
        return 1
    fi
    local DESIGN_FILES=()
    local f
    for f in "$DESIGN_REGISTRY"/*.json; do
        [ -e "$f" ] || continue
        DESIGN_FILES+=("$f")
    done
    if [ "${#DESIGN_FILES[@]}" -ne 4 ]; then
        echo "ERROR: the design registry must hold exactly FOUR <design>.json plans" >&2
        echo "  (contract section 2: 16 units = 4 designs x 4 bands); found ${#DESIGN_FILES[@]}" >&2
        echo "  in $DESIGN_REGISTRY" >&2
        return 1
    fi
    local DESIGNS=() DESIGN_ABS=()
    local base design
    for f in "${DESIGN_FILES[@]}"; do
        base="$(basename "$f")"
        design="${base%.json}"
        if ! [[ "$design" =~ ^[A-Za-z0-9_-]+$ ]]; then
            echo "ERROR: design id '$design' (from $base) must match [A-Za-z0-9_-]+ — it names" >&2
            echo "  the contract's stage2/{design}_{band}/ directory." >&2
            return 1
        fi
        DESIGNS+=("$design")
        DESIGN_ABS+=("$(cd "$(dirname "$f")" && pwd)/$base")
    done
    if [ "$DRY_RUN" -ne 1 ]; then
        gold_refuse_preset_cuda || return 1
    fi

    echo "[gold-stage2] arm=$ARM workspace_root=$WORKSPACE_ROOT designs=${DESIGNS[*]} dry_run=$DRY_RUN"
    gold_print_frozen_table

    local STAGE2_ROOT="${WORKSPACE_ROOT%/}/stage2"
    local incomplete=0 wave=0

    local i band gpu unit ws run_name plan
    for i in "${!DESIGNS[@]}"; do
        design="${DESIGNS[$i]}"
        plan="${DESIGN_ABS[$i]}"
        wave=$((wave + 1))
        echo ""
        echo "[gold-stage2] ==== wave $wave/4: design $design (plan: $plan) ===="

        local WAVE_PIDS=() WAVE_BANDS=() WAVE_UNITS=()
        for band in "${GOLD_BANDS[@]}"; do
            unit="${STAGE2_ROOT}/${design}_${band}"
            ws="${unit}/workspace"
            run_name="${ARM}_stage2_${design}_${band}"
            gpu="$(gold_band_gpu "$band")" || return 1
            gold_band_args "$band" || return 1

            if [ -f "${unit}/COMPLETE.json" ]; then
                echo "[gold-stage2] unit ${design}_${band}: SKIP (COMPLETE.json exists)"
                continue
            fi

            local UNIT_CMD=(
                bash "${GOLD_SCRIPT_DIR}/run_chain.sh"
                --mode lilab
                --workspace "$ws"
                --run_name "$run_name"
                --validation_fixed_candidate_plan "$plan"
                "${GOLD_FROZEN_CHAIN_ARGS[@]}"
                "${GOLD_BAND_ARGS[@]}"
                "${GOLD_ARM_ARGS[@]}"
            )
            UNIT_CMD+=(${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"})

            if [ "$DRY_RUN" -eq 1 ]; then
                echo "[gold-stage2] unit ${design}_${band} gpu=$gpu run_chain argv:"
                printf '%q ' "CUDA_VISIBLE_DEVICES=$gpu" "${UNIT_CMD[@]}"
                echo ""
                continue
            fi

            mkdir -p "$ws"
            local LOG="${unit}/unit_chain.log"
            CUDA_VISIBLE_DEVICES="$gpu" nohup "${UNIT_CMD[@]}" >> "$LOG" 2>&1 &
            WAVE_PIDS+=($!)
            WAVE_BANDS+=("$band")
            WAVE_UNITS+=("$unit")
            echo "[gold-stage2] unit ${design}_${band} -> gpu $gpu pid ${WAVE_PIDS[-1]} log $LOG"
        done

        [ "$DRY_RUN" -eq 1 ] && continue

        # Wait for the whole wave; relay TERM/INT to every live unit chain.
        trap 'for p in ${WAVE_PIDS[@]+"${WAVE_PIDS[@]}"}; do kill -TERM "$p" 2>/dev/null; done' TERM INT HUP
        local j rc
        for j in "${!WAVE_PIDS[@]}"; do
            rc=0
            wait "${WAVE_PIDS[$j]}" || rc=$?
            while kill -0 "${WAVE_PIDS[$j]}" 2>/dev/null; do
                rc=0
                wait "${WAVE_PIDS[$j]}" || rc=$?
            done
            echo "[gold-stage2] unit ${design}_${WAVE_BANDS[$j]}: chain exit $rc"
            if [ "$rc" -ne 0 ]; then
                echo "[gold-stage2] unit ${design}_${WAVE_BANDS[$j]}: NOT finalized (chain rc=$rc)" >&2
                incomplete=$((incomplete + 1))
                WAVE_UNITS[$j]=""
            fi
        done
        trap - TERM INT HUP

        # Finalize the wave's successful units: winner scan (contract
        # section 1 rule) + TARGET-BAND deliverable COPIES (band file set
        # via DataScope.from_cli, count 4/6/5/5 — Q-S3-2 ruling A) + atomic
        # COMPLETE.json, written LAST. A refusal leaves NO marker (Stage-3
        # ignores the dir).
        gold_resolve_python_stage2 || return 1
        for j in "${!WAVE_UNITS[@]}"; do
            unit="${WAVE_UNITS[$j]}"
            [ -z "$unit" ] && continue
            band="${WAVE_BANDS[$j]}"
            if ! "${GOLD_PY[@]}" "${GOLD_SCRIPT_DIR}/gold_campaign_state.py" stage2-finalize \
                --unit-dir "$unit" --design "$design" --target-band "$band"; then
                echo "[gold-stage2] unit ${design}_${band}: finalize REFUSED (no COMPLETE.json written)" >&2
                incomplete=$((incomplete + 1))
            else
                echo "[gold-stage2] unit ${design}_${band}: COMPLETE.json written"
            fi
        done
    done

    if [ "$DRY_RUN" -eq 1 ]; then
        echo ""
        echo "[gold-stage2] DRY-RUN COMPLETE — 4 waves x 4 bands walked, nothing launched"
        return 0
    fi

    echo ""
    local done_count
    done_count="$(find "$STAGE2_ROOT" -maxdepth 2 -name COMPLETE.json 2>/dev/null | wc -l)"
    echo "[gold-stage2] stage 2 pass finished: ${done_count}/16 units carry COMPLETE.json (incomplete this pass: $incomplete)"
    if [ "$done_count" -eq 16 ]; then
        return 0
    fi
    echo "[gold-stage2] re-run this script to retry units without markers (completed units are skipped)" >&2
    return 1
}

# Python resolution for the finalizer (same precedence as the band loop's
# helper resolution; run_chain resolves its own interpreter for the chains).
gold_resolve_python_stage2() {
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        GOLD_PY=("$VIRTUAL_ENV/bin/python")
    elif [ -x "${GOLD_PROJECT_DIR}/.venv/bin/python" ]; then
        GOLD_PY=("${GOLD_PROJECT_DIR}/.venv/bin/python")
    elif command -v python3 >/dev/null 2>&1; then
        GOLD_PY=(python3)
        echo "[gold-stage2] WARNING: no venv found — finalizer uses system python3" >&2
    else
        echo "ERROR: no python interpreter for the stage-2 finalizer" >&2
        return 1
    fi
    export PYTHONPATH="${GOLD_PROJECT_DIR}${PYTHONPATH:+:$PYTHONPATH}"
}

# Source-safe entry guard (house convention; see
# tests/unit/sdsc_submission_scripts/test_source_safe_entry.py rationale).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    stage2_main "$@"
    exit $?
fi
