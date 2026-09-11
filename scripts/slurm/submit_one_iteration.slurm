#!/bin/bash
# ---------------------------------------------------------------------------
# SIDERIUS Per-Iteration Slurm Job
# ---------------------------------------------------------------------------
# Runs ONE iteration of the 5-agent exploration workflow as a Slurm job.
# Designed for chained submission via run_chain.sh --mode sdsc — each
# job is 1-4 hours (fits gpu-shared partition easily) and writes a
# manifest.json that the next job uses to discover this iteration's
# output.
#
# Usage:
#   sbatch --partition=gpu-shared --nodes=1 --ntasks=1 --gpus=1 --mem=24G \
#          --time=04:00:00 --cpus-per-task=8 \
#          sdsc_submission_scripts/submit_one_iteration.slurm \
#          --workspace /expanse/lustre/projects/ddp433/ym137/exploration_v1 \
#          --iteration 3 \
#          --source_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \
#          --max_rounds 20
#
# FIXED SBATCH HEADERS (Static cluster configuration)
#SBATCH --job-name="SIDERIUS_ITER"

# NOTE: Resource parameters (nodes, ntasks, partition, gpus, mem, time, cpus-per-task)
# must be provided via sbatch CLI to ensure full compliance with the bank_limit plugin.

# --- Robust Error Handling ---
set -e
set -o pipefail

# --- Project Paths & Validation ---
PROJECT_DIR=""
CHECKOUT_BINDINGS=1

# The submission node passes the exact checkout immediately after this script.
# Do not infer it from the spooled script's directory or ambient activation.
if [ "${1:-}" = "--siderius-checkout" ]; then
    PROJECT_DIR="${2:-}"
    shift 2
elif [[ "${1:-}" == --siderius-checkout=* ]]; then
    PROJECT_DIR="${1#*=}"
    shift
