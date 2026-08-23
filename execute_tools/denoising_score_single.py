#!/usr/bin/env python3
"""
denoising_score_single.py — single-file denoising score CLI.

Thin wrapper around :func:`execute_tools.scoring_utils.score_vector` that
produces one scalar denoising score for one validation file. Used by
``core/sandbox_executor.py::execute_scoring`` via subprocess (it runs under
a separate RSS-limited preexec, which is why the interface is CLI, not
in-process).

**Scoring convention** — Option B, anchor-normalized, global ``s_max``:

    per_segment  = (snr_sg[i] / s_max_GLOBAL) · snr_squid[i]
    grand_mean   = mean_i(per_segment)                # 200 segments / file
    score        = log_{5.27}(grand_mean)  if grand_mean > 0 else -inf

where ``s_max`` is read from ``segment_anchors.json`` (built on the fine
validation files 0-19). This is the same formula and the same global ruler
used by ``scoring_utils.score_vector`` and by the ground-truth ceiling, so
baseline, model, and ceiling scores are directly comparable.

The legacy ``--coarse`` and ``--weak`` flags are accepted for CLI backward
compatibility (sandbox_executor would break without them) but are no-ops;
a warning is logged when they are used.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys

logging.basicConfig(
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
    level=logging.INFO,
)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="Single-file denoising score (Option B, global s_max).",
)
parser.add_argument(
    "--mode",
    type=str,
    choices=["fix", "agent"],
    default="fix",
    help="Baseline (fix) or agent-produced (agent) denoised file.",
)
parser.add_argument(
    "--data_dir", "-d", type=str, default=None, help="Directory containing the denoised HDF5 file."
)
parser.add_argument(
    "--dataset_profile_json",
    type=str,
    default=None,
    help=(
        "Path to a resolved Dataset Profile JSON. OMITTED resolves the "
        "Regime-A TIDMAD adapter; SUPPLIED but broken fails closed."
    ),
)
parser.add_argument(
    "--raw_data_dir",
    type=str,
    default=None,
    help="Directory containing the raw abra_validation_XXXX.h5 "
    "files (used for CH2 center-freq pickup). "
    "Default: TIDMAD_DATA_DIR.",
)
parser.add_argument(
    "--anchor_map",
    type=str,
    default=None,
    help="Path to segment_anchors.json (used for global s_max). "
    "Default: the committed reference_data/segment_anchors.json, resolved from "
    "the package location (independent of the working directory).",
)
parser.add_argument("--denoising_model", "-m", type=str, default="punet")
parser.add_argument(
    "--exp_id", type=str, default="default_run", help="Experiment ID (required for agent mode)."
)
parser.add_argument(
    "--run_name", type=str, default="test_run", help="Run name for the auto-exploration."
)
parser.add_argument(
    "--file_index", "-i", type=int, default=6, help="Validation file index (0-19 fine)."
)
parser.add_argument(
    "-c", "--coarse", action="store_true", help="(Deprecated no-op; kept for CLI compatibility.)"
)
parser.add_argument(
    "-p", "--parallel", action="store_true", help="Use parallel workers inside score_vector."
)
parser.add_argument("-n", "--num_workers", type=int, default=8)
parser.add_argument(
    "-w", "--weak", action="store_true", help="(Deprecated no-op; kept for CLI compatibility.)"
)
parser.add_argument(
    "--output_json", type=str, help="Optional path; denoising_score is merged into this JSON."
)
parser.add_argument(
    "--task_manifest",
    type=str,
    default=None,
    help="Step 11 C5: the composed run's task-composition manifest, emitted "
    "by the parent FROM its resolved run binding only — never an operator "
    "flag. SUPPLIED -> the run's DECLARED metric is composed through the "
    "same authority the parent used, and a failure to compose terminates "
    "this subprocess rather than falling back. ABSENT -> the legacy "
    "un-composed derivation, byte-identical.",
)
parser.add_argument(
    "--task_data_path_id",
    type=str,
    default=None,
    help="D14-1: the child side of the task-data-path transport. Emitted by "
    "the parent process FROM its resolved run binding only — never an "
    "operator flag. SUPPLIED -> explicit binding (an unknown id fails "
    "closed, never falls back); ABSENT -> regime-A (TIDMAD compatibility).",
)
parser.add_argument(
    "--task_data_path_identity",
    type=str,
    default=None,
    help="Step 12 / PR-12bc C2: the PARENT-PINNED IDENTITY of the implementation named by --task_data_path_id. The id says WHICH implementation; this says WHICH CODE. Verified BEFORE the implementation is consumed, because a registry hit is never proof of identity — a stale registration answers to the right name while running different bytes. ABSENT -> a parent that predates this transport made no claim, and a child must not invent one.",
)

args = parser.parse_args()

# ---------------------------------------------------------------------------
# Deprecation notices for legacy flags
# ---------------------------------------------------------------------------

if args.coarse:
    logging.warning(
        "--coarse flag is maintained for CLI compatibility; "
        "scoring now uses the Option B global alignment."
    )
if args.weak:
    logging.warning(
        "--weak flag is maintained for CLI compatibility; "
        "scoring now uses the Option B global alignment."
    )

# ---------------------------------------------------------------------------
# Resolve defaults
# ---------------------------------------------------------------------------

from execute_tools.build_anchor_map import resolve_anchor_map_path  # noqa: E402
from execute_tools.data_paths import TIDMAD_DATA_DIR  # noqa: E402
from execute_tools.dataset_config import (  # noqa: E402
    load_dataset_profile,
    resolve_dataset_profile,
    tidmad_topology,
)

if args.data_dir is None:
    args.data_dir = TIDMAD_DATA_DIR
if args.raw_data_dir is None:
    args.raw_data_dir = TIDMAD_DATA_DIR
# Anchor map: an explicit --anchor_map override wins; otherwise use the
# committed reference artifact (reference_data/segment_anchors.json), resolved
# from the package location independently of the current working directory. The
# artifact is never regenerated during scoring; load_anchor_map (below) fails
# clearly if it is missing or malformed.
args.anchor_map = resolve_anchor_map_path(args.anchor_map)

# ---------------------------------------------------------------------------
# Filename construction — through the Deliverable Contract (Step 06 C3)
# ---------------------------------------------------------------------------

# D14-1 C4: side-effect import — module tail registers the TIDMAD
# implementation, which regime-A resolution (agent mode below) requires.
# Step 10 / P5+P6 W3 — the BUILT-INS' BOOTSTRAP, not the extension path.
#
# A composed run transports its data-path id to this child
# (`--task_data_path_id`), and `resolve_task_data_path` fails closed on an id
# the child's registry does not hold. Before this, every child imported ONLY
# the TIDMAD implementation, so a transported `oxford_iiit_pet` or
# `davis_future_prediction` id could not resolve here even though all three
# implementations are in-tree production modules and the parent-side emitter
# already existed. Side-effect imports: each module's tail self-registers.
#
# Out-of-tree plugin availability in children is deliberately NOT solved here
# (Step 12 owns it) — this list is the built-ins' convenience bootstrap, the
# same pattern `execute_tools/health_checks/__init__.py` documents.
import execute_tools.davis_data_path  # noqa: E402
import execute_tools.pets_data_path  # noqa: E402
import execute_tools.tidmad_data_path  # noqa: E402, F401
from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec  # noqa: E402
from execute_tools.evaluation_metric import (  # noqa: E402
    NotScoreableResult,
    derive_tidmad_metric,
)

# Dataset Profile: supplied-but-broken fails closed, absent keeps Regime-A.
if args.dataset_profile_json is not None:
    dataset_profile = load_dataset_profile(args.dataset_profile_json)
else:
    dataset_profile = resolve_dataset_profile()

# 05c §3.2a Option A: the child RECONSTRUCTS the run's deliverable spec and
# metric from the profile that already crosses — one derivation, the same
# value the parent holds; no spec or metric is serialized, no argv is added.
# The two deliverable-name literals 05c left here for Step 06 now resolve
# through the naming authority: byte-identical names, declared once.
# Step 11 C6 — a composed run's DECLARED deliverable naming, bound before the
# spec is derived so `derive_tidmad_deliverable_spec` resolves the run's
# template rather than the shipped one. Same transported manifest C5 uses,
# same PRESENCE discrimination; an un-composed run binds nothing and derives
# byte-identically. The Deliverable Contract remains the naming owner — this
# child reads a declaration, it does not invent one (R-11-3).
if args.task_manifest is not None:
    from execute_tools.deliverable_spec import bind_deliverable_naming
    from workflows.task_composition import compose_deliverable_naming_from_manifest

    _declared_naming = compose_deliverable_naming_from_manifest(args.task_manifest)
    _naming_ctx = (
        bind_deliverable_naming(_declared_naming)
        if _declared_naming is not None
        else contextlib.nullcontext()
    )
else:
    _naming_ctx = contextlib.nullcontext()

with _naming_ctx:
    deliverable_spec = derive_tidmad_deliverable_spec(dataset_profile)

# Step 11 C5 (R-11-4) — the METRIC half of that reconstruction is no longer
# unconditional. Step 06 chose to re-derive TIDMAD's metric here because
# nothing else crossed; that choice is exactly what made this child
# TIDMAD-only, and it is superseded for a COMPOSED run.
#
# Discrimination is by the PRESENCE of the transported manifest, never by a
# task name. A composed run composes its DECLARED metric through the same
# declaration -> MetricSpec -> implementation authority the parent used; an
# un-composed run keeps the derivation byte-for-byte.
#
# There is deliberately NO fallback: `compose_metric_from_manifest` raises
# `TaskCompositionError` and this child lets it terminate the scoring
# subprocess. A composed run must NEVER silently score with TIDMAD's
# metric — that is the C-P56-1 failure class one layer down, and a
# fallback here would be indistinguishable from success.
if args.task_manifest is not None:
    from workflows.task_composition import compose_metric_from_manifest

    metric = compose_metric_from_manifest(args.task_manifest)
else:
    metric = derive_tidmad_metric(dataset_profile, deliverable_spec)

if args.denoising_model == "none":
    # RAW validation file — Step-02-owned INPUT topology, from the profile.
    fname = tidmad_topology(dataset_profile).dataset.validation_file_name(args.file_index)
    full_path = os.path.join(args.data_dir, fname)
elif args.mode == "fix":
    fname = deliverable_spec.naming.unqualified_name(
        model_type=args.denoising_model, file_index=args.file_index
    )
    full_path = os.path.join(args.data_dir, fname)
else:  # agent
    # D14-1 C4 — the production scoring read resolves the run's deliverables
    # THROUGH the task data path's decoded payload (child side of the
    # transport: SUPPLIED+unknown fails closed; ABSENT is regime-A). A file
    # the payload does not contain keeps its authority-derived EXPECTED path,
    # so the Step-06 scoreability contract still owns the structured
    # missing-deliverable refusal — the failure mode is byte-identical.
    from execute_tools.dataset_config import bind_dataset_profile
    from execute_tools.task_data_path import (
        EvaluationReadRequest,
        resolve_task_data_path,
    )

    # C3: one resolution authority across all three children. Scoring already
    # had the manifest for its metric; the data path now reads it too, so an
    # out-of-tree task resolves the same way here as in training and inference.
    from workflows.task_composition import resolve_child_task_data_path

    _data_path = (
        resolve_child_task_data_path(
            args.task_data_path_id,
            identity=args.task_data_path_identity,
            manifest_path=args.task_manifest,
        )
        if args.task_data_path_id is not None
        else resolve_task_data_path(None)
    )
    with bind_dataset_profile(dataset_profile):
        _payload = _data_path.read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=args.data_dir,
                exp_id=args.exp_id,
                run_name=args.run_name,
                model_type=args.denoising_model,
            )
        )
    _resolved = _payload.get(args.file_index) if isinstance(_payload, dict) else None
    if _resolved is not None:
        full_path = _resolved
        fname = os.path.basename(_resolved)
    else:
        fname = deliverable_spec.naming.name(
            model_type=args.denoising_model,
            run_name=args.run_name,
            exp_id=args.exp_id,
            file_index=args.file_index,
        )
        full_path = os.path.join(args.data_dir, fname)

# ---------------------------------------------------------------------------
# Score THROUGH the metric handle: scoreability first, then score_vector
# ---------------------------------------------------------------------------

from execute_tools.build_anchor_map import load_anchor_map  # noqa: E402
from execute_tools.scoring_utils import coerce_nonfinite_to_none  # noqa: E402

anchor_data = load_anchor_map(args.anchor_map)
s_max = float(anchor_data["s_max"])
anchors = anchor_data["anchors"]

sample_set = {
    args.file_index: list(range(tidmad_topology(dataset_profile).dataset.segments_per_file))
}


def _denoised_fn(_fi: int) -> str:
    # score_vector calls this per file-index; we only have one file here.
    return fname


def _merge_output_json(payload: dict) -> None:
    """Merge ``payload`` into ``--output_json`` (only when the parent pre-created it)."""
    if args.output_json and os.path.exists(args.output_json):
        with open(args.output_json) as f:
            data = json.load(f)
        data.update(payload)
        safe_data = coerce_nonfinite_to_none(data)
        with open(args.output_json, "w") as f:
            json.dump(safe_data, f, indent=4)
        print(f"Updated {args.output_json} with score.")


print(f"Calculating score for [{args.mode.upper()}] mode: {fname}")
print(f"  s_max (global, from anchor map) = {s_max:.4f}")

# The metric's arithmetic receives exactly the keyword arguments score_vector
# received before Step 06; the handle only puts the acceptance contract in
# front of them (design §5, §9).
outcome = metric.evaluate(
    {args.file_index: full_path},
    data_dir=args.data_dir,
    sample_set=sample_set,
    anchor_map=anchors,
    s_max=s_max,
    denoised_filename_fn=_denoised_fn,
    raw_data_dir=args.raw_data_dir,
    parallel=args.parallel,
    num_workers=args.num_workers,
    legacy_mode=False,
    profile=dataset_profile,
)

if isinstance(outcome, NotScoreableResult):
    # A STRUCTURED refusal, not a scorer traceback: named on stderr (always
    # captured by the parent's error formatter), persisted into the output
    # JSON when one was given, and exit 1 — the same exit the pre-Step-06
    # "File not found" pre-check used, so the parent's classifier ("error")
    # and every caller's handling are unchanged (design §19 C3 §6).
    for failure in outcome.verdict.failures:
        print(
            f"Deliverable not scoreable [{outcome.verdict.contract_id}] "
            f"{failure.requirement}: {failure.detail}",
            file=sys.stderr,
        )
    _merge_output_json(
        {
            "denoising_score": None,
            "file_vector": None,
            "not_scoreable": outcome.model_dump(mode="json"),
        }
    )
    sys.exit(1)

file_vector, scalar = outcome.per_sample, outcome.scalar

print(f"\nFinal Denoising Score: {scalar:.4f}")

# ---------------------------------------------------------------------------
# Optional: merge into output JSON
# ---------------------------------------------------------------------------

# The merged keys are exactly the pre-Step-06 two. The child's payload is
# json-dumped into an LLM prompt by one caller path (the legacy skill route →
# reflector), and Step 06 changes no prompt (design §8): the metric's identity
# reaches the record through the tuner's own handle, not through this file.
_merge_output_json({"denoising_score": scalar, "file_vector": file_vector})
