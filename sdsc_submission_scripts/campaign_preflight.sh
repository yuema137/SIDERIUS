#!/bin/bash
# SIDERIUS X9 campaign preflight.
#
# This launch-blocking gate serves the with-prior-art and without-prior-art
# comparison arms. Each R1-R9 row prints PASS, FAIL, SKIP, or INFO with its
# evidence; any FAIL produces a non-zero exit. Task-specific campaign gates
# belong to the experiment repository.

set -euo pipefail

PF_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PF_PROJECT_DIR="$(cd "${PF_SCRIPT_DIR}/.." && pwd)"
PF_LAUNCHER="${PF_SCRIPT_DIR}/launch_prior_baseline_experiment.sh"
PF_POSTURE="${PF_SCRIPT_DIR}/h100_posture.env"
PF_SYMMETRY="${PF_SCRIPT_DIR}/campaign_arm_symmetry.py"
PF_SURFACE="${PF_SCRIPT_DIR}/campaign_arm_surface.py"
PF_SMOKE="${PF_SCRIPT_DIR}/campaign_llm_smoke.py"
PF_PROBE="${PF_SCRIPT_DIR}/gpu_c_coresidency_probe.sh"

PF_BANDS=("0-3" "4-9" "10-14" "15-19")
# Expected DS8 pairing per band. AUTHORITY: the band launcher's own map —
# this table is the preflight's cross-check; drift fails R6 loudly.
pf_band_files() {
    case "$1" in
        0-3)   echo "0,1,2,3" ;;
        4-9)   echo "4,5,6,7,8,9" ;;
        10-14) echo "10,11,12,13,14" ;;
        15-19) echo "15,16,17,18,19" ;;
        *)     return 1 ;;
    esac
}

# --- pure, unit-testable check arithmetic ----------------------------------

# chains x per_chain + min_headroom must fit card_total (integer GiB/GB).
# Prints the arithmetic; returns 1 when it does not fit.
preflight_admission_arithmetic() {
    local chains=$1 per_chain=$2 card_total=$3 min_headroom=$4
    local sum=$((chains * per_chain))
    local headroom=$((card_total - sum))
    echo "sum=${sum} card_total=${card_total} headroom=${headroom} required_headroom=${min_headroom}"
    [ $((sum + min_headroom)) -le "$card_total" ]
}

# MemAvailable (GiB) must cover expected 4-chain anon-RSS + headroom.
preflight_host_ram_check() {
    local memavailable_gib=$1 expected_gib=$2 headroom_gib=$3
    local required=$((expected_gib + headroom_gib))
    echo "memavailable=${memavailable_gib} required=${required} (expected=${expected_gib}+headroom=${headroom_gib})"
    [ "$memavailable_gib" -ge "$required" ]
}

# Resolve the per-band X9 workspace inspected by the cold-start check.
# The launcher and preflight share this single path construction.
preflight_band_workspace() {
    local root="$1" arm="$2" band="$3"
    printf '%s\n' "${root%/}/${arm}_band${band}"
}

# The arm's baseline_isolation, READ from that arm's own resolved-config
# print (F-SCANG-4). The launcher derives the flag from --arm; this script
# must not carry a second arm->isolation table, because the surface capture
# would then render the treatment this script believes in rather than the
# one the run will apply. Prints "true"/"false"; returns 1 when the capture
# carries no such field, so a silently-absent value cannot become "false".
preflight_resolved_isolation() {
    local capture="$1" value
    value="$(grep -o '"baseline_isolation"[[:space:]]*:[[:space:]]*\(true\|false\)' "$capture" \
        | head -1 | grep -o 'true\|false' || true)"
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
}
pf_resolved_isolation() {
    local value
    if ! value="$(preflight_resolved_isolation "$1")"; then
        echo "ERROR: no baseline_isolation in the resolved-config capture: $1" >&2
        return 1
    fi
    printf '%s\n' "$value"
}

# Which of the two resolved isolation values belongs to ARM. A named
# function rather than an inline `[ ... ] && echo A || echo B`: this file
# already records what a trailing AND-list cost this campaign (see the R6
# loop note), and the arm->value selection is exactly the kind of thing a
# test should be able to call.
preflight_isolation_for_arm() {
    local arm="$1" with_iso="$2" without_iso="$3"
    case "$arm" in
        with-prior-art)    printf '%s\n' "$with_iso" ;;
        without-prior-art) printf '%s\n' "$without_iso" ;;
        *) echo "ERROR: preflight_isolation_for_arm: unknown arm '$arm'" >&2; return 1 ;;
    esac
}
pf_isolation_for_arm() { preflight_isolation_for_arm "$@"; }

