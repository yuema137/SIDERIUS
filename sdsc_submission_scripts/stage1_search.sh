#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Gold campaign — STAGE 1 fan-out (exec, do not source)
# ---------------------------------------------------------------------------
# Role   : launch the per-band search for the selected bands, ONE BAND PER
#          GPU per the frozen single-resident map (0-3->0, 4-9->1,
#          10-14->2, 15-19->3). Each band is one stage1_run_band.sh
#          process, nohup'd with a stagger between starts (so four
#          cold-start VRAM probes and LLM bursts never land in the same
#          second — the fleet-launcher pattern, reused).
#
# Called by run_gold_campaign.sh; may also be invoked directly with the
# same argument vocabulary (the frozen boundary is the sourced lib either
# way, so no value can fork between the two paths).
#
# Logs   : ${WORKSPACE_ROOT}/gold_stage1_logs/${ARM}_band${BAND}.launch.log
#          per band, plus a PID manifest gold_stage1_${ARM}_<epoch>.pids
#          ("band pid logfile" rows) for monitoring and shutdown.
#
# --dry-run runs each selected band's stage1_run_band.sh --dry-run in the
# FOREGROUND (fully-resolved argv per band, nothing launched, no writes).
# ---------------------------------------------------------------------------

set -e
set -o pipefail

GOLD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_gold_campaign_lib.sh
source "${GOLD_SCRIPT_DIR}/_gold_campaign_lib.sh"

