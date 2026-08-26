#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# examples/tidmad/quickstart.sh — the ONE documented command for this pack.
# ---------------------------------------------------------------------------
# Role : a THIN adapter. It supplies this pack's task-composition manifest and
#        a small, bounded default posture, then delegates to the NORMAL
#        production launcher. It owns no task logic, no execution architecture
#        and no scientific decision of its own.
#
#            examples/tidmad/quickstart.sh
#                 |
#                 v
#            sdsc_submission_scripts/run_chain.sh   (the production launcher)
#                 |
#                 v
#            sdsc_submission_scripts/run_one_iteration.py
#                 |
#                 v
#            the same workflow, plugins and declarations CI and the Gates run
#
# What this script is allowed to do, and nothing else:
#   1. resolve the repository root FROM ITS OWN LOCATION (never from $PWD);
#   2. refuse, by name, when a required input with no safe default is missing;
#   3. prepend `--task_composition <this pack's manifest>` and the bounded
#      quickstart defaults;
#   4. forward every user argument verbatim to the launcher.
#
# Why the defaults are prepended rather than merged: the launcher's parser is
# a `while`/`shift` loop, so the LAST occurrence of a flag wins
# (sdsc_submission_scripts/_chain_common.sh). Placing our defaults BEFORE
# "$@" therefore means any flag the user passes overrides ours, and the full
# launcher vocabulary stays available without this adapter re-declaring it.
#
# What this script must NEVER become (PR-12e §V.2, frozen): a second execution
# architecture, an example-only orchestrator, a hidden Gate wrapper, a task
# name branch in generic core, or a duplicate of the production launcher.
#
# Documented by: examples/tidmad/README.md — the command published there is
# the command exercised by
# tests/unit/examples/test_step12_pr12e_tidmad_quickstart.py.
# ---------------------------------------------------------------------------

set -euo pipefail

# --- Repository root, resolved from THIS FILE's location -------------------
# CLAUDE.md portability rule: a shell script resolves its paths relative to
# its own location, never to the caller's working directory. This is what
# lets the published command be copied and run from anywhere.
PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${PACK_DIR}/../.." && pwd)"

LAUNCHER="${REPO_ROOT}/sdsc_submission_scripts/run_chain.sh"
MANIFEST="${REPO_ROOT}/configs/task_composition/tidmad.yaml"

# --- The bounded quickstart posture ----------------------------------------
# Every value here is an ordinary flag of the production launcher, chosen to
# make a first run CHEAP. None of them is an example-only control.
#
# `--data_scope` is deliberately NOT used: it is a partition-index concept
# from TIDMAD's own topology and is refused by name for a composed task that
# declares no such topology, so it cannot be the shared quickstart mechanism
# across the example packs. The knobs below reach a composed task's scope
# capability instead. The README documents `--data_scope` separately, as the
# TIDMAD-specific extra bound it actually is.
QUICKSTART_DEFAULTS=(
    --mode lilab
    --task_composition "${MANIFEST}"
    --run_name tidmad_quickstart

    # Per-node model routing. Without it the run silently falls back to the
    # single `--llm_model` default with no routing at all (the chain default
    # is an empty LLM_CONFIG, and the app default is None). OpenAI-first
    # matches the repository's own documented setup; override with
    # `--llm_config llm_configs/deepseek_tiered_pro.json` or your own file.
    --llm_config "${REPO_ROOT}/llm_configs/openai_tiered_pro.json"

    # REQUIRED, and not cosmetic. `--auto_resume` defaults ON, and on an
    # EXISTING workspace the launcher captures its start iteration from
    # `scripts/inspect_run_state.py --next-iter` — a capture CLAUDE.md
    # records as corrupted by plugin-loader stdout, naming `--start_iter N`
    # as the workaround. The corrupted value reaches `seq`, the iteration
    # loop body never runs, and the chain still prints
    # "<N> iterations walked" (from the REQUESTED count, not the walked one)
    # and exits 0. A published command must not be able to do nothing and
    # report success. Pass `--start_iter N` yourself to resume deliberately.
    --start_iter 1

    --num_iterations 1
    --max_rounds 1
    --max_epochs 1

    # Portions, and why these deviate from the chain's 0.1 default. TIDMAD's
    # sampling unit is a 10,000,000-sample PSD segment and each of its 20
    # files holds 200 of them (resolved/dataset_profile.json), so the 0.1
    # default still means ~400 such segments per round. 0.02 means ~80 —
    # a first run that is bounded by the same knob a non-TIDMAD task uses,
    # rather than by dropping files with `--data_scope`.
    --trial_portion 0.02
    --formal_portion 0.02

    # TIDMAD-SPECIFIC, and safe ONLY here. A time budget switches on the
    # wall-time pre-flight, which resolves the training workload through
    # TIDMAD's topology; a composed task that declares none fails the
    # pre-flight before training. TIDMAD declares it, so these bound a
    # planner-chosen portion from producing a multi-hour round (CLAUDE.md's
    # standard launch command carries them for the same reason). Do NOT copy
    # these two flags into another pack's quickstart.
    --trial_time_budget_minutes 20
    --formal_time_budget_minutes 60
)

die() {
    echo "[tidmad-quickstart] ERROR: $*" >&2
    echo "" >&2
    echo "Run 'bash examples/tidmad/quickstart.sh --help' for the contract." >&2
    exit 2
}

