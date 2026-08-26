#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Oxford-IIIT Pet — the ONE documented run command for this example pack.
# Step 12 / PR-12e (§V.2 entrypoint contract, §V.14c "reuse, do not invent").
# ---------------------------------------------------------------------------
# Role: a THIN adapter with no logic of its own. It supplies THIS pack's
#       composition manifest and a set of small, bounded defaults, then execs
#       the NORMAL production chain launcher:
#
#           sdsc_submission_scripts/run_chain.sh
#               --task_composition configs/task_composition/pets.yaml
#
#       It is deliberately NOT a second execution architecture, NOT an
#       example-only orchestrator and NOT a Gate wrapper. Every flag below is
#       an ordinary production flag; delete this file and the same run is
#       still expressible by typing run_chain.sh directly.
#
#       No Pets semantics live here. Every declaration this run binds lives
#       under `examples/oxford_iiit_pet/`, reached through
#       `configs/task_composition/pets.yaml`.
#
# Two inputs are REQUIRED and have NO default, because no default could be
# correct on a machine other than the one it was written on (F-12e-UX-1):
#
#   --workspace DIR   where this run writes its records
#   --data_dir DIR    the extracted Oxford-IIIT Pet IMAGES directory, i.e.
#                     the directory that directly contains <image_id>.jpg
#                     (`<fetch --dest>/images`)
#
# Everything else is optional and every extra argument is passed straight
# through to run_chain.sh. The pass-through args are appended AFTER the
# defaults below, and the chain's parser is last-wins, so
# `--max_rounds 3` on this script's command line overrides the default of 1.
#
# Data preparation (explicit user action; the framework fetches nothing):
#
#   .venv/bin/python -m tools.example_packs.fetch_oxford_iiit_pet \
#       --dest <machine-local dir outside the repo> --extract
#
# See README.md for the full journey, including what to expect from the run.
# ---------------------------------------------------------------------------

set -euo pipefail

# Resolve the repository from THIS FILE's location, never from the caller's
# working directory (CLAUDE.md portability rule). The pack lives at
# <repo>/examples/oxford_iiit_pet/, so the repo root is two levels up.
PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${PACK_DIR}/../.." && pwd)"

LAUNCHER="${REPO_ROOT}/sdsc_submission_scripts/run_chain.sh"
COMPOSITION="${REPO_ROOT}/configs/task_composition/pets.yaml"
LLM_CONFIG="${REPO_ROOT}/llm_configs/openai_tiered_pro.json"

usage() {
    cat <<USAGE
Usage: bash examples/oxford_iiit_pet/quickstart.sh \\
           --workspace DIR --data_dir DIR [extra run_chain.sh args...]

Required:
  --workspace DIR   run workspace (created if absent; must be empty for a
                    fresh chain, or pass --force_fresh)
  --data_dir DIR    extracted Oxford-IIIT Pet images directory — the one that
                    directly contains <image_id>.jpg files

Common extras (any run_chain.sh flag works; later values win):
  --run_name NAME             default: pets_quickstart
  --num_iterations N          default: 1
  --max_rounds N              default: 1
  --dry-run                   print the exact child command, run nothing
  --healthgate_mode observe_only   do not let the health gates invalidate

Prepare the data first:
  .venv/bin/python -m tools.example_packs.fetch_oxford_iiit_pet \\
      --dest <machine-local dir outside the repo> --extract
USAGE
}

fail() {
    echo "examples/oxford_iiit_pet/quickstart.sh: $1" >&2
    echo "" >&2
    usage >&2
    exit 2
}

WORKSPACE=""
DATA_DIR=""
PASSTHROUGH=()

