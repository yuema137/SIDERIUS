#!/usr/bin/env python3
"""
compute_raw_baseline.py

Computes the denoising score on raw (undenoised) validation files under the
**Option B global-s_max convention** and saves one JSON per file index.

Per-file formula (same ruler as ``scoring_utils.score_vector`` and as the
ground-truth ceiling — global ``s_max`` from the anchor map):

    per_segment  = (snr_sg[i] / s_max_GLOBAL) · snr_squid_raw[i]
    score        = log_{5.27}(mean_i(per_segment) + 1e-10)

where ``snr_squid_raw`` is the raw CH1 SNR at the CH2 peak frequency
(i.e. no denoiser applied), computed via the Option B primitives
(``get_one_sec_psd`` upcasts to ``float64`` before ``np.fft.rfft``).

File index mapping:
  0 - 19  : fine scoring   (abra_validation_0000.h5 … 0019.h5, 200 segments)
  20 - 39 : coarse scoring (abra_validation_0020.h5 … 0039.h5, 20 segments
                            — every 10th segment; uses the same global s_max
                            so coarse scores are directly comparable to fine)

Output: ``{output_dir}/raw_baseline_score_file_{index:04d}.json``

Usage examples:
  # Compute all 40 files (skip already-done ones):
  python compute_raw_baseline.py

  # Compute only files 0 and 5:
  python compute_raw_baseline.py --indices 0 5

  # Re-compute file 3 even if it already exists:
  python compute_raw_baseline.py --indices 3 --override

  # Use parallel workers for speed:
  python compute_raw_baseline.py --parallel --num_workers 8
"""

import argparse
import concurrent.futures
import json
import math
import os
from datetime import datetime

import numpy as np
from tqdm import tqdm

from execute_tools.build_anchor_map import load_anchor_map
from execute_tools.dataset_config import NUM_FILES
from execute_tools.scoring_utils import coerce_nonfinite_to_none, process_segment

# ---------------------------------------------------------------------------
# Per-file score under the Option B global-s_max convention.
#
# Primitives (``get_one_sec_psd``, ``get_snr``) live in
# ``execute_tools.scoring_utils`` — same Option B path as ``score_vector``
# and the ground-truth ceiling. File-local ``amax(snr_sg)`` normalization
# has been removed: we divide by the global ``s_max`` from the anchor map
# so baseline and model scores share one ruler.
# See ``docs/align_denoising_score.md`` §4.1.
# ---------------------------------------------------------------------------

_FINE_SEGMENTS = 200
_COARSE_SEGMENTS = 20  # every 10th of a 200-segment file


def _calculate_score(
    data_dir: str,
    fname: str,
    s_max: float,
    coarse: bool,
    parallel: bool,
    num_workers: int,
) -> tuple[float, float, int]:
    """Global-s_max per-file score + aggregation primitives for the scalar.

        per_segment  = (snr_sg[i] / s_max_GLOBAL) · snr_squid[i]
        score        = log_{5.27}(mean_i(per_segment) + 1e-10)

    ``s_max`` is always the global value from ``segment_anchors.json`` —
    the same ruler that ``scoring_utils.score_vector`` uses for model
    evaluations and that ``compute_ground_truth._anchor_normalized_ceiling``
    uses for the theoretical ceiling. Baseline, model, and ceiling are
    therefore mutually comparable.

    Both fine (n=200) and coarse (n=20, every 10th segment) modes use the
    same ``s_max`` — a coarse run is a sparse sampling of the same
    physical signal, so it must be weighed on the same ruler as a fine run.

    The ``+ 1e-10`` offset places a soft log-space floor at
    ``log_{5.27}(1e-10) ≈ −13.854`` so a file with no signal renders as a
    finite floor value rather than ``-inf``. Negligible for any
    ``mean_linear ≫ 1e-10``. The legacy ``round(·, 2)`` quantization that
    used to live alongside the offset was removed by commit ``6c3f736``
    ("kill ghost scores") — it conflated distinct scores at the 0.01 grid
    and is intentionally not reinstated.

    Returns a 3-tuple ``(log_score, linear_sum, n_segments)`` where
    ``linear_sum = Σ_i per_segment[i]`` is the unrounded linear sum.
    The grand-mean scalar must be aggregated from the linear sums (not
    averaged from the per-file log scores) so that subset-scoped
    aggregation under trial-mode sampling is consistent — see Decision 13
    in ``docs/aggregated_score_table_awareness.md``.
    """
    n = _FINE_SEGMENTS if not coarse else _COARSE_SEGMENTS

    snr_squid = np.zeros(n)
    snr_sg = np.zeros(n)

    if parallel:
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as ex:
            tasks = [ex.submit(process_segment, i, data_dir, fname, coarse) for i in range(n)]
            for fut in tqdm(
                concurrent.futures.as_completed(tasks), total=n, desc=f"  scoring {fname}"
            ):
                i, s_sg, s_squid = fut.result()
                snr_sg[i] = s_sg
                snr_squid[i] = s_squid
    else:
        for i in tqdm(range(n), desc=f"  scoring {fname}"):
            _, s_sg, s_squid = process_segment(i, data_dir, fname, coarse)
            snr_sg[i] = s_sg
            snr_squid[i] = s_squid

    per_segment = (snr_sg / s_max) * snr_squid
    linear_sum = float(np.sum(per_segment))
    mean_linear = linear_sum / n
    if math.isfinite(mean_linear):
        log_score = float(math.log(max(mean_linear, 0.0) + 1e-10, 5.27))
    else:
        log_score = float("-inf")
    return log_score, linear_sum, n