usage() {
    cat <<'USAGE_EOF'
examples/tidmad/quickstart.sh — run the TIDMAD example task through the
normal SIDERIUS production chain.

USAGE
    bash examples/tidmad/quickstart.sh --workspace DIR --data_dir DIR [...]

REQUIRED (no defaults — a published quickstart must not depend on a path
that exists on one machine):

    --workspace DIR   where this run's outputs are written. Must be empty or
                      not yet exist for a fresh run.
    --data_dir  DIR   the directory holding the TIDMAD HDF5 files
                      (abra_training_*.h5 / abra_validation_*.h5). See
                      examples/tidmad/data/README.md for how to obtain them.

BOUNDED DEFAULTS APPLIED (each is an ordinary run_chain.sh flag; pass the
same flag yourself to override it):

    --mode lilab                      foreground subprocess
    --task_composition <repo>/configs/task_composition/tidmad.yaml
    --run_name tidmad_quickstart
    --llm_config <repo>/llm_configs/openai_tiered_pro.json
    --start_iter 1                    pins iteration 1; see the note below
    --num_iterations 1
    --max_rounds 1
    --max_epochs 1
    --trial_portion 0.02              ~80 PSD segments instead of ~400
    --formal_portion 0.02
    --trial_time_budget_minutes 20    TIDMAD-specific; see the README
    --formal_time_budget_minutes 60

`--start_iter 1` is deliberate. Auto-resume is ON by default and reads its
start iteration from a subprocess whose stdout can be polluted by the plugin
loader; the corrupted value makes the chain walk ZERO iterations while still
reporting success. Pass `--start_iter N` yourself to resume on purpose.

EVERY OTHER ARGUMENT is forwarded verbatim to
sdsc_submission_scripts/run_chain.sh — see its header, and
docs/reference/entrypoints.md, for the full vocabulary. Useful ones:

    --dry-run                         print the exact child command, run nothing
    --data_scope 4-9                  TIDMAD-only extra bound (see README)
    --health_gate_files 4,7,9         required with a partial --data_scope
    --llm_config llm_configs/openai_tiered_pro.json
USAGE_EOF
}

# --- Argument inspection ---------------------------------------------------
# The launcher's parser accepts `--flag value`, never `--flag=value`, so this
# scan uses the same rule. Last occurrence wins, exactly as the launcher does.
# Plain scalars rather than an array: `${#arr[@]}` on an EMPTY array is an
# error under `set -u` in bash < 4.4, which several long-lived cluster images
# still ship. This adapter must not be the reason a launch fails.
have_workspace=0
have_data_dir=0
data_dir_value=""
prev=""
equals_form=""

for arg in "$@"; do
    case "${arg}" in
        -h|--help)
            usage
            exit 0
            ;;
        --workspace)   have_workspace=1 ;;
        --data_dir)    have_data_dir=1 ;;
        --workspace=*) equals_form="--workspace" ;;
        --data_dir=*)  equals_form="--data_dir" ;;
    esac
    if [ "${prev}" = "--data_dir" ]; then
        data_dir_value="${arg}"
    fi
    prev="${arg}"
done

if [ -n "${equals_form}" ]; then
    die "the launcher takes space-separated values, not '=': write" \
        "'${equals_form} <value>' instead of '${equals_form}=<value>'."
fi

if [ "${have_workspace}" -eq 0 ]; then
    die "missing required flag --workspace. This quickstart has NO default" \
        "workspace: a published command must not write into a directory that" \
        "happens to exist on one machine. Pass --workspace <dir>."
fi

if [ "${have_data_dir}" -eq 0 ]; then
    die "missing required flag --data_dir. This quickstart has NO default" \
        "data root. TIDMAD's HDF5 files are obtained from the official" \
        "distribution named in examples/tidmad/PROVENANCE.md and staged in a" \
        "machine-local directory; pass that directory as --data_dir <dir>." \
        "(A permanently configured machine may also record it as" \
        "'tidmad_data_dir' in the gitignored tidmad_data_config.yaml, but the" \
        "published command states it explicitly so it reproduces anywhere.)"
fi

if [ ! -d "${data_dir_value}" ]; then
    die "--data_dir is not a readable directory: '${data_dir_value}'."
fi

# A cheap sanity check on the STAGED data, not a task decision: pointing at
# the wrong directory is the single most common first-run failure, and it
# otherwise surfaces only after an LLM call has already been spent. Which
# files are expected is projected in examples/tidmad/resolved/identity.json.
if ! compgen -G "${data_dir_value}/abra_*.h5" > /dev/null; then
    die "--data_dir '${data_dir_value}' contains no TIDMAD HDF5 file" \
        "(expected names like abra_validation_0000.h5 — see" \
        "examples/tidmad/resolved/identity.json for the full list, and" \
        "examples/tidmad/data/README.md for how to stage them)."
fi

# --- Repository integrity --------------------------------------------------
if [ ! -f "${LAUNCHER}" ]; then
    die "the production launcher was not found at '${LAUNCHER}'." \
        "This script resolves the repository root from its own location," \
        "so this means the pack was copied out of a SIDERIUS checkout."
fi

if [ ! -f "${MANIFEST}" ]; then
    die "this pack's task-composition manifest was not found at" \
        "'${MANIFEST}'. Without it the run would fall back to the legacy" \
        "un-composed path, which is not what this example demonstrates."
fi

# --- Delegate --------------------------------------------------------------
exec bash "${LAUNCHER}" "${QUICKSTART_DEFAULTS[@]}" "$@"
