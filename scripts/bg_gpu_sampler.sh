#!/bin/bash
# GPU lifecycle sampler for the B-G validation scenarios. VALIDATION ONLY.
#
# READ-ONLY with respect to the run: samples nvidia-smi and /proc, never
# signals, never writes into the run workspace, never touches the
# repository. Runs as a sibling of the tuner, not as its parent, so
# stopping it cannot affect the run under measurement.
#
# SAMPLING RATE. ~5 Hz was required because a short pre-flight worker can
# slip entirely between 1 Hz samples, which would make "worker appears"
# report a false negative. Measured on the RTX 5090 host:
# --query-compute-apps 53 ms, --query-gpu 42 ms. Doing both every
# iteration caps the loop at ~3.3 Hz, below the requirement. So the
# per-PID stream — the one every gating criterion reads — runs every
# iteration (~6.5 Hz), and the device-total stream, a secondary
# cross-check, is sampled every 10th iteration (~0.65 Hz).
#
# ROLE ATTRIBUTION BY PID (FU-B-15). Roles used to be assigned purely by
# matching a name in /proc/<pid>/cmdline. That silently failed for the
# tuner parent: the pattern was `ml_hyperparameter_tune_agent`, but the
# B-G runs launch through `scripts/bg_admission_validation.py`, so B-G0
# and B-G1 produced *no* P0_TUNER_PARENT sample at all and "parent held
# 0 MiB" rested on absence from NVML rather than on a labelled
# measurement.
#
# So identity now beats name matching: the harness writes the PIDs it
# knows, and this script reads them. A PID is exact; a command-line
# substring is a guess that happens to be right. The name patterns
# remain only as a fallback for processes nobody registered.
#
#   <outdir>/tuner_parent.pid   written by bg_admission_validation.py
#   <outdir>/holder.pid         written by bg_gpu_holder.py, if used
#
# Both are polled every iteration, so a PID registered after sampling
# starts is picked up without a restart.
#
# Usage:  scripts/bg_gpu_sampler.sh <outdir>
# Stop:   touch <outdir>/STOP     (or Ctrl-C)

set -u

OUTDIR="${1:?usage: bg_gpu_sampler.sh <outdir>}"
mkdir -p "$OUTDIR"

GPU_CSV="$OUTDIR/gpu_samples.csv"
DEV_CSV="$OUTDIR/device_samples.csv"
PS_LOG="$OUTDIR/ps_snapshots.log"
STOP="$OUTDIR/STOP"
PARENT_PID_FILE="$OUTDIR/tuner_parent.pid"
HOLDER_PID_FILE="$OUTDIR/holder.pid"

MAX_BYTES=$((512 * 1024 * 1024))   # runaway guard; ~3 MB expected
PS_INTERVAL_S=5

echo "epoch,pid,used_mib,comm,role" > "$GPU_CSV"
echo "epoch,device_used_mib,device_total_mib" > "$DEV_CSV"

# Read a registered PID, or empty if the file is absent or malformed.
# Never fails: a missing registration must degrade to name matching, not
# abort the sampler mid-run.
read_pid() {
    local f="$1" v
    [ -r "$f" ] || return 0
    v=$(tr -dc '0-9' < "$f" 2>/dev/null)
    printf '%s' "$v"
}

# Map a PID to a role. Registered identity first, command line second.
classify() {
    local pid="$1" cmdline
    [ -n "$PARENT_PID" ] && [ "$pid" = "$PARENT_PID" ] && { echo "P0_TUNER_PARENT"; return 0; }
    [ -n "$HOLDER_PID" ] && [ "$pid" = "$HOLDER_PID" ] && { echo "HOLDER"; return 0; }
    cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null) || return 1
    case "$cmdline" in
        *preflight_worker_main*)            echo "P1_PREFLIGHT_WORKER" ;;
        *train_engine_sandbox*)             echo "P2_TRAINING" ;;
        *inference_single*)                 echo "P3_INFERENCE" ;;
        *denoising_score_single*)           echo "SCORING" ;;
        *bg_gpu_holder*)                    echo "HOLDER" ;;
        *ml_hyperparameter_tune_agent*)     echo "P0_TUNER_PARENT" ;;
        *bg_admission_validation*)          echo "P0_TUNER_PARENT" ;;
        *)                                  echo "FOREIGN" ;;
    esac
}

