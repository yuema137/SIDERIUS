#!/usr/bin/env python3
"""
compute_ground_truth.py

Computes the theoretical ground-truth (ceiling) denoising score for the 20
fine TIDMAD validation files under the **Option B global-s_max convention**
— i.e., the score a perfect denoiser (output == CH2) would achieve on the
same ruler used by ``scoring_utils.score_vector`` and by
``compute_raw_baseline.py``.

Perfect-denoiser substitution: the denoised CH1 equals CH2, so
``snr_squid[f][i] == snr_sg[f][i] == anchor[f][i]``. The per-file and
grand-mean formulas collapse to anchor-only expressions:

    per_segment      = anchor[f][i]² / s_max_GLOBAL
    per_file_linear  = mean_i(per_segment)
    per_file_score   = log_{5.27}(per_file_linear + 1e-10)

    grand_mean       = ( Σ_{f,i} per_segment ) / ( Σ_f |S_f| )
    scalar_score     = log_{5.27}(grand_mean + 1e-10)

Both are read directly from ``segment_anchors.json`` — no HDF5 reads, runs
in milliseconds.

Output files:
  {output_dir}/ground_truth_score_file_{index:04d}.json     (per-file ceiling)
  {output_dir}/ceiling_anchor_normalized.json               (scalar ceiling)

Per-file JSON schema mirrors ``raw_baseline_score_file_XXXX.json`` so the
dashboard and any downstream consumer can load baseline and ceiling the
same way.

Usage:
  # Compute everything (skip already-done per-file JSONs):
  python scripts/compute_ground_truth.py

  # Point at a specific anchor map:
  python scripts/compute_ground_truth.py --anchor_map /path/to/segment_anchors.json

  # Force recompute:
  python scripts/compute_ground_truth.py --override
"""

import argparse
import json
import math
import os
from datetime import datetime

from execute_tools.scoring_utils import coerce_nonfinite_to_none

# ---------------------------------------------------------------------------
# Core formulas — all use the global s_max from the anchor map.
# ---------------------------------------------------------------------------


def _global_per_file_ceiling(anchors_f: list[float], s_max: float) -> tuple[float, float, int]:
    """Perfect-denoiser per-file ceiling under the global-s_max ruler.

        per_segment     = anchor[i]² / s_max_GLOBAL
        linear_sum      = Σ_i per_segment                   (unrounded)
        per_file_linear = linear_sum / n
        log_score       = log_{5.27}(per_file_linear + 1e-10)

    Same ruler as ``compute_raw_baseline._calculate_score`` and as
    ``scoring_utils.score_vector`` (``legacy_mode=False``), so baseline,
    ceiling, and model scores are mutually comparable.

    The ``+ 1e-10`` offset places a soft log-space floor at
    ``log_{5.27}(1e-10) ≈ −13.854`` for files with no signal. Negligible
    for any ``per_file_linear ≫ 1e-10``. The legacy ``round(·, 2)``
    quantization that used to live alongside the offset was removed by
    commit ``6c3f736`` ("kill ghost scores") and is intentionally not
    reinstated.

    Returns a 3-tuple ``(log_score, linear_sum, n_segments)``. The
    unrounded ``linear_sum`` + ``n_segments`` are required by
    subset-aware aggregation in
    ``execute_tools.scoring_helpers.build_score_table`` (see Decision 14
    in ``docs/aggregated_score_table_awareness.md``).

    See ``docs/align_denoising_score.md`` §4.1.
    """
    n = len(anchors_f)
    linear_sum = sum(v * v for v in anchors_f) / s_max
    per_file_linear = linear_sum / n
    if math.isfinite(per_file_linear):
        log_score = float(math.log(max(per_file_linear, 0.0) + 1e-10, 5.27))
    else:
        log_score = float("-inf")
    return log_score, float(linear_sum), n


