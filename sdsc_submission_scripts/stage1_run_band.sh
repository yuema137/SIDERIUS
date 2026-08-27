#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Gold campaign — STAGE 1 per-band loop (exec, do not source)
# ---------------------------------------------------------------------------
# Role   : the band orchestrator (D-ARCH-1 invariant: it only inspects
#          persisted state, invokes, validates, updates the valid-formal
#          incumbent, and tests FCNet+2). One band, one GPU, one chain
#          workspace {workspace_root}/{arm}_band{BAND} (contract section 1).
#
# Loop   : each cycle re-derives EVERYTHING from persisted state
#          (gold_campaign_state.py — the inspect_run_state verifiers plus
#          the contract's winner rule), then invokes the EXISTING chain
#          (run_chain.sh, reused unchanged) over the FULL frozen horizon
#          with auto-resume, so the chain's own inspector picks the next
#          incomplete iteration and its #258 replacement path can retry a
#          failed tail. While the chain runs, a watcher polls committed
#          manifests, refreshes {workspace_root}/{arm}_band{BAND}.gold_status.json
#          (a SIBLING of the chain workspace, deliberately outside it: the
#          chain's stale-fresh guard treats a non-empty workspace at iter 1
#          as a wrong-workspace accident, and the contract freezes the
#          workspace's internal layout) with the cumulative HealthGate-valid
#          FORMAL incumbent per the contract's winner table, and — when the
#          FCNet+2 stop rule is EVALUABLE and
#          satisfied — requests a graceful stop through the chain's own C13
#          STOP-file channel ("stop after the current iteration"). The stop
#          rule is evaluable only when --fcnet_reference_json supplies a
#          per-band reference (A2-FCNET); absent that, the band runs its
#          full 20-iteration horizon (the golden notebook's interim).
#
# Exit   : 0  terminal — stop rule satisfied, or horizon exhausted with
#              every slot committed;
#          1  terminal with defects — horizon exhausted with failed slots,
#              or the no-progress brake (GOLD_MAX_NO_PROGRESS_CYCLES);
#          2  persisted-state refusal (gap / tamper — operator inspects);
#          3  chain infrastructure abort;  99 operator stop;  >=128 signal.
#
# --dry-run prints the frozen table and the fully-resolved run_chain argv
# for this band, launches nothing, writes nothing.
# ---------------------------------------------------------------------------

set -e
set -o pipefail

GOLD_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_gold_campaign_lib.sh
source "${GOLD_SCRIPT_DIR}/_gold_campaign_lib.sh"

# --- helpers ----------------------------------------------------------------

# Minimal python resolution for the STATE HELPER only (run_chain.sh resolves
# its own interpreter + source-tree authority for the chain itself).
# Precedence mirrors run_chain.sh: activated venv > project .venv > python3.
gold_resolve_python() {
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        GOLD_PY=("$VIRTUAL_ENV/bin/python")
    elif [ -x "${GOLD_PROJECT_DIR}/.venv/bin/python" ]; then
        GOLD_PY=("${GOLD_PROJECT_DIR}/.venv/bin/python")
    elif command -v python3 >/dev/null 2>&1; then
        GOLD_PY=(python3)
        echo "[gold-band] WARNING: no venv found — state helper uses system python3" >&2
    else
        echo "ERROR: no python interpreter for the state helper" >&2
        return 1
    fi
}

# Extract one TOP-LEVEL scalar field from the status JSON. Same head-1
# convention as _chain_common's _manifest_status: the helper writes the
# shell-read scalars FIRST (before any nested object), so the first match
# is the top-level one.
gold_status_field() {  # file key -> raw scalar (quotes stripped)
    grep -o "\"$2\"[[:space:]]*:[[:space:]]*\(\"[^\"]*\"\|[A-Za-z0-9_.+-]\+\)" "$1" 2>/dev/null \
        | head -1 \
        | sed -e 's/^"[^"]*"[[:space:]]*:[[:space:]]*//' -e 's/^"\(.*\)"$/\1/'
}