while [ $# -gt 0 ]; do
    case "$1" in
        --workspace)
            [ $# -ge 2 ] || fail "MISSING VALUE for --workspace"
            WORKSPACE="$2"
            shift 2
            ;;
        --data_dir)
            [ $# -ge 2 ] || fail "MISSING VALUE for --data_dir"
            DATA_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            PASSTHROUGH+=("$1")
            shift
            ;;
    esac
done

# Fail here, by name, rather than several minutes and one LLM call later
# inside the composition root. `bind_run_task_composition` does refuse a
# composed run with no data root, but only after the launcher has already
# started an iteration.
[ -n "$WORKSPACE" ] || fail "MISSING REQUIRED ARGUMENT --workspace (no default exists: it is machine-local)"
[ -n "$DATA_DIR" ] || fail "MISSING REQUIRED ARGUMENT --data_dir (no default exists: it is machine-local)"

if [ ! -d "$DATA_DIR" ]; then
    fail "DATA DIRECTORY NOT FOUND: '$DATA_DIR' is not a directory. It must be
  the EXTRACTED images directory containing <image_id>.jpg files — normally
  '<dest>/images' after:
      .venv/bin/python -m tools.example_packs.fetch_oxford_iiit_pet --dest <dest> --extract"
fi

[ -f "$LAUNCHER" ] || fail "PRODUCTION LAUNCHER NOT FOUND at '$LAUNCHER' (is this a complete checkout?)"
[ -f "$COMPOSITION" ] || fail "TASK COMPOSITION MANIFEST NOT FOUND at '$COMPOSITION' (is this a complete checkout?)"

# The bounded quickstart is a PARAMETERIZATION of the normal production
# surface, never a bypass (§V.1 F-12e-UX-2). Note what is NOT here:
#
#   * --data_scope — a TIDMAD partition-index concept. A composed task that
#     declares no TIDMAD topology refuses it BY NAME (12bc B7), so it cannot
#     bound this run at all.
#   * --target_files — parsed by the chain and then NOT forwarded
#     (_chain_common.sh: "DEPRECATED no-op (DS7)"), so it would silently do
#     nothing here.
#   * --healthgate_mode / --result_authority — `blocking` / `scientific` are
#     already the chain's defaults (_chain_common.sh:67-68) and are forwarded
#     to the child unconditionally (:441-442), so naming them here would add
#     two tokens a reader of the published command must evaluate before
#     discovering they change nothing. The README's expectation that both
#     BLOCKING health gates fire still holds; it is now inherited from the
#     launcher rather than restated here, and the regression test asserts the
#     child actually receives them.
#   * --no-is_trial — it does NOT mean "be more rigorous". `--is_trial`
#     means "trials are ALLOWED", it is the only input that can yield a
#     formal round, and run_one_iteration.py defaults it TRUE. Passing
#     --no-is_trial drops the run into the legacy single-file TIDMAD path,
#     where the composed scope capability is never called and every bounded
#     knob below is silently ignored (PR-12d F-12d-26).
#
# `--start_iter 1` is pinned deliberately, and it is a WORKAROUND for a known
# OPEN defect, not a style choice. With auto-resume (the chain default) and an
# EXISTING workspace directory, the start iteration is captured as the STDOUT
# of scripts/inspect_run_state.py — and the plugin loader also writes to
# stdout at import time. On a machine whose plugin directory is non-empty the
# capture is corrupted, `seq` is then handed the plugin banner instead of an
# integer, the iteration loop receives an EMPTY list, and the chain prints
# "CHAIN COMPLETE — 1 iterations" having run NOTHING. Reproduced on this
# repository while building this script. The defect is recorded in CLAUDE.md
# (Step 10 / P5+P6 carried debt) and `--start_iter N` is the workaround it
# names; it belongs to the chain launcher, so it is not repaired from an
# example pack. Pinning it also makes the quickstart mean what it says: a
# fresh, bounded run. Pass `--start_iter N` yourself to resume, and
# `--force_fresh` to reuse a non-empty workspace.
#
# The scope is already small before any portion is applied: the shipped
# manifest binds this pack's NESTED gate subsets (370 train / 74 eval rows),
# not the 2 946-row canonical training scope. The portions are pinned to 1.0
# because the chain defaults them to 0.1, which would cut 370 images to 37 —
# too few for the 37-class collapse evidence in the README to reproduce.
exec bash "$LAUNCHER" \
    --mode lilab \
    --task_composition "$COMPOSITION" \
    --workspace "$WORKSPACE" \
    --data_dir "$DATA_DIR" \
    --run_name pets_quickstart \
    --llm_config "$LLM_CONFIG" \
    --start_iter 1 \
    --num_iterations 1 \
    --max_rounds 1 \
    --max_epochs 1 \
    --trial_portion 1.0 \
    --eval_portion 1.0 \
    --formal_portion 1.0 \
    ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
