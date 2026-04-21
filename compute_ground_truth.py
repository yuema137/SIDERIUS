#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_ground_truth.py

Computes the theoretical ground-truth (ceiling) denoising score for the 20
TIDMAD validation files — i.e., the score a perfect denoiser (output == CH2)
would achieve. Produces two outputs:

1. Per-file scores under the LEGACY file-local formula (one JSON per file,
   format mirror of ``raw_baseline/raw_baseline_score_file_XXXX.json``).
   Use these as the dashboard per-file ceiling line, and for direct
   comparison against raw_baseline.

2. A single scalar ceiling under the ANCHOR-NORMALIZED formula (same formula
   used by ``execute_tools.scoring_utils.score_vector``, i.e. the scoring
   pipeline the LLM-driven tuner optimizes).

Both are computed directly from ``segment_anchors.json``: no HDF5 reads are
required because the anchor map already stores the per-segment CH2 SNRs we
would otherwise derive from CH2 PSDs. Runs in milliseconds.

Caveat: the anchor map is produced with scipy.fft; ``compute_raw_baseline.py``
uses numpy.fft. Numerical differences are <1e-5 relative, but if you need
bit-exact parity with raw_baseline, re-derive the CH2 SNRs from HDF5 using
the same code path as raw_baseline.

Output files:
  {output_dir}/ground_truth_score_file_{index:04d}.json     (legacy per-file)
  {output_dir}/ceiling_anchor_normalized.json               (scalar ceiling)

Usage:
  # Compute everything (skip already-done per-file JSONs):
  python compute_ground_truth.py

  # Point at a specific anchor map:
  python compute_ground_truth.py --anchor_map /path/to/segment_anchors.json

  # Force recompute:
  python compute_ground_truth.py --override
