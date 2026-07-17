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
    "Default: {TIDMAD_DATA_DIR}/segment_anchors.json.",
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

from execute_tools.data_paths import TIDMAD_DATA_DIR  # noqa: E402

if args.data_dir is None:
    args.data_dir = TIDMAD_DATA_DIR
if args.raw_data_dir is None:
    args.raw_data_dir = TIDMAD_DATA_DIR
if args.anchor_map is None:
    args.anchor_map = os.path.join(TIDMAD_DATA_DIR, "segment_anchors.json")

# ---------------------------------------------------------------------------
# Filename construction (preserved from legacy for sandbox compatibility)
# ---------------------------------------------------------------------------

idx_str = f"{args.file_index:04d}"
if args.denoising_model == "none":
    fname = f"abra_validation_{idx_str}.h5"
elif args.mode == "fix":
    fname = f"abra_validation_denoised_{args.denoising_model}_{idx_str}.h5"
else:  # agent
    fname = (
        f"abra_validation_denoised_{args.denoising_model}"
        f"_{args.run_name}_{args.exp_id}_{idx_str}.h5"
    )

full_path = os.path.join(args.data_dir, fname)

if not os.path.exists(full_path):
    print(f"Error: File not found at {full_path}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Score via score_vector
# ---------------------------------------------------------------------------

from execute_tools.build_anchor_map import load_anchor_map  # noqa: E402
from execute_tools.dataset_config import SEGMENTS_PER_FILE  # noqa: E402
from execute_tools.scoring_utils import (  # noqa: E402
    coerce_nonfinite_to_none,
    score_vector,
)

anchor_data = load_anchor_map(args.anchor_map)
s_max = float(anchor_data["s_max"])
anchors = anchor_data["anchors"]

sample_set = {args.file_index: list(range(SEGMENTS_PER_FILE))}


def _denoised_fn(_fi: int) -> str:
    # score_vector calls this per file-index; we only have one file here.
    return fname


print(f"Calculating score for [{args.mode.upper()}] mode: {fname}")
print(f"  s_max (global, from anchor map) = {s_max:.4f}")

file_vector, scalar = score_vector(
    data_dir=args.data_dir,
    sample_set=sample_set,
    anchor_map=anchors,
    s_max=s_max,
    denoised_filename_fn=_denoised_fn,
    raw_data_dir=args.raw_data_dir,
    parallel=args.parallel,
    num_workers=args.num_workers,
    legacy_mode=False,
)

print(f"\nFinal Denoising Score: {scalar:.4f}")

# ---------------------------------------------------------------------------
# Optional: merge into output JSON
# ---------------------------------------------------------------------------

if args.output_json and os.path.exists(args.output_json):
    with open(args.output_json) as f:
        data = json.load(f)
    data["denoising_score"] = scalar
    data["file_vector"] = file_vector
    safe_data = coerce_nonfinite_to_none(data)
    with open(args.output_json, "w") as f:
        json.dump(safe_data, f, indent=4)
    print(f"Updated {args.output_json} with score.")
