#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS band fleet — FOUR co-resident band chains of ONE arm on one GPU
# ---------------------------------------------------------------------------
# Role   : launch the four campaign band chains (0-3, 4-9, 10-14, 15-19) of
#          one experiment arm on one H100 card, per the arXiv launch
#          topology (author ruling 2026-08-25):
#
#            GPU A — WITH arm    (--card A == --arm with-prior-art)
#            GPU B — WITHOUT arm (--card B == --arm without-prior-art)
#            GPU C — calibration (--card C is REFUSED here: that card runs
#                                 gpu_c_coresidency_probe.sh, not chains)
#
#          Each chain is one launch_prior_baseline_experiment.sh invocation
#          in campaign band mode (--band + --workspace-root); the four
#          workspaces and run names derive from arm+band and can never
#          collide. Launches are SEQUENTIAL nohup background starts with a
#          stagger between them (so four cold-start VRAM probes and LLM
#          bursts do not land in the same second); the chains then run
#          CONCURRENTLY. No scheduler is assumed.
#
# GPU    : honors CUDA_VISIBLE_DEVICES. Pass --gpu N to pin the fleet to
#          one device index (exported to every chain); with neither, the
#          chains see every visible device — on the campaign hosts always
#          pin one card per fleet.
#
# Posture: --h100 is ON by default (this is the H100 fleet script); each
#          chain launcher sources h100_posture.env itself and REFUSES the
#          launch when H100_CORESIDENCY_FACTOR is empty (the GPU-C probe
#          must run first). --no-h100 opts out (dev/dry-run only).
#
# Logs   : ${WORKSPACE_ROOT}/fleet_logs/${ARM}_band${BAND}.launch.log per
#          chain, plus a PID manifest fleet_${ARM}_<epoch>.pids
#          ("band pid logfile" rows) for monitoring and shutdown.
#
# Usage:
#   bash sdsc_submission_scripts/launch_band_fleet.sh \
#       (--arm with-prior-art|without-prior-art | --card A|B) \
#       --workspace-root DIR [--gpu N] [--fixed-candidate PLAN.json] \
#       [--stagger-seconds S] [--no-h100] [--dry-run] \
#       [passthrough run_chain.sh flags...]
#
#   --dry-run runs the four band launchers FOREGROUND sequentially with
#   --dry-run (exact child argv + resolved config JSON, no side effects,
#   no nohup). --fixed-candidate forwards the frozen champion plan to all
#   four chains (the post-freeze finalization retrains: champion x 4 bands
#   x this arm). Passthrough flags go to every chain identically; --band /
#   --workspace / --data_scope / --health_gate_files are refused (the
#   fleet and the band decide them).
# ---------------------------------------------------------------------------

set -e
set -o pipefail

FLEET_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# E1 pin (see launch_prior_baseline_experiment.sh) — exported here too so a
# direct fleet invocation is covered even before the launcher re-exports it.
export PYTHONPATH="$(cd "${FLEET_SCRIPT_DIR}/.." && pwd)${PYTHONPATH:+:${PYTHONPATH}}"
LAUNCHER="${FLEET_SCRIPT_DIR}/launch_prior_baseline_experiment.sh"

#: The four campaign bands. The band->scope/health mapping authority is the
#: band launcher's own case table; an unknown band refuses THERE, so this
#: roster cannot silently drift into unmapped territory.
FLEET_BANDS=("0-3" "4-9" "10-14" "15-19")