# The R7 evidence caveat for a DERIVED sibling-surface evidence state (N-6).
#
# WHY THIS IS A FUNCTION, and why it answers for EVERY state. The disclaimer
# used to be gated on `[ "$PROVENANCE" = "local" ]`, so it DISAPPEARED at
# exactly the moment the label got stronger — and the label got stronger on
# `[ -f "$PUBLISHED_OTHER" ]`, file existence alone, with nothing in the
# artifact for anyone to verify. The rule is now the opposite: every state
# prints a note, the unverified states print a LOUDER one than the verified
# state, and an unknown state RETURNS 1 rather than printing nothing —
# silence is the failure mode this whole row exists to remove.
#
# Args: STATE SOURCE OTHER_ARM PUBLISHED_PATH.
preflight_surface_evidence_note() {
    local state="$1" source="$2" other_arm="$3" published="$4"
    local from_here=""
    [ "$source" = "published" ] && from_here=" The file read from ${published} was written by THIS host."
    case "$state" in
        cross_pod_verified)
            printf '%s\n' "R7 sibling surface VERIFIED cross-pod: the ${other_arm} surface records a DIFFERENT host, the SAME code revision as this checkout, and a capture inside the freshness window. The environment, machine-local-store and neutral-prompt layers were genuinely compared across two pods (source=${source})" ;;
        cross_pod_stale)
            printf '%s\n' "R7 CAVEAT — sibling surface is STALE: the ${other_arm} surface was written by another host but is older than the freshness threshold, so nothing has re-measured that pod since. A stale surface survives every cold start: R8 globs the per-band workspaces and never ${published}. Re-run this preflight on the ${other_arm} pod and then re-run here before launching (source=${source})" ;;
        same_host)
            printf '%s\n' "R7 CAVEAT — NOT cross-pod evidence: both surfaces were captured on THIS host.${from_here} capture_environment() and resolve_stores() take no arm argument, so the environment, the machine-local stores and the neutral prompt render agree BY CONSTRUCTION and are reported NOT COMPARED, not as agreeing. This comparison cannot speak for a second pod. Run this preflight on the ${other_arm} pod to publish its surface, then re-run here (source=${source})" ;;
        revision_mismatch)
            printf '%s\n' "R7 CAVEAT — the two surfaces were rendered by DIFFERENT code revisions, so their prompt bytes compare two renderers rather than two machines; R2 requires one SHA per campaign. R7 FAILS on this (source=${source})" ;;
        unverifiable)
            printf '%s\n' "R7 CAVEAT — UNATTRIBUTABLE surface: at least one surface carries no readable host, captured-at or revision, so nothing about its origin can be checked and no cross-pod claim is available from it (source=${source})" ;;
        *)
            echo "ERROR: preflight_surface_evidence_note: unknown evidence state '$state'" >&2
            return 1 ;;
    esac
}

# The evidence state the CHECKER derived, read back from its own report.
# Read, never re-derived: a second opinion formed in bash would be free to
# drift from the one the checker printed, and the whole finding is a label
# that was not the comparison's own conclusion. Returns 1 when the line is
# absent, so a checker that stopped emitting it cannot become "unstated".
preflight_evidence_state() {
    local report="$1" value
    # `|| true` for the same reason pf_resolved_isolation carries it: under
    # `set -euo pipefail` a grep that matches nothing fails the pipeline, and
    # a failed command substitution in an assignment ABORTS. The refusal must
    # come from the explicit emptiness test below — a function whose contract
    # depends on where `set -e` happens to be suppressed is one whose refusal
    # nobody can test.
    value="$(grep -o '^\[arm-symmetry\] evidence-state: .*$' "$report" 2>/dev/null \
        | tail -1 | sed 's/^.*evidence-state: //' | tr -d '[:space:]' || true)"
    [ -n "$value" ] || return 1
    printf '%s\n' "$value"
}

# Capture ONE arm's surface (rendered prompt bytes / environment /
# machine-local stores) through the production renderers. PYTHONPATH-pinned
# to this checkout for the same reason R2b exists: a surface rendered by
# another clone's templates describes prompts this launch will not send.
pf_capture_surface() {
    local arm="$1" isolation="$2" out="$3"
    (cd "$PF_PROJECT_DIR" && PYTHONPATH="${PF_PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
        "$PF_PY" "$PF_SURFACE" --arm "$arm" --baseline-isolation "$isolation" \
        --project-dir "$PF_PROJECT_DIR" --out "$out")
}

# --- row bookkeeping --------------------------------------------------------

PF_FAILS=0
PF_ROWS=()
pf_pass() { PF_ROWS+=("PASS  $1"); echo "[preflight] PASS  $1"; }
pf_fail() { PF_ROWS+=("FAIL  $1"); echo "[preflight] FAIL  $1" >&2; PF_FAILS=$((PF_FAILS + 1)); }
pf_info() { PF_ROWS+=("INFO  $1"); echo "[preflight] INFO  $1"; }
# A row that does NOT APPLY to the arm under check. Deliberately its own
# verdict rather than a PASS: a row skipped because the topology cannot
# exercise it has proven nothing, and printing PASS would be the same lie
# the X9-surrogate workspace told. Does not count as a failure either — an
# inapplicable check must not block a launch it says nothing about.
pf_skip() { PF_ROWS+=("SKIP  $1"); echo "[preflight] SKIP  $1"; }