iter=0
last_ps=0
PARENT_PID=""
HOLDER_PID=""

echo "[bg_sampler] started $(date -Iseconds) -> $OUTDIR" >&2
echo "[bg_sampler] per-PID ~6.5 Hz, device ~0.65 Hz, ps every ${PS_INTERVAL_S}s" >&2
echo "[bg_sampler] role PIDs polled from tuner_parent.pid / holder.pid" >&2
echo "[bg_sampler] stop with: touch $STOP" >&2

while [ ! -e "$STOP" ]; do
    iter=$((iter + 1))
    ts=$(date +%s.%N)

    # Re-read every iteration: the harness registers its PID after the
    # sampler is already running, and a holder may start mid-run.
    PARENT_PID=$(read_pid "$PARENT_PID_FILE")
    HOLDER_PID=$(read_pid "$HOLDER_PID_FILE")

    # --- per-PID stream: every iteration ---------------------------------
    # An empty result is a legitimate sample (GPU idle) and must stay
    # visible in the timeline. A gap in the file would be ambiguous
    # between "idle" and "sampler died", so emit an explicit marker.
    apps=$(nvidia-smi --query-compute-apps=pid,used_gpu_memory \
                      --format=csv,noheader,nounits 2>/dev/null)
    if [ -z "$apps" ]; then
        echo "$ts,,,,NO_COMPUTE_APPS" >> "$GPU_CSV"
    else
        while IFS=, read -r pid mem; do
            pid="${pid// /}"; mem="${mem// /}"
            [ -z "$pid" ] && continue
            comm=$(cat "/proc/$pid/comm" 2>/dev/null || echo "gone")
            role=$(classify "$pid" || echo "gone")
            echo "$ts,$pid,$mem,$comm,$role" >> "$GPU_CSV"
        done <<< "$apps"
    fi

    # --- device total: every 10th iteration -------------------------------
    # Independent of per-PID accounting, so a leak that per-PID sampling
    # misses still shows up here.
    if [ $((iter % 10)) -eq 1 ]; then
        nvidia-smi --query-gpu=memory.used,memory.total \
                   --format=csv,noheader,nounits 2>/dev/null |
            while IFS=, read -r used total; do
                echo "$ts,${used// /},${total// /}" >> "$DEV_CSV"
            done
    fi

    # --- process snapshot: every PS_INTERVAL_S ----------------------------
    # The no-orphan and no-candidate-child proofs read this, so it
    # records full command lines, not just PIDs.
    now=$(date +%s)
    if [ $((now - last_ps)) -ge "$PS_INTERVAL_S" ]; then
        last_ps=$now
        {
            echo "--- $(date -Iseconds) parent=${PARENT_PID:-unregistered} holder=${HOLDER_PID:-none}"
            ps -eo pid,ppid,etimes,rss,args 2>/dev/null |
                grep -E "train_engine_sandbox|inference_single|denoising_score_single|preflight_worker_main|bg_gpu_holder|bg_admission_validation|ml_hyperparameter_tune_agent" |
                grep -v grep
        } >> "$PS_LOG"
    fi

    # Runaway guard: stop rather than fill the disk.
    if [ "$(stat -c%s "$GPU_CSV" 2>/dev/null || echo 0)" -gt "$MAX_BYTES" ]; then
        echo "[bg_sampler] size guard hit; stopping" >&2
        break
    fi

    sleep 0.05
done

echo "[bg_sampler] stopped $(date -Iseconds)" >&2