stage1_main() {
    local WORKSPACE_ROOT="" ARM="goldpod" ADVICE_FILE="" ADVICE_SHA256="" FCNET_REFERENCE_JSON=""
    local ONLY="" STAGGER=60 DRY_RUN=0
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
            --arm)                  ARM="$2"; shift 2 ;;
            --gold_advice_file)     ADVICE_FILE="$2"; shift 2 ;;
            --gold_advice_sha256) ADVICE_SHA256="$2"; shift 2 ;;
            --gold_required_runtime_profile_path) GOLD_REQUIRED_RUNTIME_PROFILE_PATH="$2"; shift 2 ;;
            --gold_required_runtime_profile) GOLD_REQUIRED_RUNTIME_PROFILE="$2"; shift 2 ;;
            --gold_required_runtime_profile_sha256) GOLD_REQUIRED_RUNTIME_PROFILE_SHA256="$2"; shift 2 ;;
            --gold_trial_vram_budget_gb) GOLD_TRIAL_VRAM_BUDGET_GB="$2"; shift 2 ;;
            --gold_formal_vram_budget_gb) GOLD_FORMAL_VRAM_BUDGET_GB="$2"; shift 2 ;;
            --fcnet_reference_json) FCNET_REFERENCE_JSON="$2"; shift 2 ;;
            --only)                 ONLY="$2"; shift 2 ;;
            --stagger-seconds|--stagger_seconds) STAGGER="$2"; shift 2 ;;
            --dry-run|--dry_run)    DRY_RUN=1; shift ;;
            *)                      PASSTHROUGH+=("$1"); shift ;;
        esac
    done

    gold_refuse_reserved_passthrough ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} || return 1
    gold_workspace_root_check "$WORKSPACE_ROOT" || return 1
    # Validates the arm + advice pairing up-front (each band re-derives its
    # own argv from the same lib, so this is a fail-fast, not the binding).
    # The campaign's ONE observed treatment identity (empty when this
    # script was invoked directly): gold_arm_args refuses when its own
    # read of the artifact disagrees.
    gold_arm_args "$ARM" "$ADVICE_FILE" "$ADVICE_SHA256" || return 1
    # F-GENLIB-WIRE-1: enforced in EVERY stage, not only the entrypoint —
    # a stage script invoked directly must refuse the same undeclared
    # library root, and this is what makes GOLD_GENERATED_LIBRARY_DIR
    # populated for the dry-run row in this process.
    gold_require_generated_library || return 1
    if ! [[ "$STAGGER" =~ ^[0-9]+$ ]]; then
        echo "ERROR: --stagger-seconds must be a non-negative integer, got '$STAGGER'" >&2
        return 1
    fi
    local SELECTED
    SELECTED="$(gold_select_bands "$ONLY")" || return 1
    local BANDS=()
    local _band
    while IFS= read -r _band; do
        [ -n "$_band" ] && BANDS+=("$_band")
    done <<< "$SELECTED"
    if [ "${#BANDS[@]}" -eq 0 ]; then
        echo "ERROR: band selection resolved empty" >&2
        return 1
    fi
    if [ "$DRY_RUN" -ne 1 ]; then
        gold_refuse_preset_cuda || return 1
    fi

    echo "[gold-stage1] arm=$ARM workspace_root=$WORKSPACE_ROOT bands=${BANDS[*]} stagger=${STAGGER}s dry_run=$DRY_RUN"

    local BAND_ARGS_COMMON=(
        --workspace_root "$WORKSPACE_ROOT"
        --arm "$ARM"
    )
    [ -n "$ADVICE_FILE" ] && BAND_ARGS_COMMON+=(--gold_advice_file "$ADVICE_FILE")
    # Inherited, never recomputed here: recomputing would restore exactly the
    # per-band independent observation this threading exists to remove.
    [ -n "$ADVICE_SHA256" ] && BAND_ARGS_COMMON+=(--gold_advice_sha256 "$ADVICE_SHA256")
    # F-PROFILE-WIRE-1 — forwarded to every band, so all four bands of a
    # declared campaign certify the SAME overlay.
    [ -n "$GOLD_REQUIRED_RUNTIME_PROFILE" ] && BAND_ARGS_COMMON+=(
        --gold_required_runtime_profile_path "$GOLD_REQUIRED_RUNTIME_PROFILE_PATH"
        --gold_required_runtime_profile "$GOLD_REQUIRED_RUNTIME_PROFILE"
        --gold_required_runtime_profile_sha256 "$GOLD_REQUIRED_RUNTIME_PROFILE_SHA256")
    # D-HW-6 — forwarded to every band, so all four bands of a supplied
    # campaign run under the SAME per-mode ceiling.
    [ -n "$GOLD_TRIAL_VRAM_BUDGET_GB" ] && BAND_ARGS_COMMON+=(
        --gold_trial_vram_budget_gb "$GOLD_TRIAL_VRAM_BUDGET_GB"
        --gold_formal_vram_budget_gb "$GOLD_FORMAL_VRAM_BUDGET_GB")
    [ -n "$FCNET_REFERENCE_JSON" ] && BAND_ARGS_COMMON+=(--fcnet_reference_json "$FCNET_REFERENCE_JSON")

    if [ "$DRY_RUN" -eq 1 ]; then
        local band
        for band in "${BANDS[@]}"; do
            echo ""
            echo "[gold-stage1] ---- dry-run band $band ----"
            bash "${GOLD_SCRIPT_DIR}/stage1_run_band.sh" --band "$band" \
                "${BAND_ARGS_COMMON[@]}" --dry-run \
                ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} || return 1
        done
        echo "[gold-stage1] DRY-RUN COMPLETE — ${#BANDS[@]} band loops walked, nothing launched"
        return 0
    fi

    local LOG_DIR="${WORKSPACE_ROOT%/}/gold_stage1_logs"
    mkdir -p "$LOG_DIR"
    local PID_MANIFEST="${LOG_DIR}/gold_stage1_${ARM}_$(date +%s).pids"
    : > "$PID_MANIFEST"

    local band first=1 gpu LOG PID
    for band in "${BANDS[@]}"; do
        if [ "$first" -eq 0 ] && [ "$STAGGER" -gt 0 ]; then
            echo "[gold-stage1] stagger ${STAGGER}s before band $band"
            sleep "$STAGGER"
        fi
        first=0
        gpu="$(gold_band_gpu "$band")" || return 1
        LOG="${LOG_DIR}/${ARM}_band${band}.launch.log"
        CUDA_VISIBLE_DEVICES="$gpu" nohup bash "${GOLD_SCRIPT_DIR}/stage1_run_band.sh" \
            --band "$band" "${BAND_ARGS_COMMON[@]}" \
            ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} >> "$LOG" 2>&1 &
        PID=$!
        printf '%s %s %s\n' "$band" "$PID" "$LOG" >> "$PID_MANIFEST"
        echo "[gold-stage1] band $band -> gpu $gpu pid $PID log $LOG"
    done

    echo ""
    echo "[gold-stage1] ${#BANDS[@]} band loops launched (arm=$ARM). PID manifest: $PID_MANIFEST"
    echo "[gold-stage1] monitor:  tail -f ${LOG_DIR}/${ARM}_band*.launch.log"
    echo "[gold-stage1] stop one band after its current iteration: touch <band workspace>/STOP"
    echo "[gold-stage1] shutdown: kill \$(awk '{print \$2}' $PID_MANIFEST)  # bands relay TERM to their chain"
}

# Source-safe entry guard (house convention; see
# tests/unit/sdsc_submission_scripts/test_source_safe_entry.py rationale).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    stage1_main "$@"
    exit $?
fi