"""

import argparse
import json
import math
import os
from datetime import datetime

# ---------------------------------------------------------------------------
# Core formulas
# ---------------------------------------------------------------------------

def _legacy_per_file_ceiling(anchors_f: list[float]) -> float:
    """Legacy file-local score with denoiser output == CH2 (so snr_squid
    identically equals snr_sg). Mirrors ``compute_raw_baseline._calculate_score``:

        max_sg   = max(snr_sg)                                  # per-file max
        weights  = snr_sg / max_sg                              # ∈ [0, 1]
        score    = mean_s(weights * snr_squid)                  # = mean(snr_sg²) / max_sg
        score    = round(score, 2) + 1e-10                      # matches raw_baseline exactly
        return log_{5.27}(score)
    """
    n = len(anchors_f)
    max_sg = max(anchors_f) if max(anchors_f) != 0 else 1.0
    raw = sum(v * v for v in anchors_f) / (n * max_sg)
    score = round(raw, 2) + 1e-10
    return float(math.log(score, 5.27))


def _anchor_normalized_ceiling(
    anchors: dict[str, list[float]], s_max: float
) -> tuple[list[float], float]:
    """Anchor-normalized ceiling with denoiser output == CH2.

    Per-segment:   weighted_snr[f,i] = anchor[f,i]² / s_max
    Per-file:      file_vector[f]    = mean_i(weighted_snr[f,i])
    Grand mean:    grand             = Σ_{f,i} weighted_snr  /  Σ_f |S_f|
    Scalar:        score             = log_{5.27}(round(grand, 2) + 1e-10)

    Same aggregation as ``scoring_utils.score_vector`` (grand mean + TIDMAD
    round); the only change is that snr_squid is replaced by anchor (the
    perfect-denoiser substitution). Using the grand mean makes the scalar
    legacy-compatible regardless of whether every file has the same
    segment count; when ``|S_f|`` is uniform (the typical 200-per-file
    anchor map) it equals ``mean_f(file_vector)``.

    See ``docs/align_denoising_score.md`` §C.2.

    Returns:
        (file_vector, scalar_score)
    """
    file_vector: list[float] = []
    total_weighted = 0.0
    total_count = 0
    for f in sorted(anchors, key=int):
        a = anchors[f]
        file_sum = sum(v * v for v in a) / s_max
        file_vector.append(file_sum / len(a))
        total_weighted += file_sum
        total_count += len(a)
    grand_mean = total_weighted / total_count
    # TIDMAD round: legacy applies ``np.round(·, 2) + 1e-10`` before log.
    scalar = math.log(round(grand_mean, 2) + 1e-10, 5.27)
    return file_vector, float(scalar)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compute theoretical ground-truth (perfect-denoiser) "
                    "scores from an anchor map.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--anchor_map", "-a", type=str, default=None,
        help="Path to segment_anchors.json. Default: "
             "{TIDMAD_DATA_DIR}/segment_anchors.json.",
    )
    parser.add_argument(
        "--output_dir", "-o", type=str, default=None,
        help="Directory to write ground-truth JSONs. "
             "Default: {SIDERIUS_DATA_DIR}/ground_truth.",
    )
    parser.add_argument(
        "--override", action="store_true",
        help="Recompute even if output JSONs already exist.",
    )
    args = parser.parse_args()

    if args.anchor_map is None:
        from execute_tools.data_paths import TIDMAD_DATA_DIR
        args.anchor_map = os.path.join(TIDMAD_DATA_DIR, "segment_anchors.json")
    if args.output_dir is None:
        from execute_tools.data_paths import SIDERIUS_DATA_DIR
        args.output_dir = os.path.join(SIDERIUS_DATA_DIR, "ground_truth")

    if not os.path.exists(args.anchor_map):
        raise FileNotFoundError(f"Anchor map not found: {args.anchor_map}")
    os.makedirs(args.output_dir, exist_ok=True)

    with open(args.anchor_map, "r") as f:
        am = json.load(f)
    anchors: dict[str, list[float]] = am["anchors"]
    s_max: float = am["s_max"]
    num_files: int = am.get("num_files", len(anchors))

    print(f"\n{'='*60}")
    print(f"  compute_ground_truth.py")
    print(f"  anchor_map : {args.anchor_map}")
    print(f"  output_dir : {args.output_dir}")
    print(f"  num_files  : {num_files}")
    print(f"  s_max      : {s_max:.6g}")
    print(f"  override   : {args.override}")
    print(f"{'='*60}\n")

    # --- 1. Per-file legacy ceiling ---
    computed = 0
    skipped = 0
    for f_str in sorted(anchors, key=int):
        f_idx = int(f_str)
        out_path = os.path.join(
            args.output_dir, f"ground_truth_score_file_{f_idx:04d}.json"
        )
        if os.path.exists(out_path) and not args.override:
            print(f"[SKIP] index={f_idx:02d}  {out_path} already exists.")
            skipped += 1
            continue

        score = _legacy_per_file_ceiling(anchors[f_str])
        result = {
            "file_index":  f_idx,
            "score":       score,
            "mode":        "fine",
            "formula":     "legacy_file_local_ceiling",
            "source":      os.path.basename(args.anchor_map),
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[COMPUTE] index={f_idx:02d}  score={score:.6f}  -> {out_path}")
        computed += 1

    # --- 2. Anchor-normalized scalar ceiling ---
    fv, scalar = _anchor_normalized_ceiling(anchors, s_max)
    scalar_path = os.path.join(args.output_dir, "ceiling_anchor_normalized.json")
    scalar_result = {
        "scalar_score":     scalar,
        "file_vector":      fv,
        "formula":          "anchor_normalized_ceiling",
        "s_max":            s_max,
        "num_files":        num_files,
        "source":           os.path.basename(args.anchor_map),
        "computed_at":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(scalar_path, "w") as f:
        json.dump(scalar_result, f, indent=2)
    print(f"\n[COMPUTE] anchor-normalized scalar ceiling = {scalar:.6f}")
    print(f"          -> {scalar_path}")

    print(f"\n{'='*60}")
    print(f"  Done.  per-file computed={computed}  skipped={skipped}")
    print(f"         scalar ceiling (anchor-normalized) = {scalar:.4f}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
