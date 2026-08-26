#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS GPU-C co-residency calibration probe (arXiv launch topology)
# ---------------------------------------------------------------------------
# Role   : measure, ON THE CAMPAIGN CARD, the 4-way co-residency wall-time
#          slowdown factor that the H100 posture's watchdog / time-budget
#          rows carry (author ruling 2026-08-25). The RTX 5090 pairwise
#          figure (1.85-2.13x) is a stale LOWER BOUND and is never reused.
#          The probe is RESOURCE CALIBRATION, not science: it trains, it
#          times, it samples memory — it never runs inference or scoring,
#          and scores are explicitly out of scope.
#
# Shape  : two bounded legs through gpu_c_probe_train_leg.py (the per-leg
#          driver — the zero-LLM baseline-trial training path: paper-spec
#          config, epochs=1, snapshot SampleSet over one band's DataScope,
#          the REAL TidmadSandbox training subprocess on real TIDMAD data):
#
#            leg 1  SOLO — one chain, band 0-3 (the reference).
#            leg 2  QUAD — four co-resident chains, bands 0-3 / 4-9 /
#                   10-14 / 15-19, started together.
#
#          coresidency_factor = quad wall(band 0-3) / solo wall(band 0-3)
#          — the MATCHED band, so the bands' different file counts cannot
#          skew the ratio; the other three quad walls are recorded as
#          context. Per-chain VRAM peaks and per-tree anon-RSS peaks are
#          sampled by each driver over its own process tree; this
#          orchestrator additionally samples host MemAvailable during the
#          quad leg. Results: gpu_c_probe_result.json + a human summary.
#          The operator copies the factor into h100_posture.env
#          (H100_CORESIDENCY_FACTOR=...) with a posture version bump; the
#          band launcher refuses campaign --h100 launches until then.
#
# Bounds : BOUNDED by construction — each leg runs under `timeout`
#          (defaults: solo 1200 s, quad 2100 s; ~55 min worst case, under
#          the ~1 h cap). A timed-out leg is a FAILED leg: the assembler
#          reports it and exits non-zero, and the factor is not usable
#          evidence.
#
# Refuses: to run when the GPU already has compute processes (a probe on
#          a busy card measures the neighbours, not the topology), or when
#          nvidia-smi / a project venv python is unavailable.
#
# Usage (on the H100 box, GPU C pinned):
#   CUDA_VISIBLE_DEVICES=<gpu_c_index> \
#   bash sdsc_submission_scripts/gpu_c_coresidency_probe.sh \
#       [--work-dir DIR] [--model wavenet] [--train-portion 0.05] \
#       [--solo-cap-seconds 1200] [--quad-cap-seconds 2100] [--out FILE]
#
#   The default --work-dir is ${TMPDIR:-/tmp}/gpu_c_probe_<epoch> — probe
#   artifacts are throwaway calibration state, NOT campaign records, so
#   they do not need the persistent volume.
# ---------------------------------------------------------------------------

set -euo pipefail

PROBE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE_PROJECT_DIR="$(cd "${PROBE_SCRIPT_DIR}/.." && pwd)"
# E1 pin — the probe's training legs are real children; they must resolve
# THIS tree (see launch_prior_baseline_experiment.sh for the full note).
export PYTHONPATH="${PROBE_PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
PROBE_DRIVER="${PROBE_SCRIPT_DIR}/gpu_c_probe_train_leg.py"

PROBE_BANDS=("0-3" "4-9" "10-14" "15-19")
PROBE_REFERENCE_BAND="0-3"

