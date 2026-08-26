#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# quickstart.sh — the ONE documented way to run the `davis_future_prediction`
# example pack.
# ---------------------------------------------------------------------------
# WHAT THIS IS: a THIN adapter. It supplies three things and nothing else —
# this pack's task-composition manifest, the machine-local DAVIS root the
# operator names, and a small default bound on the work — then hands over to
# the NORMAL production chain launcher.
#
# WHAT THIS IS NOT, deliberately (Step 12 / PR-12e §V.2):
#   * not a second execution architecture,
#   * not an example-only orchestrator,
#   * not a wrapper around a Gate harness (`scripts/run_davis_gate2.py` is an
#     L3 real-execution EVIDENCE harness, not a way this task "runs"),
#   * not a duplicate of the launcher, and
#   * not a place where any DAVIS semantics live. Every declaration this run
#     binds lives under `examples/davis_future_prediction/`, reached through
#     `configs/task_composition/davis.yaml`.
#
# The command published in this pack's README is exactly this script, and the
# pack's regression test drives that same published string. There is no second
# path.
#
# Paths resolve from THIS FILE's location, never from the caller's working
# directory (CLAUDE.md portability rule), so the script works from anywhere and
# from a checkout at any absolute path.
# ---------------------------------------------------------------------------

set -euo pipefail

PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${PACK_DIR}/../.." && pwd)"

LAUNCHER="${REPO_ROOT}/sdsc_submission_scripts/run_chain.sh"
TASK_COMPOSITION="${REPO_ROOT}/configs/task_composition/davis.yaml"

# Per-node LLM routing. The chain default is an EMPTY `--llm_config`, and
# `run_one_iteration.py --llm_config` defaults to `None`, so omitting this
# silently falls back to the single `--llm_model` value with no per-node
# routing at all. The repository's documented setup is OpenAI-first; swap in
# `llm_configs/deepseek_tiered_pro.json` by repeating the flag (last-wins).
DEFAULT_LLM_CONFIG="${REPO_ROOT}/llm_configs/openai_tiered_pro.json"

# --- Bounded defaults -------------------------------------------------------
# A quickstart must be cheap. These are a PARAMETERIZATION of the normal
# production surface, never a bypass of it: every one of them is an ordinary
# chain flag, and every one is task-agnostic — `--trial_portion` /
# `--formal_portion` reach the composed task's own scope capability as
# `ScopeBuildRequest.portion`, and `--validation_max_samples` as its
# `max_samples` ceiling.
#
# `--data_scope` is NOT among them and must not be added: it is refused BY NAME
# for a composed task that does not declare TIDMAD's file topology (PR-12bc B7),
# so it cannot bound a DAVIS run at all.
#
# The launcher's argument parser is last-wins, so any of these can be raised by
# repeating the flag after this script's own arguments — see EXTRA below.
#
# `--start_iter 1` is NOT a bound; it is a CORRECTNESS pin, and omitting it can
# make this command do nothing while reporting success. `--auto_resume` is ON by
# default (`run_chain.sh:42`, `_chain_common.sh:173`). On a workspace that
# already EXISTS, `resolve_start_iter` (`run_chain.sh:277-278`) captures
# `START_ITER` from `scripts/inspect_run_state.py --next-iter` — and that
# capture is corrupted by plugin-loader stdout, with `--start_iter N` named as
# the workaround (CLAUDE.md, Step 10 / P5+P6). When the capture is bad the loop
# walks ZERO iterations, and `run_chain.sh:336` prints
# "… ${NUM_ITERATIONS} iterations walked" from the REQUESTED count rather than
# from what actually ran, so the chain announces success and exits 0. Pinning 1
# also turns a re-run against a NON-empty workspace into the loud stale-fresh
# refusal (`run_chain.sh:310`) instead of a silent no-op. A user resuming a
# real chain overrides it — `--start_iter N` after this script's own arguments.
DEFAULT_START_ITER=1
DEFAULT_NUM_ITERATIONS=1
DEFAULT_MAX_ROUNDS=1
DEFAULT_MAX_EPOCHS=1
DEFAULT_TRIAL_PORTION=0.1
DEFAULT_FORMAL_PORTION=0.1
DEFAULT_VALIDATION_MAX_SAMPLES=8
DEFAULT_RUN_NAME="davis_quickstart"
DEFAULT_MODE="lilab"