pf_resolve_python() {
    if [ -n "${SIDERIUS_PYTHON:-}" ]; then
        PF_PY="$SIDERIUS_PYTHON"
    elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        PF_PY="$VIRTUAL_ENV/bin/python"
    elif [ -x "${PF_PROJECT_DIR}/.venv/bin/python" ]; then
        PF_PY="${PF_PROJECT_DIR}/.venv/bin/python"
    else
        echo "ERROR: no project python (SIDERIUS_PYTHON / \$VIRTUAL_ENV / ${PF_PROJECT_DIR}/.venv)." >&2
        return 1
    fi
}

pf_main() {
    local WORKSPACE_ROOT="" ARM="" REVISION="" DATA_DIR="" LLM_CONFIG=""
    local SKIP_LLM=0 SYMMETRY_BAND="0-3"
    local PASSTHROUGH=()

    while [[ $# -gt 0 ]]; do
        case $1 in
            --workspace-root|--workspace_root) WORKSPACE_ROOT="$2"; shift 2 ;;
            --arm)            ARM="$2"; shift 2 ;;
            --revision)       REVISION="$2"; shift 2 ;;
            --data_dir|--data-dir) DATA_DIR="$2"; shift 2 ;;
            --llm_config|--llm-config) LLM_CONFIG="$2"; shift 2 ;;
            --skip_llm_smoke|--skip-llm-smoke) SKIP_LLM=1; shift ;;
            --symmetry-band|--symmetry_band) SYMMETRY_BAND="$2"; shift 2 ;;
            # Print the whole header block: from line 2 until the first
            # line that is not a comment. A hardcoded end line silently
            # truncates help the moment a row's documentation grows.
            -h|--help) sed -n '2,${/^#/!q;p;}' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
            --) shift; PASSTHROUGH=("$@"); break ;;
            *)
                echo "ERROR: unknown argument $1 (chain flags go after --)" >&2
                return 1 ;;
        esac
    done

    if [ -z "$WORKSPACE_ROOT" ] || [ -z "$ARM" ] || [ -z "$REVISION" ]; then
        echo "Required: --workspace-root DIR --arm ARM --revision SHA (see --help)" >&2
        return 1
    fi
    case "$ARM" in
        with-prior-art|without-prior-art) ;;
        *)
            echo "ERROR: unknown --arm '$ARM' (accepted: with-prior-art, without-prior-art)" >&2
            return 1 ;;
    esac
    # The X9 symmetry partner.
    local OTHER_ARM=""
    if [ "$ARM" = "with-prior-art" ]; then
        OTHER_ARM="without-prior-art"
    elif [ "$ARM" = "without-prior-art" ]; then
        OTHER_ARM="with-prior-art"
    fi

    local HAVE_HG=0 HAVE_RA=0 tok
    for tok in ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}; do
        [ "$tok" = "--healthgate_mode" ] && HAVE_HG=1
        [ "$tok" = "--result_authority" ] && HAVE_RA=1
    done
    if [ "$HAVE_HG" -eq 0 ] || [ "$HAVE_RA" -eq 0 ]; then
        echo "ERROR: pass the launch's own '-- --healthgate_mode ... --result_authority ...'" >&2
        echo "  (run_one_iteration.py refuses a formal launch without both, so the dry-runs" >&2
        echo "   in R6/R7 need them to resolve the configuration you will actually launch)." >&2
        return 1
    fi

    pf_resolve_python
    local SCRATCH
    SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/campaign_preflight.XXXXXX")"

    echo "[preflight] arm=$ARM workspace_root=$WORKSPACE_ROOT symmetry_band=$SYMMETRY_BAND"

    # ---- R1: workspace root persistence -----------------------------------
    if [ ! -d "$WORKSPACE_ROOT" ]; then
        pf_fail "R1 workspace root does not exist: $WORKSPACE_ROOT"
    elif ! touch "${WORKSPACE_ROOT}/.preflight_write_probe" 2>/dev/null; then
        pf_fail "R1 workspace root not writable: $WORKSPACE_ROOT"
    else
        rm -f "${WORKSPACE_ROOT}/.preflight_write_probe"
        local FSTYPE=""
        if command -v findmnt >/dev/null 2>&1; then
            FSTYPE="$(findmnt -n -o FSTYPE --target "$WORKSPACE_ROOT" 2>/dev/null || true)"
        fi
        [ -z "$FSTYPE" ] && FSTYPE="$(df -PT "$WORKSPACE_ROOT" 2>/dev/null | awk 'NR==2 {print $2}')"
        local MOUNT_SRC
        MOUNT_SRC="$(df -P "$WORKSPACE_ROOT" 2>/dev/null | awk 'NR==2 {print $1 " on " $6}')"
        case "$FSTYPE" in
            tmpfs|ramfs|overlay)
                pf_fail "R1 workspace root is on EPHEMERAL '$FSTYPE' ($MOUNT_SRC) — pod loss destroys campaign records; mount persistent storage" ;;
            "")
                pf_fail "R1 could not determine the filesystem type of $WORKSPACE_ROOT" ;;
            *)
                pf_pass "R1 workspace root writable on persistent '$FSTYPE' ($MOUNT_SRC)" ;;
        esac
    fi

    # ---- R1b: calibration store persistence (H100-prep finding) ------------
    # R1's fstype logic applied to the per-device calibration directory —
    # the resolution mirrors calibration_dir() in
    # agent/skills/evaluate_time_skill/calibration.py ($SIDERIUS_CALIBRATION_DIR
    # override, else ~/.siderius). The dir may not exist yet on a fresh box,
    # so the probe walks to the nearest existing ancestor: what persists (or
    # doesn't) is the MOUNT, not the leaf.
    local CAL_DIR="${SIDERIUS_CALIBRATION_DIR:-$HOME/.siderius}"
    local CAL_PROBE="$CAL_DIR"
    while [ ! -e "$CAL_PROBE" ] && [ "$CAL_PROBE" != "/" ]; do
        CAL_PROBE="$(dirname "$CAL_PROBE")"
    done
    local CAL_FSTYPE=""
    if command -v findmnt >/dev/null 2>&1; then
        CAL_FSTYPE="$(findmnt -n -o FSTYPE --target "$CAL_PROBE" 2>/dev/null || true)"
    fi
    [ -z "$CAL_FSTYPE" ] && CAL_FSTYPE="$(df -PT "$CAL_PROBE" 2>/dev/null | awk 'NR==2 {print $2}')"
    local CAL_MOUNT_SRC
    CAL_MOUNT_SRC="$(df -P "$CAL_PROBE" 2>/dev/null | awk 'NR==2 {print $1 " on " $6}')"
    case "$CAL_FSTYPE" in
        tmpfs|ramfs|overlay)
            pf_fail "R1b calibration store $CAL_DIR is on EPHEMERAL '$CAL_FSTYPE' ($CAL_MOUNT_SRC) — pod loss destroys the time-calibration k-tables and the measured runtime-profile overlay (#311); export SIDERIUS_CALIBRATION_DIR to a persistent mount" ;;
        "")
            pf_fail "R1b could not determine the filesystem type of $CAL_DIR (probe: $CAL_PROBE)" ;;
        *)
            pf_pass "R1b calibration store $CAL_DIR on persistent '$CAL_FSTYPE' ($CAL_MOUNT_SRC)" ;;
    esac

    # ---- R1c: generated-capability library root (F-GENLIB-WIRE-1) ----------
    # Resolution is DELEGATED to the production authority, never re-derived:
    # `resolve_generated_library` owns the two layers, the "~" expansion and
    # the relative-path refusal, and a bash re-implementation would be a
    # second authority free to drift from the one the run obeys. One call,
    # tab-separated "<source>\t<root>"; a non-zero exit means the authority
    # itself REFUSED the value (a relative override), which is a FAIL here
    # rather than a silent fallback.
    local GENLIB_RAW GENLIB_SOURCE GENLIB_ROOT
    if GENLIB_RAW="$(cd "$PF_PROJECT_DIR" && PYTHONPATH="${PF_PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
        "$PF_PY" -c 'from core.generated_library import resolve_generated_library as r; x = r(); print(x.source + "\t" + x.root)' \
        2>/dev/null | tail -1)" && [ -n "$GENLIB_RAW" ]; then
        GENLIB_SOURCE="${GENLIB_RAW%%$'\t'*}"
        GENLIB_ROOT="${GENLIB_RAW#*$'\t'}"
        if [ "$GENLIB_SOURCE" != "env" ]; then
            pf_fail "R1c generated-capability library resolves to the DEFAULT root $GENLIB_ROOT — \$SIDERIUS_GENERATED_LIBRARY_DIR was not exported. On a pod that path is the ephemeral container overlay, and it is shared across campaigns: promoted models and losses from an earlier run become visible to this one's proposer. Export it to an absolute, persistent, campaign-owned, FRESH directory before launching"
        else
            local GENLIB_PROBE="$GENLIB_ROOT"
            while [ ! -e "$GENLIB_PROBE" ] && [ "$GENLIB_PROBE" != "/" ]; do
                GENLIB_PROBE="$(dirname "$GENLIB_PROBE")"
            done
            local GENLIB_FSTYPE=""
            if command -v findmnt >/dev/null 2>&1; then
                GENLIB_FSTYPE="$(findmnt -n -o FSTYPE --target "$GENLIB_PROBE" 2>/dev/null || true)"
        fi
            [ -z "$GENLIB_FSTYPE" ] && GENLIB_FSTYPE="$(df -PT "$GENLIB_PROBE" 2>/dev/null | awk 'NR==2 {print $2}')"
            local GENLIB_MOUNT_SRC
            GENLIB_MOUNT_SRC="$(df -P "$GENLIB_PROBE" 2>/dev/null | awk 'NR==2 {print $1 " on " $6}')"
            case "$GENLIB_FSTYPE" in
                tmpfs|ramfs|overlay)
                    pf_fail "R1c generated-capability library $GENLIB_ROOT is on EPHEMERAL '$GENLIB_FSTYPE' ($GENLIB_MOUNT_SRC) — pod loss destroys every promoted capability and its index; export \$SIDERIUS_GENERATED_LIBRARY_DIR to a persistent mount" ;;
                "")
                    pf_fail "R1c could not determine the filesystem type of $GENLIB_ROOT (probe: $GENLIB_PROBE)" ;;
                *)
                    pf_pass "R1c generated-capability library $GENLIB_ROOT (source=env) on persistent '$GENLIB_FSTYPE' ($GENLIB_MOUNT_SRC)" ;;
            esac
        fi
    else
        pf_fail "R1c generated-capability library root could not be resolved — \$SIDERIUS_GENERATED_LIBRARY_DIR is set to a value core.generated_library REFUSES (a relative path resolves against the launch cwd and would write generated artifacts back into the checkout). Export an absolute path"
    fi

    # ---- R2: authoritative revision ----------------------------------------
    local REPO_SHA DIRTY
    REPO_SHA="$(git -C "$PF_PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    DIRTY="$(git -C "$PF_PROJECT_DIR" status --porcelain 2>/dev/null || true)"
    echo "[preflight] repo_sha=${REPO_SHA}"
    if [ "$REPO_SHA" = "unknown" ]; then
        pf_fail "R2 not a git checkout: $PF_PROJECT_DIR"
    elif [ "${#REVISION}" -lt 7 ]; then
        pf_fail "R2 --revision '$REVISION' too short (>= 7 hex chars)"
    elif [[ "$REPO_SHA" != "$REVISION"* ]]; then
        pf_fail "R2 revision mismatch: HEAD=$REPO_SHA expected=$REVISION*"
    elif [ -n "$DIRTY" ]; then
        pf_fail "R2 dirty tree — a campaign must be attributable to one SHA; commit first: $(echo "$DIRTY" | head -3 | tr '\n' ' ')"
    else
        pf_pass "R2 revision $REPO_SHA matches --revision and the tree is clean"
    fi

    # ---- R2b: import resolution (P0 launch blocker, supervisor 2026-08-25) --
    # The venv's editable install maps packages to the MAIN checkout; a child
    # whose cwd leaves this tree silently imports THAT tree's code (the E1
    # trap — concretely, a campaign without #299's divergence repair while
    # its git SHA says otherwise). The launchers export
    # PYTHONPATH=$PF_PROJECT_DIR; this row PROVES the pinned resolution from
    # a NEUTRAL cwd (a copied probe file — `-c` is blind, cwd sits on
    # sys.path) and REPORTS what an unpinned child would resolve.
    local PROBE_TMP
    PROBE_TMP="$(mktemp -d)"
    cp "${PF_SCRIPT_DIR}/_import_resolution_probe.py" "$PROBE_TMP/probe.py"
    local UNPINNED
    UNPINNED="$(cd "$PROBE_TMP" && env -u PYTHONPATH "$PF_PY" probe.py "$PF_PROJECT_DIR" 2>/dev/null | head -1 || true)"
    echo "[preflight] R2b unpinned child would resolve: ${UNPINNED#*-> }"
    if (cd "$PROBE_TMP" && PYTHONPATH="$PF_PROJECT_DIR" "$PF_PY" probe.py "$PF_PROJECT_DIR" >/dev/null 2>&1); then
        pf_pass "R2b pinned import resolution: hyperparam_tuning resolves in this tree with the #299-tolerant loss_history"
    else
        (cd "$PROBE_TMP" && PYTHONPATH="$PF_PROJECT_DIR" "$PF_PY" probe.py "$PF_PROJECT_DIR") 2>&1 | tail -3 >&2 || true
        pf_fail "R2b import resolution: the PINNED probe failed — chains would execute another tree's code (see [import-probe] lines)"
    fi
    rm -rf "$PROBE_TMP"

    # ---- R3: dataset availability ------------------------------------------
    if [ -z "$DATA_DIR" ]; then
        DATA_DIR="$(cd "$PF_PROJECT_DIR" && PYTHONPATH="${PF_PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
            "$PF_PY" -c 'from execute_tools.data_paths import TIDMAD_DATA_DIR; print(TIDMAD_DATA_DIR)' \
            2>/dev/null | tail -1 || true)"
    fi
    if [ -z "$DATA_DIR" ] || [ ! -d "$DATA_DIR" ]; then
        pf_fail "R3 dataset dir unresolved or missing (--data_dir / tidmad_data_config.yaml): '${DATA_DIR:-}'"
    else
        local MISSING=0 band f idx
        for band in "${PF_BANDS[@]}"; do
            local BAND_MISSING=()
            for idx in $(echo "$(pf_band_files "$band")" | tr ',' ' '); do
                for f in "abra_training_$(printf '%04d' "$idx").h5" "abra_validation_$(printf '%04d' "$idx").h5"; do
                    [ -f "${DATA_DIR}/${f}" ] || BAND_MISSING+=("$f")
                done
            done
            if [ "${#BAND_MISSING[@]}" -gt 0 ]; then
                pf_fail "R3 band $band missing under $DATA_DIR: ${BAND_MISSING[*]}"
                MISSING=1
        fi
        done
        [ "$MISSING" -eq 0 ] && pf_pass "R3 all 20 file indices (training+validation pairs) present under $DATA_DIR"
    fi

    # ---- R4: posture arithmetic + coresidency factor -----------------------
    # The posture file also owns the host-RAM expectation used by R5.
    if [ ! -f "$PF_POSTURE" ]; then
        pf_fail "R4 posture file missing: $PF_POSTURE"
    else
        # shellcheck disable=SC1090
        source "$PF_POSTURE"
        local ARITH
        if ARITH="$(preflight_admission_arithmetic \
                    "${H100_CORESIDENT_CHAINS:-4}" "${H100_PER_CHAIN_VRAM_GB:-18}" \
                    "${H100_CARD_TOTAL_VRAM_GB:-80}" "${H100_MIN_CARD_VRAM_HEADROOM_GB:-6}")"; then
                pf_pass "R4 admission arithmetic fits: $ARITH"
        else
                pf_fail "R4 admission arithmetic does NOT fit: $ARITH"
        fi
        if [ -n "${H100_CORESIDENCY_FACTOR:-}" ]; then
                pf_pass "R4 coresidency factor filled: H100_CORESIDENCY_FACTOR=${H100_CORESIDENCY_FACTOR} (posture v${H100_POSTURE_VERSION:-?})"
        else
                pf_fail "R4 H100_CORESIDENCY_FACTOR is EMPTY — the band launcher will refuse --h100 campaign launches; run: bash $PF_PROBE"
        fi
    fi

    # ---- R5: host-RAM headroom ---------------------------------------------
    local MEM_KIB MEM_GIB RAMCHK
    MEM_KIB="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
    MEM_GIB=$((MEM_KIB / 1024 / 1024))
    if RAMCHK="$(preflight_host_ram_check "$MEM_GIB" \
            "${H100_EXPECTED_QUAD_HOST_ANON_RSS_GB:-47}" "${H100_HOST_RAM_HEADROOM_GB:-16}")"; then
        pf_pass "R5 host RAM: $RAMCHK GiB"
    else
        pf_fail "R5 host RAM short of the 4-chain expectation: $RAMCHK GiB (recorded 4-chain inspection OOM at ~47 GB anon-RSS)"
    fi

    # ---- R6: arm+band identity coherence (dry-runs, this arm) --------------
    local band OUT RC EXPECT_FILES EXPECT_FILES_Q ARM_CAPTURE=""
         for band in "${PF_BANDS[@]}"; do
            OUT="${SCRATCH}/dryrun_${ARM}_band${band}.out"
            RC=0
            bash "$PF_LAUNCHER" --arm "$ARM" --band "$band" --workspace-root "$WORKSPACE_ROOT" \
                --dry-run ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} > "$OUT" 2>&1 || RC=$?
            EXPECT_FILES="$(pf_band_files "$band")"
            # run_chain's dry-run prints each token with `printf %q`, which
            # escapes commas ("0,1,2,3" -> "0\,1\,2\,3"); build the expectation
            # with the SAME printf so the grep matches what the printer emits.
            printf -v EXPECT_FILES_Q '%q' "$EXPECT_FILES"
            if [ "$RC" -ne 0 ]; then
                pf_fail "R6 band $band dry-run exited $RC (see $OUT)"
            elif ! grep -q "\"experiment_arm\": \"$ARM\"" "$OUT"; then
                pf_fail "R6 band $band resolved config lacks experiment_arm=$ARM (see $OUT)"
            elif ! grep -q "\"run_name\": \"${ARM}_band${band}\"" "$OUT"; then
                pf_fail "R6 band $band resolved config lacks derived run_name ${ARM}_band${band} (see $OUT)"
            elif ! grep -qF -- "--data_scope ${band} " "$OUT"; then
                pf_fail "R6 band $band child argv lacks '--data_scope ${band}' (see $OUT)"
            elif ! grep -qF -- "--health_gate_files ${EXPECT_FILES_Q} " "$OUT"; then
                pf_fail "R6 band $band child argv lacks DS8 pair '--health_gate_files ${EXPECT_FILES}' (see $OUT)"
        else
                pf_pass "R6 band $band identity coherent (arm, run_name, DS8 scope pair)"
        fi
            # Keep the capture assignment in an explicit conditional so a
            # non-matching final band cannot leak status 1 from an AND-list.
            if [ "$band" = "$SYMMETRY_BAND" ]; then
                ARM_CAPTURE="$OUT"
        fi
        done

    # ---- R7: arm symmetry — argv + surface (#255, F-SCANG-4) ---------------
        local OTHER_OUT="${SCRATCH}/dryrun_${OTHER_ARM}_band${SYMMETRY_BAND}.out"
        RC=0
        bash "$PF_LAUNCHER" --arm "$OTHER_ARM" --band "$SYMMETRY_BAND" --workspace-root "$WORKSPACE_ROOT" \
            --dry-run ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"} > "$OTHER_OUT" 2>&1 || RC=$?
        if [ "$RC" -ne 0 ] || [ -z "$ARM_CAPTURE" ]; then
            pf_fail "R7 could not capture both arms' dry-runs for the symmetry check (rc=$RC)"
        else
            local WITH_CAP="$ARM_CAPTURE" WITHOUT_CAP="$OTHER_OUT"
            if [ "$ARM" = "without-prior-art" ]; then
                WITH_CAP="$OTHER_OUT"; WITHOUT_CAP="$ARM_CAPTURE"
        fi
            # F-SCANG-4 layer 3. Each arm's isolation flag is READ from that
            # arm's own resolved-config print, never re-derived here: the
            # launcher decides it from --arm, and a second table in this
            # script would be free to drift from the one the run obeys.
            #
            # Every one of these resolutions is captured with `|| RC=$?`.
            # A bare `X=$(fn)` under `set -e` ABORTS pf_main when fn returns
            # non-zero, so an unparseable capture would kill the preflight
            # mid-summary instead of failing one row — every later row, R8
            # included, would silently never run.
            local SURF_RC=0 WITH_ISO="" WITHOUT_ISO="" SELF_ISO="" OTHER_ISO=""
            WITH_ISO="$(pf_resolved_isolation "$WITH_CAP")" || SURF_RC=$?
            WITHOUT_ISO="$(pf_resolved_isolation "$WITHOUT_CAP")" || SURF_RC=$?
            if [ "$SURF_RC" -eq 0 ]; then
                SELF_ISO="$(pf_isolation_for_arm "$ARM" "$WITH_ISO" "$WITHOUT_ISO")" || SURF_RC=$?
                OTHER_ISO="$(pf_isolation_for_arm "$OTHER_ARM" "$WITH_ISO" "$WITHOUT_ISO")" || SURF_RC=$?
        fi
            if [ "$SURF_RC" -eq 0 ]; then
                pf_capture_surface "$ARM" "$SELF_ISO" "${SCRATCH}/surface_${ARM}.json" || SURF_RC=$?
        fi
            # PUBLISH into the shared campaign root. This is what makes the
            # comparison CROSS-POD: the arm that preflights second reads the
            # first pod's recorded surface instead of a sibling re-derived
            # from its own machine, which would agree with itself by
            # construction — the row's "one machine" objection.
            local PUBLISHED_SELF="${WORKSPACE_ROOT%/}/.campaign_arm_surface_${ARM}.json"
            local PUBLISHED_OTHER="${WORKSPACE_ROOT%/}/.campaign_arm_surface_${OTHER_ARM}.json"
            # SIBLING_SOURCE records only WHERE the file was read — the one
            # fact this script cannot be wrong about. It is NOT a strength
            # label: `published` used to be asserted on this `[ -f ]` alone,
            # and the artifact carried no captured-at, host or revision for
            # anyone to check, so one same-host rehearsal (or a day-1
            # publication that no cold start removes) earned the strongest
            # claim the report can print. What the file is WORTH is derived
            # by campaign_arm_symmetry.py from the surfaces' own provenance.
            local OTHER_SURFACE="" SIBLING_SOURCE="local"
            if [ "$SURF_RC" -eq 0 ]; then
                cp "${SCRATCH}/surface_${ARM}.json" "$PUBLISHED_SELF" 2>/dev/null \
                    || pf_info "R7 could not publish this arm's surface to $PUBLISHED_SELF (the other pod will capture its own sibling locally)"
                if [ -f "$PUBLISHED_OTHER" ]; then
                    OTHER_SURFACE="$PUBLISHED_OTHER"
                    SIBLING_SOURCE="published"
                else
                    OTHER_SURFACE="${SCRATCH}/surface_${OTHER_ARM}.json"
                    SIBLING_SOURCE="local"
                    pf_capture_surface "$OTHER_ARM" "$OTHER_ISO" "$OTHER_SURFACE" || SURF_RC=$?
                fi
        fi
            # ONE verdict for the whole surface layer. Two pf_fail calls for
            # one broken capture would double the failure count and read as
            # two independent defects in the summary.
            if [ "$SURF_RC" -ne 0 ]; then
                pf_fail "R7 could not build the arm SURFACE layer (rendered prompt bytes / environment / machine-local stores) — see the [arm-surface] lines above; the argv layer alone cannot claim arm symmetry (F-SCANG-4)"
        else
                local WITH_SURF="${SCRATCH}/surface_${ARM}.json" WITHOUT_SURF="$OTHER_SURFACE"
                if [ "$ARM" = "without-prior-art" ]; then
                    WITH_SURF="$OTHER_SURFACE"; WITHOUT_SURF="${SCRATCH}/surface_${ARM}.json"
                fi
                # The report is TEED, not just streamed: the R7 row must
                # state the evidence state the CHECKER derived, and reading
                # it back is what keeps this script from forming a second
                # opinion about how strong its own evidence is.
                local SYM_REPORT="${SCRATCH}/arm_symmetry_report.txt" SYM_RC=0
                (cd "$PF_PROJECT_DIR" && PYTHONPATH="${PF_PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
                        "$PF_PY" "$PF_SYMMETRY" --with-output "$WITH_CAP" --without-output "$WITHOUT_CAP" \
                        --workspace-root "$WORKSPACE_ROOT" --band "$SYMMETRY_BAND" \
                        --with-surface "$WITH_SURF" --without-surface "$WITHOUT_SURF" \
                        --sibling-source "$SIBLING_SOURCE") > "$SYM_REPORT" 2>&1 || SYM_RC=$?
                cat "$SYM_REPORT"
                local EV_STATE
                EV_STATE="$(preflight_evidence_state "$SYM_REPORT")" || EV_STATE=""
                if [ "$SYM_RC" -eq 0 ]; then
                    # The row states WHICH layers were compared, and never
                    # claims agreement for a layer reported NOT COMPARED.
                    pf_pass "R7 arm symmetry holds for every COMPARED layer (#255 argv + F-SCANG-4 surface; sibling-source=$SIBLING_SOURCE evidence-state=${EV_STATE:-unreported}): arms differ only in declared policy + derived naming. Per-layer verdicts, including any NOT COMPARED layer, are in the checker report above"
                else
                    pf_fail "R7 arm symmetry VIOLATED (#255 / F-SCANG-4 — launch validity conditioned on this; see the field diff above)"
                fi
                # Printed in EVERY state, weak states louder than the
                # verified one. An unreported state is itself a caveat, not
                # a reason to print nothing.
                local EV_NOTE=""
                if [ -n "$EV_STATE" ] \
                    && EV_NOTE="$(preflight_surface_evidence_note "$EV_STATE" "$SIBLING_SOURCE" "$OTHER_ARM" "$PUBLISHED_OTHER")"; then
                    pf_info "$EV_NOTE"
                else
                    pf_info "R7 CAVEAT — the symmetry checker reported no evidence state this script recognises (got '${EV_STATE:-<none>}'), so the strength of the ${OTHER_ARM} surface is UNKNOWN: treat the environment and machine-local-store layers as NOT COMPARED"
                fi
        fi
        fi

    # ---- R8: cold-start preconditions (#260) -------------------------------
    for band in "${PF_BANDS[@]}"; do
        # The workspace of the arm ACTUALLY under check — never a surrogate.
        local WS
        WS="$(preflight_band_workspace "$WORKSPACE_ROOT" "$ARM" "$band")"
        if [ ! -d "$WS" ] || [ -z "$(ls -A "$WS" 2>/dev/null)" ]; then
            pf_pass "R8 item1 band $band workspace absent/empty ($WS)"
        else
            pf_fail "R8 item1 band $band workspace NOT empty ($WS) — a reused workspace resumes, it does not start cold"
        fi
    done
    local GEN_MODELS="${PF_PROJECT_DIR}/agent_generated/models"
    local GEN_INDEX="${PF_PROJECT_DIR}/agent_generated/_capability_index.json"
    local LEFTOVER
    LEFTOVER="$(find "$GEN_MODELS" -maxdepth 1 -name '*.py' 2>/dev/null | head -5 || true)"
    if [ -n "$LEFTOVER" ]; then
        pf_fail "R8 item3 leftover plugins in agent_generated/models (prior-campaign capability state): $(echo "$LEFTOVER" | tr '\n' ' ')"
    else
        pf_pass "R8 item3 agent_generated/models holds no leftover plugin .py"
    fi
    if [ -f "$GEN_INDEX" ]; then
        pf_fail "R8 item3 agent_generated/_capability_index.json exists — clear it for a cold capability surface"
    else
        pf_pass "R8 item3 no _capability_index.json"
    fi
    pf_info "R8 item4 workspace plugins/ covered by item1 (fresh workspace)"
    pf_info "R8 items2/7 seeds + advice files: enforced by launcher refusals in both arms"
    pf_info "R8 item5 root_papers_cache: RETAIN by design"
    pf_info "R8 item6 runtime calibration store: RETAIN by design — persistence of its mount is CHECKED by R1b, not assumed"

    # ---- R9: LLM reachability + concurrency smoke --------------------------
    if [ "$SKIP_LLM" -eq 1 ]; then
        pf_info "R9 LLM smoke SKIPPED (--skip_llm_smoke)"
    else
        local SMOKE_ARGS=(--out "${SCRATCH}/llm_smoke.json")
        [ -n "$LLM_CONFIG" ] && SMOKE_ARGS+=(--llm-config "$LLM_CONFIG")
        if (cd "$PF_PROJECT_DIR" && PYTHONPATH="${PF_PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
                "$PF_PY" "$PF_SMOKE" "${SMOKE_ARGS[@]}"); then
            pf_pass "R9 LLM burst reachable (8/8; p95 + per-call detail above; NOT a quota guarantee)"
        else
            pf_fail "R9 LLM burst failed (see per-call errors above; report ${SCRATCH}/llm_smoke.json)"
        fi
    fi

    # ---- summary -----------------------------------------------------------
    echo ""
    echo "############################################################"
    echo "  CAMPAIGN PREFLIGHT SUMMARY  (arm=$ARM)"
    echo "  repo_sha=${REPO_SHA}"
    local row
    for row in "${PF_ROWS[@]}"; do
        echo "  $row"
    done
    echo "  failures=${PF_FAILS}  evidence=${SCRATCH}"
    echo "############################################################"
    [ "$PF_FAILS" -eq 0 ]
}

# Source-safe entry guard (house convention): sourcing exposes the pure
# check functions for tests without running anything.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    pf_main "$@"
    exit $?
fi
