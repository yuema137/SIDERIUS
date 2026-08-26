#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS campaign preflight (arXiv launch topology, H100 band fleet)
# ---------------------------------------------------------------------------
# Role   : ONE launch-blocking gate for a band-fleet campaign launch. Every
#          row prints PASS/FAIL/INFO with its evidence; ANY FAIL exits
#          non-zero. Run it on the campaign host, per arm, before
#          launch_band_fleet.sh.
#
# Rows:
#   R1  workspace root exists / writable / on a PERSISTENT mount.
#       Expectation: the filesystem holding the root must survive pod
#       loss — records/checkpoints/manifests/provenance live there. The
#       check reads the mount's fstype (findmnt, df -PT fallback) and
#       FAILS on tmpfs/ramfs/overlay (pod-local ephemeral state); network
#       or block filesystems (nfs*, lustre, ext4, xfs, ...) pass.
#   R2  authoritative code revision: `git rev-parse HEAD` printed
#       (launch-packet row `repo_sha=`), compared against --revision
#       (prefix >= 7 chars accepted); a DIRTY tree FAILS — commit first,
#       a campaign must be attributable to one SHA.
#   R2b import resolution: a neutral-cwd probe proves the PINNED
#       (PYTHONPATH=this tree) child resolves hyperparam_tuning inside this
#       tree with the #299-tolerant loss_history, and reports what an
#       UNPINNED child would resolve (the editable-install E1 trap).
#   R3  dataset availability: abra_training_NNNN.h5 + abra_validation_NNNN.h5
#       for every index of every band (0..19) under the resolved data dir
#       (--data_dir > tidmad_data_config.yaml via execute_tools.data_paths).
#   R4  posture arithmetic (sourced from h100_posture.env):
#       chains x per-chain VRAM + min headroom must fit the card total
#       (pure function, unit-tested); and H100_CORESIDENCY_FACTOR must be
#       FILLED (empty predicts the band launcher's refusal — run
#       gpu_c_coresidency_probe.sh first).
#   R5  host-RAM headroom: MemAvailable >= expected 4-chain anon-RSS +
#       headroom (both posture rows; the 47 GB figure is the recorded
#       4-chain inspection OOM).
#   R6  arm+band identity coherence: the band launcher's --dry-run for
#       EVERY band of --arm resolves rc=0 with the expected
#       experiment_arm, derived run_name, and the DS8 pair
#       (--data_scope band + --health_gate_files <band files>) on the
#       child argv.
#   R7  arm argv-symmetry (#255 exposure determination — launch validity
#       is CONDITIONED on it): both arms' dry-runs with otherwise
#       identical arguments may differ ONLY in declared arm policy +
#       derived naming; especially the lock-invisible population knobs
#       (formal_portion / formal_train_portion / formal_eval_portion),
#       --data_dir, band/scope, time budgets, VRAM budgets and the
#       output-type surface must be IDENTICAL. Field-by-field diff on
#       failure (campaign_arm_symmetry.py; both arms run from THIS
#       checkout, so the SHA of R2 covers both).
#   R8  cold-start preconditions (#260 checklist, gate_testing_standard.md):
#       item 1 per-band workspaces absent/empty; item 3
#       agent_generated/models/*.py + _capability_index.json absent;
#       items 4 (workspace plugins/) covered by item 1; items 2/7
#       (seeds, advice) enforced by launcher refusals; items 5/6
#       (root-paper cache, runtime calibration) RETAIN by design — INFO.
#   R9  LLM reachability + concurrency smoke (campaign_llm_smoke.py):
#       a bounded burst of 8 parallel one-word completions through the
#       repo's own config loading; success count + p95 latency. NOT a
#       quota guarantee (provider-side limits act on the sustained
#       pattern) — skip with --skip_llm_smoke for offline rehearsals.
#
# Usage (campaign host):
#   bash sdsc_submission_scripts/campaign_preflight.sh \
#       --workspace-root /persist/siderius_campaign \
#       --arm with-prior-art|without-prior-art \
#       --revision <expected sha> \
#       [--data_dir DIR] [--llm_config FILE] [--skip_llm_smoke] \
#       [--symmetry-band 0-3] \
#       -- --healthgate_mode blocking --result_authority scientific \
#          [more chain flags the real launch will pass...]
#
#   Everything after `--` is forwarded VERBATIM to every dry-run (both
#   arms identically), so R6/R7 validate the launch you will actually
#   perform; --healthgate_mode + --result_authority are REQUIRED there
#   (run_one_iteration.py refuses a formal launch without them).
#   Dry-runs import the full framework: expect ~1-5 min total.
# ---------------------------------------------------------------------------

set -euo pipefail

PF_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PF_PROJECT_DIR="$(cd "${PF_SCRIPT_DIR}/.." && pwd)"
PF_LAUNCHER="${PF_SCRIPT_DIR}/launch_prior_baseline_experiment.sh"
PF_POSTURE="${PF_SCRIPT_DIR}/h100_posture.env"
PF_SYMMETRY="${PF_SCRIPT_DIR}/campaign_arm_symmetry.py"
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

# --- row bookkeeping --------------------------------------------------------

PF_FAILS=0
PF_ROWS=()
pf_pass() { PF_ROWS+=("PASS  $1"); echo "[preflight] PASS  $1"; }
pf_fail() { PF_ROWS+=("FAIL  $1"); echo "[preflight] FAIL  $1" >&2; PF_FAILS=$((PF_FAILS + 1)); }
pf_info() { PF_ROWS+=("INFO  $1"); echo "[preflight] INFO  $1"; }

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
            -h|--help) sed -n '2,73p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
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
        *) echo "ERROR: unknown --arm '$ARM'" >&2; return 1 ;;
    esac
    local OTHER_ARM="without-prior-art"
    [ "$ARM" = "without-prior-art" ] && OTHER_ARM="with-prior-art"

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
        [ "$band" = "$SYMMETRY_BAND" ] && ARM_CAPTURE="$OUT"
    done

    # ---- R7: arm argv-symmetry (#255) --------------------------------------
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
        if (cd "$PF_PROJECT_DIR" && PYTHONPATH="${PF_PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
                "$PF_PY" "$PF_SYMMETRY" --with-output "$WITH_CAP" --without-output "$WITHOUT_CAP" \
                --workspace-root "$WORKSPACE_ROOT" --band "$SYMMETRY_BAND"); then
            pf_pass "R7 arm argv-symmetry holds (#255): arms differ only in declared policy + derived naming"
        else
            pf_fail "R7 arm argv-symmetry VIOLATED (#255 — launch validity conditioned on this; see the field diff above)"
        fi
    fi

    # ---- R8: cold-start preconditions (#260) -------------------------------
    for band in "${PF_BANDS[@]}"; do
        local WS="${WORKSPACE_ROOT%/}/${ARM}_band${band}"
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
    pf_info "R8 items5/6 root_papers_cache + runtime calibration store: RETAIN by design"

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