stage1_band_main() {
    local BAND="" WORKSPACE_ROOT="" ARM="goldpod" ADVICE_FILE=""
    local FCNET_REFERENCE_JSON="" DRY_RUN=0
    # F-PROFILE-WIRE-1 — command-line only; never inherited from the shell.
    GOLD_REQUIRED_RUNTIME_PROFILE_PATH=""
    GOLD_REQUIRED_RUNTIME_PROFILE=""
    GOLD_REQUIRED_RUNTIME_PROFILE_SHA256=""
    local PASSTHROUGH=()

    while [[ $# -gt 0 ]]; do
        case $1 in
            --band)                 BAND="$2"; shift 2 ;;
            --workspace_root|--workspace-root) WORKSPACE_ROOT="$2"; shift 2 ;;
            --arm)                  ARM="$2"; shift 2 ;;
            --gold_advice_file)     ADVICE_FILE="$2"; shift 2 ;;
            --gold_required_runtime_profile_path) GOLD_REQUIRED_RUNTIME_PROFILE_PATH="$2"; shift 2 ;;
            --gold_required_runtime_profile) GOLD_REQUIRED_RUNTIME_PROFILE="$2"; shift 2 ;;
            --gold_required_runtime_profile_sha256) GOLD_REQUIRED_RUNTIME_PROFILE_SHA256="$2"; shift 2 ;;
            --fcnet_reference_json) FCNET_REFERENCE_JSON="$2"; shift 2 ;;
            --dry-run|--dry_run)    DRY_RUN=1; shift ;;
            *)                      PASSTHROUGH+=("$1"); shift ;;
        esac
    done

    gold_refuse_reserved_passthrough ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} || return 1
    if [ -z "$BAND" ]; then
        echo "Required: --band 0-3|4-9|10-14|15-19" >&2
        return 1
    fi
    local GPU
    GPU="$(gold_band_gpu "$BAND")" || return 1
    gold_workspace_root_check "$WORKSPACE_ROOT" || return 1
    gold_arm_args "$ARM" "$ADVICE_FILE" || return 1
    # F-GENLIB-WIRE-1: enforced in EVERY stage, not only the entrypoint —
    # a stage script invoked directly must refuse the same undeclared
    # library root, and this is what makes GOLD_GENERATED_LIBRARY_DIR
    # populated for the dry-run row in this process.
    gold_require_generated_library || return 1
    gold_band_args "$BAND" || return 1
    gold_frozen_chain_args stage1 || return 1
    if [ -n "$FCNET_REFERENCE_JSON" ] && [ ! -f "$FCNET_REFERENCE_JSON" ]; then
        echo "ERROR: --fcnet_reference_json not found: $FCNET_REFERENCE_JSON" >&2
        return 1
    fi

    local WORKSPACE="${WORKSPACE_ROOT%/}/${ARM}_band${BAND}"
    local RUN_NAME="${ARM}_band${BAND}"
    local GOLD_HORIZON
    GOLD_HORIZON="$(gold_frozen_value num_iterations)" || return 1

    # GPU identity (frozen single-resident map). The fan-out parent exports
    # the mapped index; a direct invocation gets it here. A CONFLICTING
    # ambient value is refused — under this map the index is physical.
    if [ -z "${CUDA_VISIBLE_DEVICES:-}" ]; then
        export CUDA_VISIBLE_DEVICES="$GPU"
    elif [ "${CUDA_VISIBLE_DEVICES}" != "$GPU" ]; then
        echo "ERROR: CUDA_VISIBLE_DEVICES='${CUDA_VISIBLE_DEVICES}' conflicts with the frozen" >&2
        echo "  band->GPU map (band $BAND -> $GPU, single_resident). Unset it and relaunch." >&2
        return 1
    fi

    # E1 pin: the helper must import THIS checkout's framework code even
    # under a shared venv whose editable install points elsewhere.
    export PYTHONPATH="${GOLD_PROJECT_DIR}${PYTHONPATH:+:$PYTHONPATH}"

    # The fully-resolved chain invocation — the effective-resolution witness
    # surface. Every frozen value is typed here; nothing is left to a
    # default (_chain_common's defaults are documented as NOT campaign
    # values — decisions F-LAUNCH-1).
    local CHAIN_CMD=(
        bash "${GOLD_SCRIPT_DIR}/run_chain.sh"
        --mode lilab
        --workspace "$WORKSPACE"
        --run_name "$RUN_NAME"
        "${GOLD_FROZEN_CHAIN_ARGS[@]}"
        "${GOLD_BAND_ARGS[@]}"
        "${GOLD_ARM_ARGS[@]}"
    )
    CHAIN_CMD+=(${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"})

    if [ "$DRY_RUN" -eq 1 ]; then
        gold_print_frozen_table
        echo "[gold-band] band=$BAND gpu=$GPU arm=$ARM workspace=$WORKSPACE run_name=$RUN_NAME horizon=$GOLD_HORIZON"
        if [ -n "$FCNET_REFERENCE_JSON" ]; then
            echo "[gold-band] fcnet stop: reference=$FCNET_REFERENCE_JSON margin=$GOLD_FCNET_STOP_MARGIN"
        else
            echo "[gold-band] fcnet stop: NOT EVALUABLE (no per-band reference — A2-FCNET); full horizon runs"
        fi
        echo "[gold-band] band $BAND run_chain argv:"
        printf '%q ' "CUDA_VISIBLE_DEVICES=$GPU" "${CHAIN_CMD[@]}"
        echo ""
        echo "[gold-band] DRY-RUN COMPLETE — nothing launched, nothing written"
        return 0
    fi

    gold_resolve_python || return 1
    local STATE_HELPER="${GOLD_SCRIPT_DIR}/gold_campaign_state.py"
    # Sibling of the chain workspace, NOT inside it (see header note).
    local STATUS_JSON="${WORKSPACE}.gold_status.json"

    run_scan() {
        local args=(band-state --workspace "$WORKSPACE" --horizon "$GOLD_HORIZON"
                    --band "$BAND" --out "$STATUS_JSON")
        if [ -n "$FCNET_REFERENCE_JSON" ]; then
            args+=(--fcnet-reference-json "$FCNET_REFERENCE_JSON" --stop-margin "$GOLD_FCNET_STOP_MARGIN")
        fi
        "${GOLD_PY[@]}" "$STATE_HELPER" "${args[@]}"
    }

    local CHAIN_PID="" WATCHER_PID=""
    gold_watcher() {
        local last=""
        while :; do
            sleep "$GOLD_WATCH_INTERVAL_SECONDS"
            kill -0 "$CHAIN_PID" 2>/dev/null || break
            local count
            count="$(find "$WORKSPACE" -maxdepth 2 -name manifest.json 2>/dev/null | wc -l)"
            [ "$count" = "$last" ] && continue
            last="$count"
            # Mid-flight scans are advisory: a transient read failure is
            # retried at the next poll, never fatal to the running chain.
            run_scan || continue
            if [ "$(gold_status_field "$STATUS_JSON" stop_rule_satisfied)" = "true" ]; then
                if [ ! -e "${WORKSPACE}/STOP" ]; then
                    printf '%s %s band=%s\n' "$GOLD_STOP_MARKER" \
                        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$BAND" > "${WORKSPACE}/STOP"
                    echo "[gold-band] FCNet+2 stop rule satisfied — STOP requested (chain finishes the current iteration)"
                fi
                break
            fi
        done
    }

    # The chain workspace is created by run_chain itself; creating (or
    # writing into) it here would trip the stale-fresh guard's
    # non-empty-at-iter-1 refusal.
    local no_progress=0 cycle=0
    while :; do
        cycle=$((cycle + 1))
        # Persisted-state scan (loop-top scans are authoritative: a gap or
        # tampered iteration refuses here, before anything is launched).
        if ! run_scan; then
            echo "[gold-band] persisted-state scan REFUSED for $WORKSPACE (see error above)" >&2
            return 2
        fi

        local terminal terminal_reason terminal_ok
        terminal="$(gold_status_field "$STATUS_JSON" terminal)"
        terminal_reason="$(gold_status_field "$STATUS_JSON" terminal_reason)"
        terminal_ok="$(gold_status_field "$STATUS_JSON" terminal_ok)"
        if [ "$terminal" = "true" ]; then
            echo "[gold-band] band $BAND TERMINAL: ${terminal_reason} (status: $STATUS_JSON)"
            [ "$terminal_ok" = "true" ] && return 0 || return 1
        fi

        local committed_before force_args=()
        committed_before="$(gold_status_field "$STATUS_JSON" committed_count)"
        if [ "$(gold_status_field "$STATUS_JSON" needs_force_fresh)" = "true" ]; then
            # The NAMED iter-1-retry case: iter_001 exists non-completed with
            # nothing committed, so the chain's stale-fresh guard would
            # refuse START_ITER=1 in this band's own workspace. The scan
            # verified the workspace identity; the #258 replacement path
            # (auto-resume) still governs the actual manifest replacement.
            force_args=(--force_fresh)
            echo "[gold-band] iter-1 retry in own workspace — passing --force_fresh (replacement stays #258-governed)"
        fi

        echo "[gold-band] cycle $cycle: invoking chain (committed=$committed_before horizon=$GOLD_HORIZON)"
        local rc=0
        "${CHAIN_CMD[@]}" ${force_args[@]+"${force_args[@]}"} &
        CHAIN_PID=$!
        trap 'kill -TERM "$CHAIN_PID" 2>/dev/null' TERM INT HUP
        gold_watcher &
        WATCHER_PID=$!
        wait "$CHAIN_PID" || rc=$?
        # If our relay trap interrupted the wait, the chain is still doing
        # its own graceful stop — wait again for its REAL exit status.
        while kill -0 "$CHAIN_PID" 2>/dev/null; do
            rc=0
            wait "$CHAIN_PID" || rc=$?
        done
        trap - TERM INT HUP
        kill "$WATCHER_PID" 2>/dev/null || true
        wait "$WATCHER_PID" 2>/dev/null || true

        # Final scan of the cycle (best effort — rc dispatch happens either way).
        run_scan || true

        if [ "$rc" -eq 99 ]; then
            if [ -e "${WORKSPACE}/STOP" ] && grep -q "$GOLD_STOP_MARKER" "${WORKSPACE}/STOP" 2>/dev/null; then
                rm -f "${WORKSPACE}/STOP"
                echo "[gold-band] band $BAND TERMINAL: stop_rule_satisfied (graceful, current iteration completed)"
                return 0
            fi
            echo "[gold-band] band $BAND stopped by OPERATOR (STOP file/signal not ours) — not resuming" >&2
            return 99
        fi
        if [ "$rc" -eq 3 ] || [ "$rc" -ge 128 ]; then
            echo "[gold-band] band $BAND chain ended with rc=$rc (infrastructure abort / signal) — not resuming" >&2
            return "$rc"
        fi
        # rc 0 or 1: loop back — the loop-top scan decides terminal vs
        # another cycle. Progress = at least one NEW committed iteration.
        local committed_after
        committed_after="$(gold_status_field "$STATUS_JSON" committed_count)"
        if [ -n "$committed_after" ] && [ -n "$committed_before" ] \
            && [ "$committed_after" -gt "$committed_before" ] 2>/dev/null; then
            no_progress=0
        else
            no_progress=$((no_progress + 1))
            echo "[gold-band] cycle $cycle made no committed progress (streak $no_progress/$GOLD_MAX_NO_PROGRESS_CYCLES)" >&2
            if [ "$no_progress" -ge "$GOLD_MAX_NO_PROGRESS_CYCLES" ]; then
                echo "[gold-band] band $BAND: no-progress brake — operator review required (status: $STATUS_JSON)" >&2
                return 1
            fi
        fi
    done
}

# Source-safe entry guard (house convention; see
# tests/unit/sdsc_submission_scripts/test_source_safe_entry.py rationale).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    stage1_band_main "$@"
    exit $?
fi
