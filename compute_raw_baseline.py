#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_raw_baseline.py

Computes the denoising score on raw (undenoised) validation files and saves
one JSON result per file index. Run this once before starting the dashboard;
results are used as a reference baseline line in the score chart.

File index mapping:
  0 – 19  : fine scoring   (abra_validation_0000.h5 … abra_validation_0019.h5)
  20 – 39 : coarse scoring (abra_validation_0020.h5 … abra_validation_0039.h5,
                            using 1/10th of segments — same as --coarse flag)

Output: {output_dir}/raw_baseline_score_file_{index:04d}.json
        e.g.  raw_baseline/raw_baseline_score_file_0000.json

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

from execute_tools.scoring_utils import process_segment

# ---------------------------------------------------------------------------
# Per-file legacy score (byte-strict transcription of
# ``denoising_score_old.calculateBenchmark`` invoked on a single-file list).
#
# All PSD/SNR primitives live in ``execute_tools.scoring_utils`` — there is
# one definition shared by every scoring entry point. No private copies.
# See ``docs/align_denoising_score.md`` §4.1.
# ---------------------------------------------------------------------------

# Number of seconds (and hence 1-second segments) per TIDMAD validation file
# under the legacy LIST-input shortcut. Real ``abra_validation_*.h5`` files
# actually contain 201 seconds of data; legacy ``calculateBenchmark`` when
# called with a list of files uses ``n = 200 * len(file_list)`` and silently
# ignores the trailing second. Matching that behavior bit-for-bit requires
# the same fixed cap here — reading ``length // 10_000_000`` would yield
# 201 and run past the end of the 1-element file list.
_LEGACY_LIST_PATH_N = 200


def _calculate_score(data_dir, fname, coarse, parallel, num_workers):
    """Byte-strict legacy per-file score.

    Mirrors ``denoising_score_old.calculateBenchmark(path, [fname], args)``
    under its **list-input path**, which is how the legacy CLI is
    invoked:

        n = 200 * len(file_list)        # list-path shortcut
        if coarse:
            n = int(n / 10)
        snr_sg  = snr_sg / np.amax(snr_sg)
        score   = np.round(Σ snr_sg·snr_squid / n, 2) + 1e-10
        return math.log(score, 5.27)

    ``_calculate_score`` is always called on one file at a time from
    ``main()``, so ``len(file_list) = 1`` and ``n = 200``. No HDF5
    length read is needed; the 201-second trailing data is intentionally
    ignored to match legacy.
    """
    n = _LEGACY_LIST_PATH_N
    if coarse:
        n = int(n / 10)

    snr_squid = np.zeros(n)
    snr_sg    = np.zeros(n)

    if parallel:
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as ex:
            tasks = [ex.submit(process_segment, i, data_dir, fname, coarse)
                     for i in range(n)]
            for fut in tqdm(concurrent.futures.as_completed(tasks), total=n,
                            desc=f"  scoring {fname}"):
                i, s_sg, s_squid = fut.result()
                snr_sg[i]    = s_sg
                snr_squid[i] = s_squid
    else:
        for i in tqdm(range(n), desc=f"  scoring {fname}"):
            _, s_sg, s_squid = process_segment(i, data_dir, fname, coarse)
            snr_sg[i]    = s_sg
            snr_squid[i] = s_squid

    snr_sg = snr_sg / np.amax(snr_sg)
    score  = np.round(np.sum(np.multiply(snr_sg, snr_squid)) / snr_squid.size,
                      decimals=2) + 1e-10
    return float(math.log(score, 5.27))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compute raw (undenoised) baseline denoising scores.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--data_dir", "-d", type=str, default=None,
        help="Directory containing abra_validation_*.h5 files. Default: from tidmad_data_config.yaml.",
    )
    parser.add_argument(
        "--output_dir", "-o", type=str, default=None,
        help="Directory to write per-file JSON results.",
    )
    parser.add_argument(
        "--indices", "-i", type=int, nargs="+",
        default=list(range(40)),
        help="File indices to process (default: 0–39).",
    )
    parser.add_argument(
        "--override", action="store_true",
        help="Recompute even if the output JSON already exists.",
    )
    parser.add_argument(
        "--parallel", "-p", action="store_true",
        help="Use parallel workers for the FFT scoring loop.",
    )
    parser.add_argument(
        "--num_workers", "-n", type=int, default=8,
        help="Number of parallel workers (used only with --parallel).",
    )
    args = parser.parse_args()

    if args.data_dir is None:
        from execute_tools.data_paths import TIDMAD_DATA_DIR
        args.data_dir = TIDMAD_DATA_DIR
    if args.output_dir is None:
        from execute_tools.data_paths import SIDERIUS_DATA_DIR
        args.output_dir = os.path.join(SIDERIUS_DATA_DIR, "raw_baseline")

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  compute_raw_baseline.py")
    print(f"  data_dir   : {args.data_dir}")
    print(f"  output_dir : {args.output_dir}")
    print(f"  indices    : {args.indices}")
    print(f"  override   : {args.override}")
    print(f"{'='*60}\n")

    skipped = 0
    computed = 0
    errors = []

    for idx in args.indices:
        if idx < 0 or idx > 39:
            print(f"[WARN] Index {idx} out of range 0–39, skipping.")
            continue

        coarse = idx >= 20
        mode   = "coarse" if coarse else "fine"
        fname  = f"abra_validation_{idx:04d}.h5"
        out_path = os.path.join(args.output_dir,
                                f"raw_baseline_score_file_{idx:04d}.json")

        if os.path.exists(out_path) and not args.override:
            print(f"[SKIP] index={idx:02d}  {out_path} already exists."
                  f" Use --override to recompute.")
            skipped += 1
            continue

        fpath = os.path.join(args.data_dir, fname)
        if not os.path.exists(fpath):
            print(f"[ERROR] index={idx:02d}  data file not found: {fpath}")
            errors.append(idx)
            continue

        print(f"[COMPUTE] index={idx:02d}  mode={mode}  file={fname}")
        try:
            score = _calculate_score(
                args.data_dir, fname, coarse,
                args.parallel, args.num_workers,
            )
            result = {
                "file_index":   idx,
                "score":        score,
                "mode":         mode,
                "data_file":    fname,
                "computed_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(out_path, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  -> score={score:.6f}  saved to {out_path}")
            computed += 1
        except Exception as e:
            print(f"[ERROR] index={idx:02d}  {e}")
            errors.append(idx)

    print(f"\n{'='*60}")
    print(f"  Done.  computed={computed}  skipped={skipped}  errors={len(errors)}")
    if errors:
        print(f"  Failed indices: {errors}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