# ---------------------------------------------------------------------------
# Anchor-normalized scalar (grand-mean over all fine segments).
#
# Symmetric with ``compute_ground_truth._anchor_normalized_ceiling``:
#
#     grand_mean  = Σ_f linear_sum[f]  /  Σ_f n_segments[f]
#     scalar      = log_{5.27}(grand_mean + 1e-10)
#
# The ``+ 1e-10`` offset matches the per-file convention so a fully collapsed
# run renders as the same soft floor (~−13.854) at every aggregation level
# instead of producing ``-inf`` here while per-file rows show finite floors.
#
# Only fine files (0-19) contribute — coarse files are a sparse sampling of
# the same physical signal and would bias the grand mean if mixed in. See
# Decision 13 in ``docs/aggregated_score_table_awareness.md``.
# ---------------------------------------------------------------------------

_FINE_INDICES = tuple(range(NUM_FILES))


def _maybe_write_anchor_normalized_scalar(
    output_dir: str,
    s_max: float,
    anchor_src: str,
) -> None:
    """Scan the 20 fine per-file JSONs and, if complete, write the scalar.

    Non-fatal: prints a warning and returns if any fine JSON is missing or
    lacks ``linear_sum`` / ``n_segments`` (e.g. a legacy JSON produced before
    Decision 13). The caller can re-run with ``--override`` to regenerate.
    """
    per_file: list[dict] = []
    missing: list[int] = []
    lossy: list[int] = []

    for idx in _FINE_INDICES:
        path = os.path.join(output_dir, f"raw_baseline_score_file_{idx:04d}.json")
        if not os.path.exists(path):
            missing.append(idx)
            continue
        with open(path) as f:
            payload = json.load(f)
        if "linear_sum" not in payload or "n_segments" not in payload:
            lossy.append(idx)
            continue
        per_file.append(payload)

    if missing or lossy:
        if missing:
            print(f"[SCALAR] skipping — missing fine indices: {missing}")
        if lossy:
            print(
                f"[SCALAR] skipping — indices without linear_sum/n_segments "
                f"(regenerate with --override): {lossy}"
            )
        return

    total_linear = sum(p["linear_sum"] for p in per_file)
    total_n = sum(p["n_segments"] for p in per_file)
    grand_mean = total_linear / total_n
    if math.isfinite(grand_mean):
        scalar = float(math.log(max(grand_mean, 0.0) + 1e-10, 5.27))
    else:
        scalar = float("-inf")

    # Per-file LINEAR means (mirror of ceiling_anchor_normalized.json.file_vector).
    file_vector_linear = [p["linear_sum"] / p["n_segments"] for p in per_file]

    out_path = os.path.join(output_dir, "scalar_anchor_normalized.json")
    result = {
        "scalar_score": scalar,
        "file_vector": file_vector_linear,
        "formula": "anchor_normalized_raw_baseline",
        "s_max": s_max,
        "num_files": len(per_file),
        "source": anchor_src,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(out_path, "w") as f:
        json.dump(coerce_nonfinite_to_none(result), f, indent=2)
    print(f"\n[SCALAR] anchor-normalized raw-baseline scalar = {scalar:.6f}")
    print(f"         -> {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Compute raw (undenoised) baseline denoising scores "
        "under the Option B global-s_max convention.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--data_dir",
        "-d",
        type=str,
        default=None,
        help="Directory containing abra_validation_*.h5 files. Default: TIDMAD_DATA_DIR.",
    )
    parser.add_argument(
        "--anchor_map",
        type=str,
        default=None,
        help="Path to segment_anchors.json (for global s_max). "
        "Default: {TIDMAD_DATA_DIR}/segment_anchors.json.",
    )
    parser.add_argument(
        "--output_dir",
        "-o",
        type=str,
        default=None,
        help="Directory to write per-file JSON results.",
    )
    parser.add_argument(
        "--indices",
        "-i",
        type=int,
        nargs="+",
        default=list(range(40)),
        help="File indices to process (default: 0-39).",
    )
    parser.add_argument(
        "--override",
        action="store_true",
        help="Recompute even if the output JSON already exists.",
    )
    parser.add_argument(
        "--parallel",
        "-p",
        action="store_true",
        help="Use parallel workers for the FFT scoring loop.",
    )
    parser.add_argument(
        "--num_workers",
        "-n",
        type=int,
        default=8,
        help="Number of parallel workers (used only with --parallel).",
    )
    args = parser.parse_args()

    if args.data_dir is None:
        from execute_tools.data_paths import TIDMAD_DATA_DIR

        args.data_dir = TIDMAD_DATA_DIR
    if args.anchor_map is None:
        from execute_tools.data_paths import TIDMAD_DATA_DIR

        args.anchor_map = os.path.join(TIDMAD_DATA_DIR, "segment_anchors.json")
    if args.output_dir is None:
        from execute_tools.data_paths import SIDERIUS_DATA_DIR

        args.output_dir = os.path.join(SIDERIUS_DATA_DIR, "raw_baseline")

    os.makedirs(args.output_dir, exist_ok=True)

    anchor_data = load_anchor_map(args.anchor_map)
    s_max = float(anchor_data["s_max"])

    print(f"\n{'=' * 60}")
    print("  compute_raw_baseline.py")
    print(f"  data_dir   : {args.data_dir}")
    print(f"  anchor_map : {args.anchor_map}")
    print(f"  s_max      : {s_max:.6g}  (global, from anchor map)")
    print(f"  output_dir : {args.output_dir}")
    print(f"  indices    : {args.indices}")
    print(f"  override   : {args.override}")
    print(f"{'=' * 60}\n")

    skipped = 0
    computed = 0
    errors = []

    for idx in args.indices:
        if idx < 0 or idx > 39:
            print(f"[WARN] Index {idx} out of range 0-39, skipping.")
            continue

        coarse = idx >= 20
        mode = "coarse" if coarse else "fine"
        fname = f"abra_validation_{idx:04d}.h5"
        out_path = os.path.join(args.output_dir, f"raw_baseline_score_file_{idx:04d}.json")

        if os.path.exists(out_path) and not args.override:
            print(
                f"[SKIP] index={idx:02d}  {out_path} already exists. Use --override to recompute."
            )
            skipped += 1
            continue

        fpath = os.path.join(args.data_dir, fname)
        if not os.path.exists(fpath):
            print(f"[ERROR] index={idx:02d}  data file not found: {fpath}")
            errors.append(idx)
            continue

        print(f"[COMPUTE] index={idx:02d}  mode={mode}  file={fname}")
        try:
            score, linear_sum, n_segments = _calculate_score(
                data_dir=args.data_dir,
                fname=fname,
                s_max=s_max,
                coarse=coarse,
                parallel=args.parallel,
                num_workers=args.num_workers,
            )
            result = {
                "file_index": idx,
                "score": score,
                "linear_sum": linear_sum,
                "n_segments": n_segments,
                "mode": mode,
                "data_file": fname,
                "s_max": s_max,
                "formula": "option_b_global_s_max",
                "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(out_path, "w") as f:
                json.dump(coerce_nonfinite_to_none(result), f, indent=2)
            print(f"  -> score={score:.6f}  saved to {out_path}")
            computed += 1
        except Exception as e:
            print(f"[ERROR] index={idx:02d}  {e}")
            errors.append(idx)

    print(f"\n{'=' * 60}")
    print(f"  Done.  computed={computed}  skipped={skipped}  errors={len(errors)}")
    if errors:
        print(f"  Failed indices: {errors}")
    print(f"{'=' * 60}\n")

    # --- Anchor-normalized scalar (fine files only) ---
    _maybe_write_anchor_normalized_scalar(
        output_dir=args.output_dir,
        s_max=s_max,
        anchor_src=os.path.basename(args.anchor_map),
    )


if __name__ == "__main__":
    main()