fi
if [ -z "$PROJECT_DIR" ] || [[ "$PROJECT_DIR" != /* ]] || [ ! -d "$PROJECT_DIR" ]; then
    echo "[CRITICAL] --siderius-checkout must be an absolute existing directory" >&2
    exit 1
fi

if [ ! -d "$PROJECT_DIR" ]; then
    echo "[CRITICAL] Project directory $PROJECT_DIR not found!" >&2
    exit 1
fi

# --- Environment Setup ---
cd "$PROJECT_DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "[CRITICAL] Virtual environment not found in $PROJECT_DIR" >&2
    exit 1
fi
export VIRTUAL_ENV="$PROJECT_DIR/.venv"

unset PYTHONPATH

# Force Python stdout/stderr to be unbuffered so progress lines appear in the
# slurm .out file in real time, instead of being block-buffered in memory and
# only flushed when the process exits. Affects every python child process in
# this job session.
export PYTHONUNBUFFERED=1

# --- Application Defaults ---
WORKSPACE=""
ITERATION=""
SOURCE_PATHS=()
# Only the values this wrapper still needs: for its banner, its manifest
# verification, and as defaults when the caller supplied none. Every other
# application setting is forwarded verbatim and defaulted by Python.
MAX_ROUNDS=20
MAX_PROPOSAL_ATTEMPTS=3
LLM_MODEL="gemini-3.1-pro-preview"
TRIAL_PORTION=0.1
TRAIN_PORTION=0.1
EVAL_PORTION=0.1

# --- Argument parsing ---
#
# OWNERSHIP (V20 B-G3 / FU-B-16). This wrapper owns *scheduler* concerns.
# It does not own the application CLI and must not try to know it.
#
# It used to parse ~14 application flags into shell variables and then
# REBUILD the command line from them, ending with `*) shift ;;`. Every
# flag it did not name -- 35 of them, including --data_scope, every
# runtime-control flag and the VRAM budgets -- was silently discarded, so
# a run configured on the command line executed with different settings
# on SDSC than on lilab, with nothing in the log to say so.
#
# The rule now:
#
#     owned here        -> consume
#     not owned here    -> forward unchanged
#     unknown to Python -> Python rejects it, loudly
#
# `--workspace`, `--iteration` and `--source_paths` are PEEKED, not
# consumed: this script needs them for its banner and its post-run
# manifest verification, so it records the value AND forwards the tokens.
# Consuming them would be the same bug in a smaller form.
#
# `--` forwards everything after it verbatim and is the unambiguous
# interface; bare forwarding is kept so existing invocations still work.
FORWARD_ARGS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --)
      shift
      FORWARD_ARGS+=("$@")
      break
      ;;
    --workspace)
      WORKSPACE="$2"; FORWARD_ARGS+=("$1" "$2"); shift 2 ;;
    --siderius-checkout|--siderius-checkout=*)
      echo "[FAIL] duplicate --siderius-checkout binding" >&2
      exit 2
      ;;
    --iteration|--start_iteration)
      ITERATION="$2"; FORWARD_ARGS+=("$1" "$2"); shift 2 ;;
    --source_paths|--seed_paths)
      FORWARD_ARGS+=("$1"); shift
      while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
        SOURCE_PATHS+=("$1")
        FORWARD_ARGS+=("$1")
        shift
      done
      ;;
    *)
      # Not owned here. Forward the token exactly as received -- values,
      # `--flag=value`, negative numbers, paths with spaces and repeated
      # flags all survive because nothing is re-split or re-quoted.
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done

# Defaults are appended only when the caller did not supply the flag, so
# a value from run_chain.sh always wins and a direct `sbatch` invocation
# (the usage block above) keeps behaving as it did.
_has_flag() {
  local needle="$1"; shift
  local tok
  for tok in "$@"; do
    if [[ "$tok" == "$needle" || "$tok" == "$needle="* ]]; then
      return 0
    fi
  done
  return 1
}

_default_if_absent() {
  local flag="$1"; shift
  if ! _has_flag "$flag" "${FORWARD_ARGS[@]}"; then
    FORWARD_ARGS+=("$flag" "$@")
  fi
}

if [ -z "$WORKSPACE" ] || [ -z "$ITERATION" ] || [ ${#SOURCE_PATHS[@]} -eq 0 ]; then
    echo "[FAIL] Required args: --workspace, --iteration, --source_paths" >&2
    exit 1
fi

echo "############################################################"
echo "  SIDERIUS PER-ITERATION JOB"
echo "------------------------------------------------------------"
echo "  [EXECUTION CONTEXT]"
echo "    Workspace        : ${WORKSPACE}"
echo "    Iteration        : ${ITERATION}"
echo "    Source paths     : ${#SOURCE_PATHS[@]} files"
for p in "${SOURCE_PATHS[@]}"; do
    echo "      - $p"
done
echo "    Max rounds       : ${MAX_ROUNDS}"
echo "    LLM model        : ${LLM_MODEL}"
echo ""
echo "  [RUNTIME CONTEXT (Assigned by Slurm)]"
echo "    Job ID           : ${SLURM_JOB_ID:-N/A}"
echo "    Partition        : ${SLURM_JOB_PARTITION:-N/A}"
echo "    Nodes            : ${SLURM_JOB_NUM_NODES:-1}"
echo "    GPUs             : ${SLURM_JOB_GPUS:-0}"
echo "    CPUs             : ${SLURM_CPUS_PER_TASK:-N/A}"
echo "############################################################"

# --- Fill in defaults the caller did not specify ---
_default_if_absent --max_rounds "${MAX_ROUNDS}"
_default_if_absent --max_proposal_attempts "${MAX_PROPOSAL_ATTEMPTS}"
_default_if_absent --llm_model "${LLM_MODEL}"
_default_if_absent --trial_portion "${TRIAL_PORTION}"
_default_if_absent --train_portion "${TRAIN_PORTION}"
_default_if_absent --eval_portion "${EVAL_PORTION}"

if ! _has_flag --cleanup_denoised "${FORWARD_ARGS[@]}"; then
    FORWARD_ARGS+=(--cleanup_denoised)
fi
# Trial posture: only default it in if the caller expressed neither
# choice. `--no-is_trial` must survive, which is the whole point of
# making the flag able to express false.
if ! _has_flag --is_trial "${FORWARD_ARGS[@]}" && ! _has_flag --no-is_trial "${FORWARD_ARGS[@]}"; then
    FORWARD_ARGS+=(--is_trial)
fi

RUNNER_ARGS=("${FORWARD_ARGS[@]}")

# Validate source ownership on the compute node as well as the submission node.
PROBE_TMP="$(mktemp -d)"
cleanup_probe() { rm -rf "$PROBE_TMP"; }
trap cleanup_probe EXIT
if [ ! -f "$PROJECT_DIR/scripts/launch/_import_resolution_probe.py" ]; then
    echo "[FAIL] source-authority probe missing in checkout" >&2
    exit 1
fi
cp "$PROJECT_DIR/scripts/launch/_import_resolution_probe.py" "$PROBE_TMP/probe.py"
set +e
(cd "$PROBE_TMP" && "$PROJECT_DIR/.venv/bin/python" probe.py "$PROJECT_DIR" --tree-only)
PROBE_RC=$?
set -e
if [ "$PROBE_RC" -ne 0 ]; then
    echo "[FAIL] source-authority probe refused compute checkout (exit $PROBE_RC)" >&2
    exit 1
fi

# --- Execute the runner ---
set +e
"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/src/workflows/run_one_iteration.py" "${RUNNER_ARGS[@]}"
PY_EXIT_CODE=$?
set -e

# --- Post-Run Verification ---
echo ""
echo "--- Post-Run Verification ---"

if [ $PY_EXIT_CODE -ne 0 ]; then
    echo "[FAIL] Iteration runner exited with code: $PY_EXIT_CODE" >&2
    exit $PY_EXIT_CODE
fi

# Verify manifest.json was written
ITER_DIR_NAME=$(printf "iter_%03d" "${ITERATION}")
MANIFEST="${WORKSPACE}/${ITER_DIR_NAME}/manifest.json"
if [ ! -s "$MANIFEST" ]; then
    echo "[FAIL] Manifest not found or empty: $MANIFEST" >&2
    exit 1
fi

echo "[SUCCESS] Iteration ${ITERATION} complete. Manifest: $MANIFEST"
echo "############################################################"
echo "  SIDERIUS | Iteration Job ${SLURM_JOB_ID:-N/A} COMPLETED SUCCESSFULLY"
echo "############################################################"