probe_usage() {
    sed -n '2,55p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

probe_resolve_python() {
    if [ -n "${SIDERIUS_PYTHON:-}" ]; then
        PROBE_PY="$SIDERIUS_PYTHON"
    elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        PROBE_PY="$VIRTUAL_ENV/bin/python"
    elif [ -x "${PROBE_PROJECT_DIR}/.venv/bin/python" ]; then
        PROBE_PY="${PROBE_PROJECT_DIR}/.venv/bin/python"
    else
        echo "ERROR: no project python (SIDERIUS_PYTHON / \$VIRTUAL_ENV / ${PROBE_PROJECT_DIR}/.venv)." >&2
        echo "  The probe refuses system python3 — SIDERIUS requires the project venv." >&2
        return 1
    fi
}

probe_refuse_busy_gpu() {
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        echo "ERROR: nvidia-smi not found — the probe needs GPU telemetry to run." >&2
        return 1
    fi
    local apps
    apps="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null || true)"
    if [ -n "$apps" ]; then
        echo "ERROR: the GPU already has compute processes (pids: $(echo "$apps" | tr '\n' ' '))." >&2
        echo "  A probe on a busy card measures the neighbours, not the topology. Wait or" >&2
        echo "  pin an idle card via CUDA_VISIBLE_DEVICES." >&2
        return 1
    fi
}

probe_main() {
    local WORK_DIR="" MODEL="wavenet" TRAIN_PORTION="0.05"
    local SOLO_CAP=1200 QUAD_CAP=2100 OUT=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            --work-dir|--work_dir)           WORK_DIR="$2"; shift 2 ;;
            --model)                          MODEL="$2"; shift 2 ;;
            --train-portion|--train_portion)  TRAIN_PORTION="$2"; shift 2 ;;
            --solo-cap-seconds|--solo_cap_seconds) SOLO_CAP="$2"; shift 2 ;;
            --quad-cap-seconds|--quad_cap_seconds) QUAD_CAP="$2"; shift 2 ;;
            --out)                            OUT="$2"; shift 2 ;;
            -h|--help)                        probe_usage; return 0 ;;
            *)
                echo "ERROR: unknown argument $1" >&2
                return 1 ;;
        esac
    done

    probe_resolve_python
    probe_refuse_busy_gpu

    [ -z "$WORK_DIR" ] && WORK_DIR="${TMPDIR:-/tmp}/gpu_c_probe_$(date +%s)"
    mkdir -p "$WORK_DIR"
    WORK_DIR="$(cd "$WORK_DIR" && pwd)"
    [ -z "$OUT" ] && OUT="${WORK_DIR}/gpu_c_probe_result.json"

    echo "[gpu-c-probe] work_dir=$WORK_DIR model=$MODEL train_portion=$TRAIN_PORTION"
    echo "[gpu-c-probe] caps: solo ${SOLO_CAP}s, quad ${QUAD_CAP}s (bounded probe, ~1h worst case)"
    echo "[gpu-c-probe] CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<unset — pin GPU C!>}"

    # PYTHONPATH pins THIS checkout (portability rule: a shared venv's
    # editable install may point at another clone).
    local -a DRIVER_ENV=(env "PYTHONPATH=${PROBE_PROJECT_DIR}${PYTHONPATH:+:${PYTHONPATH}}")

    # ---- leg 1: SOLO reference (band 0-3) --------------------------------
    echo "[gpu-c-probe] leg 1/2 SOLO band ${PROBE_REFERENCE_BAND} ..."
    if ! (cd "$PROBE_PROJECT_DIR" && timeout --signal=TERM --kill-after=60 "$SOLO_CAP" \
            "${DRIVER_ENV[@]}" "$PROBE_PY" "$PROBE_DRIVER" leg \
            --band "$PROBE_REFERENCE_BAND" --leg-label solo \
            --workspace "${WORK_DIR}/solo_band${PROBE_REFERENCE_BAND}" \
            --model "$MODEL" --train-portion "$TRAIN_PORTION" \
            --out "${WORK_DIR}/leg_solo.json"); then
        echo "ERROR: solo reference leg failed or timed out (cap ${SOLO_CAP}s) —" >&2
        echo "  no reference wall time, so the quad leg would prove nothing. Aborting." >&2
        return 1
    fi

    # ---- leg 2: QUAD co-resident (all four bands) ------------------------
    echo "[gpu-c-probe] leg 2/2 QUAD bands ${PROBE_BANDS[*]} ..."
    : > "${WORK_DIR}/host_memavailable_samples.txt"
    (
        while :; do
            awk '/MemAvailable:/ {print systime(), $2}' /proc/meminfo \
                >> "${WORK_DIR}/host_memavailable_samples.txt"
            sleep 5
        done
    ) &
    local SAMPLER_PID=$!

    local band PIDS=()
    for band in "${PROBE_BANDS[@]}"; do
        (cd "$PROBE_PROJECT_DIR" && timeout --signal=TERM --kill-after=60 "$QUAD_CAP" \
            "${DRIVER_ENV[@]}" "$PROBE_PY" "$PROBE_DRIVER" leg \
            --band "$band" --leg-label quad \
            --workspace "${WORK_DIR}/quad_band${band}" \
            --model "$MODEL" --train-portion "$TRAIN_PORTION" \
            --out "${WORK_DIR}/leg_quad_band${band}.json") \
            > "${WORK_DIR}/quad_band${band}.log" 2>&1 &
        PIDS+=($!)
        echo "[gpu-c-probe]   quad band $band -> pid ${PIDS[-1]} (log ${WORK_DIR}/quad_band${band}.log)"
    done

    local QUAD_RC=0 pid
    for pid in "${PIDS[@]}"; do
        wait "$pid" || QUAD_RC=1
    done
    kill "$SAMPLER_PID" 2>/dev/null || true
    wait "$SAMPLER_PID" 2>/dev/null || true
    if [ "$QUAD_RC" -ne 0 ]; then
        echo "WARNING: at least one quad leg failed or timed out — the assembler will" >&2
        echo "  name the failed legs and exit non-zero (factor not usable)." >&2
    fi

    # ---- assemble --------------------------------------------------------
    (cd "$PROBE_PROJECT_DIR" && "${DRIVER_ENV[@]}" "$PROBE_PY" "$PROBE_DRIVER" assemble \
        --work-dir "$WORK_DIR" --out "$OUT")
}

# Source-safe entry guard (house convention): sourcing this file for its
# functions must never start a probe.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    probe_main "$@"
    exit $?
fi