usage() {
    cat <<'USAGE'
Run the DAVIS 2017 future-frame-prediction example through the normal SIDERIUS
production chain.

Usage:
  bash examples/davis_future_prediction/quickstart.sh \
      --workspace <WORKSPACE_DIR> \
      --data_dir <DAVIS_DATA_ROOT> \
      [--run_name NAME] [extra chain flags...]

Required:
  --workspace DIR   where this run writes its iterations, records and logs.
                    Must be OUTSIDE the checkout. No default: a published
                    quickstart must never require a path that exists on one
                    machine.
  --data_dir DIR    the machine-local DAVIS 2017 root you prepared, i.e. the
                    directory that CONTAINS `DAVIS/JPEGImages/480p/`. No
                    default, for the same reason. Prepare it with:
                      python -m tools.example_packs.fetch_davis \
                          --dest <DAVIS_DATA_ROOT> --extract --check-layout

Optional:
  --run_name NAME   chain-level run name (default: davis_quickstart). Pins the
                    run id for the workspace.
  --print           print the resolved launcher command and exit without
                    running it.
  -h, --help        this message.

Anything else is passed straight through to
`sdsc_submission_scripts/run_chain.sh` and, because that parser is last-wins,
overrides this script's bounded defaults. Two useful examples:

  --dry-run                walk the chain and print the exact per-iteration
                           commands without touching the workspace
  --num_iterations 3       run a longer exploration than the bounded default
  --start_iter 4           resume a real chain instead of starting at 1
  --llm_config <path>      use a different per-node routing file, e.g.
                           llm_configs/deepseek_tiered_pro.json

Defaults this script supplies: --mode lilab, --start_iter 1, --num_iterations 1,
--max_rounds 1, --max_epochs 1, --trial_portion 0.1, --formal_portion 0.1,
--validation_max_samples 8, --llm_config llm_configs/openai_tiered_pro.json.
USAGE
}

WORKSPACE=""
DATA_DIR=""
RUN_NAME="${DEFAULT_RUN_NAME}"
PRINT_ONLY=0
EXTRA=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workspace)
            [[ $# -ge 2 ]] || { echo "ERROR: --workspace needs a value" >&2; exit 2; }
            WORKSPACE="$2"; shift 2 ;;
        --data_dir)
            [[ $# -ge 2 ]] || { echo "ERROR: --data_dir needs a value" >&2; exit 2; }
            DATA_DIR="$2"; shift 2 ;;
        --run_name)
            [[ $# -ge 2 ]] || { echo "ERROR: --run_name needs a value" >&2; exit 2; }
            RUN_NAME="$2"; shift 2 ;;
        --print)
            PRINT_ONLY=1; shift ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            EXTRA+=("$1"); shift ;;
    esac
done

# Both required inputs are refused BY NAME. A quickstart that quietly defaulted
# either one would either write into the checkout or read somebody else's data.
MISSING=()
[[ -n "${WORKSPACE}" ]] || MISSING+=("--workspace")
[[ -n "${DATA_DIR}" ]] || MISSING+=("--data_dir")
if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo "ERROR: missing required argument(s): ${MISSING[*]}" >&2
    echo "" >&2
    usage >&2
    exit 2
fi

# Deliberately NOT validated here: whether ${DATA_DIR} is a usable dataset root.
# That rule has exactly one owner — `bind_physical_data_root` fails the launch
# closed before an LLM call or a GPU minute is spent — and a second copy of it
# in this adapter would be a second authority.

if [[ ! -x "${LAUNCHER}" && ! -f "${LAUNCHER}" ]]; then
    echo "ERROR: chain launcher not found at ${LAUNCHER}" >&2
    echo "  This script resolves the repository root from its own location;" >&2
    echo "  ${REPO_ROOT} does not look like a SIDERIUS checkout." >&2
    exit 2
fi

# NOTE ON ROUND SEMANTICS: this script passes no `--is_trial` / `--no-is_trial`.
# `run_one_iteration.py` defaults `--is_trial` to TRUE, which is what makes the
# composed task's own scope capability reachable. Passing `--no-is_trial` here
# would look like "be more rigorous" and would in fact drop the run onto the
# legacy single-file TIDMAD path — scoring a future-frame prediction through a
# 1-D denoising route, silently, while every bounded knob above is ignored
# (PR-12d F-12d-26). Do not add it.
CMD=(
    bash "${LAUNCHER}"
    --mode "${DEFAULT_MODE}"
    --workspace "${WORKSPACE}"
    --run_name "${RUN_NAME}"
    --task_composition "${TASK_COMPOSITION}"
    --data_dir "${DATA_DIR}"
    --llm_config "${DEFAULT_LLM_CONFIG}"
    --start_iter "${DEFAULT_START_ITER}"
    --num_iterations "${DEFAULT_NUM_ITERATIONS}"
    --max_rounds "${DEFAULT_MAX_ROUNDS}"
    --max_epochs "${DEFAULT_MAX_EPOCHS}"
    --trial_portion "${DEFAULT_TRIAL_PORTION}"
    --formal_portion "${DEFAULT_FORMAL_PORTION}"
    --validation_max_samples "${DEFAULT_VALIDATION_MAX_SAMPLES}"
)
CMD+=(${EXTRA[@]+"${EXTRA[@]}"})

printf '[quickstart] repo root : %s\n' "${REPO_ROOT}"
printf '[quickstart] task      : %s\n' "${TASK_COMPOSITION}"
printf '[quickstart] launching :'
printf ' %q' "${CMD[@]}"
printf '\n'

if [[ "${PRINT_ONLY}" -eq 1 ]]; then
    exit 0
fi

exec "${CMD[@]}"