fleet_usage() {
    sed -n '2,50p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

fleet_main() {
    local ARM="" CARD="" WORKSPACE_ROOT="" GPU="" FIXED_CANDIDATE=""
    local STAGGER="${H100_FLEET_STAGGER_SECONDS:-60}"
    local H100=1 DRY_RUN=0
    local PASSTHROUGH=()

    while [[ $# -gt 0 ]]; do
        case $1 in
            --arm)               ARM="$2"; shift 2 ;;
            --card)              CARD="$2"; shift 2 ;;
            --workspace-root|--workspace_root) WORKSPACE_ROOT="$2"; shift 2 ;;
            --gpu)               GPU="$2"; shift 2 ;;
            --fixed-candidate|--fixed_candidate) FIXED_CANDIDATE="$2"; shift 2 ;;
            --stagger-seconds|--stagger_seconds) STAGGER="$2"; shift 2 ;;
            --no-h100)           H100=0; shift ;;
            --dry-run|--dry_run) DRY_RUN=1; shift ;;
            -h|--help)           fleet_usage; return 0 ;;
            --band|--workspace|--data_scope|--health_gate_files)
                echo "ERROR: $1 is decided by the fleet/band topology and cannot be passed through" >&2
                return 1 ;;
            *)                   PASSTHROUGH+=("$1"); shift ;;
        esac
    done

    if [ -n "$CARD" ]; then
        if [ -n "$ARM" ]; then
            echo "ERROR: pass --arm or --card, not both" >&2
            return 1
        fi
        case "$CARD" in
            A) ARM="with-prior-art" ;;
            B) ARM="without-prior-art" ;;
            C)
                echo "ERROR: --card C is the calibration/support card — it runs" >&2
                echo "  gpu_c_coresidency_probe.sh (and campaign_preflight.sh), never band chains." >&2
                return 1 ;;
            *)
                echo "ERROR: unknown --card '$CARD' (expected A, B or C)" >&2
                return 1 ;;
        esac
    fi
    if [ -z "$ARM" ]; then
        echo "Required: --arm with-prior-art|without-prior-art (or --card A|B)" >&2
        return 1
    fi
    if [ -z "$WORKSPACE_ROOT" ]; then
        echo "Required: --workspace-root DIR (the persistent-volume campaign root)" >&2
        return 1
    fi
    # Fail the whole fleet up-front rather than once per nohup'd chain.
    if [ ! -d "$WORKSPACE_ROOT" ] || [ ! -w "$WORKSPACE_ROOT" ]; then
        echo "ERROR: --workspace-root must be an existing writable directory: $WORKSPACE_ROOT" >&2
        return 1
    fi
    if ! [[ "$STAGGER" =~ ^[0-9]+$ ]]; then
        echo "ERROR: --stagger-seconds must be a non-negative integer, got '$STAGGER'" >&2
        return 1
    fi

    local COMMON_ARGS=(--workspace-root "$WORKSPACE_ROOT")
    [ "$H100" -eq 1 ] && COMMON_ARGS+=(--h100)
    [ -n "$FIXED_CANDIDATE" ] && COMMON_ARGS+=(--fixed-candidate "$FIXED_CANDIDATE")

    if [ -n "$GPU" ]; then
        export CUDA_VISIBLE_DEVICES="$GPU"
        echo "[band-fleet] CUDA_VISIBLE_DEVICES=$GPU (pinned by --gpu)"
    elif [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
        echo "[band-fleet] CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES} (inherited)"
    else
        echo "[band-fleet] WARNING: CUDA_VISIBLE_DEVICES unset — chains see every visible device;" >&2
        echo "  on a campaign host pass --gpu N to pin this fleet to one card." >&2
    fi

    echo "[band-fleet] arm=$ARM workspace_root=$WORKSPACE_ROOT h100=$H100 dry_run=$DRY_RUN stagger=${STAGGER}s bands=${FLEET_BANDS[*]}"

    if [ "$DRY_RUN" -eq 1 ]; then
        local band
        for band in "${FLEET_BANDS[@]}"; do
            echo ""
            echo "[band-fleet] ---- dry-run band $band ----"
            bash "$LAUNCHER" --arm "$ARM" --band "$band" "${COMMON_ARGS[@]}" \
                ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} --dry-run
        done
        echo "[band-fleet] DRY-RUN COMPLETE — 4 band chains walked, nothing launched"
        return 0
    fi

    local LOG_DIR="${WORKSPACE_ROOT%/}/fleet_logs"
    mkdir -p "$LOG_DIR"
    local PID_MANIFEST="${LOG_DIR}/fleet_${ARM}_$(date +%s).pids"
    : > "$PID_MANIFEST"

    local band first=1
    for band in "${FLEET_BANDS[@]}"; do
        if [ "$first" -eq 0 ] && [ "$STAGGER" -gt 0 ]; then
            echo "[band-fleet] stagger ${STAGGER}s before band $band"
            sleep "$STAGGER"
        fi
        first=0
        local LOG="${LOG_DIR}/${ARM}_band${band}.launch.log"
        nohup bash "$LAUNCHER" --arm "$ARM" --band "$band" "${COMMON_ARGS[@]}" \
            ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} >> "$LOG" 2>&1 &
        local PID=$!
        printf '%s %s %s\n' "$band" "$PID" "$LOG" >> "$PID_MANIFEST"
        echo "[band-fleet] band $band -> pid $PID log $LOG"
    done

    echo ""
    echo "[band-fleet] 4 band chains launched (arm=$ARM). PID manifest: $PID_MANIFEST"
    echo "[band-fleet] monitor:  tail -f ${LOG_DIR}/${ARM}_band*.launch.log"
    echo "[band-fleet] shutdown: kill \$(awk '{print \$2}' $PID_MANIFEST)  # then wait for children"
}

# Source-safe entry guard (house convention, tests/unit/sdsc_submission_scripts/
# test_source_safe_entry.py rationale): sourcing this file for its functions
# must never launch anything.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    fleet_main "$@"
    exit $?
fi