def _anchor_normalized_ceiling(
    anchors: dict[str, list[float]], s_max: float
) -> tuple[list[float], float]:
    """Grand-mean scalar ceiling under the global-s_max ruler.

    Per-segment:   per_segment[f,i] = anchor[f,i]² / s_max
    Per-file:      file_vector[f]   = mean_i(per_segment[f,i])
    Grand mean:    grand            = Σ_{f,i} per_segment  /  Σ_f |S_f|
    Scalar:        score            = log_{5.27}(grand + 1e-10)

    Same aggregation as ``scoring_utils.score_vector`` (grand mean over
    log_{5.27}); the only change is that ``snr_squid`` is replaced by
    ``anchor`` (the perfect-denoiser substitution). Using the grand mean
    makes the scalar legacy-compatible regardless of whether every file has
    the same segment count; when ``|S_f|`` is uniform (the typical 200-per-
    file anchor map) it equals ``mean_f(file_vector)``.

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
    if math.isfinite(grand_mean):
        scalar = math.log(max(grand_mean, 0.0) + 1e-10, 5.27)
    else:
        scalar = float("-inf")
    return file_vector, float(scalar)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Compute theoretical ground-truth (perfect-denoiser) "
        "scores under the Option B global-s_max convention.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--anchor_map",
        "-a",
        type=str,
        default=None,
        help="Path to segment_anchors.json. Default: {TIDMAD_DATA_DIR}/segment_anchors.json.",
    )
    parser.add_argument(
        "--output_dir",
        "-o",
        type=str,
        default=None,
        help="Directory to write ground-truth JSONs. Default: {SIDERIUS_DATA_DIR}/ground_truth.",
    )
    parser.add_argument(
        "--override",
        action="store_true",
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

    with open(args.anchor_map) as f:
        am = json.load(f)
    anchors: dict[str, list[float]] = am["anchors"]
    s_max: float = am["s_max"]
    num_files: int = am.get("num_files", len(anchors))

    print(f"\n{'=' * 60}")
    print("  compute_ground_truth.py")
    print(f"  anchor_map : {args.anchor_map}")
    print(f"  output_dir : {args.output_dir}")
    print(f"  num_files  : {num_files}")
    print(f"  s_max      : {s_max:.6g}  (global, from anchor map)")
    print(f"  override   : {args.override}")
    print(f"{'=' * 60}\n")

    # --- 1. Per-file ceiling under global s_max ---
    computed = 0
    skipped = 0
    for f_str in sorted(anchors, key=int):
        f_idx = int(f_str)
        out_path = os.path.join(args.output_dir, f"ground_truth_score_file_{f_idx:04d}.json")
        if os.path.exists(out_path) and not args.override:
            print(f"[SKIP] index={f_idx:02d}  {out_path} already exists.")
            skipped += 1
            continue

        score, linear_sum, n_segments = _global_per_file_ceiling(anchors[f_str], s_max)
        result = {
            "file_index": f_idx,
            "score": score,
            "linear_sum": linear_sum,
            "n_segments": n_segments,
            "mode": "fine",
            "s_max": s_max,
            "formula": "option_b_global_s_max_ceiling",
            "source": os.path.basename(args.anchor_map),
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(out_path, "w") as f:
            json.dump(coerce_nonfinite_to_none(result), f, indent=2)
        print(f"[COMPUTE] index={f_idx:02d}  score={score:.6f}  -> {out_path}")
        computed += 1

    # --- 2. Anchor-normalized scalar ceiling ---
    fv, scalar = _anchor_normalized_ceiling(anchors, s_max)
    scalar_path = os.path.join(args.output_dir, "ceiling_anchor_normalized.json")
    scalar_result = {
        "scalar_score": scalar,
        "file_vector": fv,
        "formula": "anchor_normalized_ceiling",
        "s_max": s_max,
        "num_files": num_files,
        "source": os.path.basename(args.anchor_map),
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(scalar_path, "w") as f:
        json.dump(coerce_nonfinite_to_none(scalar_result), f, indent=2)
    print(f"\n[COMPUTE] anchor-normalized scalar ceiling = {scalar:.6f}")
    print(f"          -> {scalar_path}")

    print(f"\n{'=' * 60}")
    print(f"  Done.  per-file computed={computed}  skipped={skipped}")
    print(f"         scalar ceiling (global s_max) = {scalar:.4f}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
