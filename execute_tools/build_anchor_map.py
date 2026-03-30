"""
Pre-compute the Segment Anchor Map for physics-anchored scoring.

Scans all 20 raw validation files (CH2 ground truth only), computes
per-segment SNR, and stores the results as a JSON file. This is a
one-time operation — the output is reused by all subsequent scoring runs.

Output format (segment_anchors.json):
    {
        "s_max": <float>,               # global max SNR across all segments
        "segments_per_file": 200,
        "num_files": 20,
        "anchors": {
            "0": [snr_0, snr_1, ..., snr_199],    # file 0, segments 0–199
            "1": [snr_0, snr_1, ..., snr_199],    # file 1, segments 0–199
            ...
            "19": [snr_0, snr_1, ..., snr_199],   # file 19, segments 0–199
        }
    }

Usage:
    python execute_tools/build_anchor_map.py --data_dir /home/klz/Data/TIDMAD/
    python execute_tools/build_anchor_map.py --data_dir /home/klz/Data/TIDMAD/ --parallel -n 8
"""

import argparse
import json
import os
import sys
import concurrent.futures

import numpy as np
from tqdm import tqdm

# Add project root to path so we can import scoring_utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execute_tools.scoring_utils import (
    NUM_FILES,
    SEGMENTS_PER_FILE,
    get_one_sec_psd,
    get_snr,
)


def _compute_ch2_snr(
    file_index: int,
    segment_index: int,
    data_dir: str,
) -> tuple[int, int, float]:
    """
    Compute CH2 (ground truth) SNR for a single segment.

    Returns:
        (file_index, segment_index, snr_ch2)
    """
    fname = f"abra_validation_{file_index:04d}.h5"
    freq, psd = get_one_sec_psd(data_dir, fname, ch=2, start=segment_index)
    snr, _ = get_snr(freq, psd)
    return file_index, segment_index, snr


def build_anchor_map(
    data_dir: str,
    parallel: bool = False,
    num_workers: int = 8,
) -> dict:
    """
    Scan all 20 validation files and compute per-segment CH2 SNR.

    Args:
        data_dir:    Directory containing ``abra_validation_XXXX.h5`` files.
        parallel:    Use multiprocessing for speed.
        num_workers: Number of parallel workers (only if ``parallel=True``).

    Returns:
        Dict with keys ``"s_max"``, ``"segments_per_file"``, ``"num_files"``,
        and ``"anchors"`` (file_index → list of 200 SNR floats).
    """
    # Initialize: 20 files × 200 segments
    anchors: dict[int, list[float]] = {
        i: [0.0] * SEGMENTS_PER_FILE for i in range(NUM_FILES)
    }

    # Build task list: (file_index, segment_index)
    tasks = [
        (fi, si)
        for fi in range(NUM_FILES)
        for si in range(SEGMENTS_PER_FILE)
    ]
    total = len(tasks)

    if parallel:
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(_compute_ch2_snr, fi, si, data_dir)
                for fi, si in tasks
            ]
            for future in tqdm(
                concurrent.futures.as_completed(futures),
                total=total,
                desc="Building anchor map",
            ):
                fi, si, snr = future.result()
                anchors[fi][si] = snr
    else:
        for fi, si in tqdm(tasks, desc="Building anchor map"):
            _, _, snr = _compute_ch2_snr(fi, si, data_dir)
            anchors[fi][si] = snr

    # Compute global max
    s_max = max(max(segs) for segs in anchors.values())

    return {
        "s_max": s_max,
        "segments_per_file": SEGMENTS_PER_FILE,
        "num_files": NUM_FILES,
        "anchors": {str(k): v for k, v in anchors.items()},
    }


def load_anchor_map(path: str) -> dict:
    """
    Load a pre-computed anchor map from a JSON file.

    Returns the same dict structure as ``build_anchor_map()``, with
    ``"anchors"`` keys as strings (JSON constraint).
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Pre-compute the segment anchor map for physics-anchored scoring.",
    )
    parser.add_argument(
        "--data_dir", "-d", type=str, default="/home/klz/Data/TIDMAD/",
        help="Directory containing abra_validation_XXXX.h5 files.",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output JSON path. Defaults to <data_dir>/segment_anchors.json.",
    )
    parser.add_argument(
        "-p", "--parallel", action="store_true",
        help="Use multiprocessing for speed.",
    )
    parser.add_argument(
        "-n", "--num_workers", type=int, default=8,
        help="Number of parallel workers.",
    )
    args = parser.parse_args()

    output_path = args.output or os.path.join(args.data_dir, "segment_anchors.json")

    print(f"Scanning {NUM_FILES} files × {SEGMENTS_PER_FILE} segments = "
          f"{NUM_FILES * SEGMENTS_PER_FILE} total segments")
    print(f"Data dir: {args.data_dir}")
    print(f"Output:   {output_path}")
    print(f"Parallel: {args.parallel} (workers: {args.num_workers})")
    print()

    anchor_map = build_anchor_map(
        data_dir=args.data_dir,
        parallel=args.parallel,
        num_workers=args.num_workers,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(anchor_map, f, indent=2)

    print(f"\nAnchor map saved to {output_path}")
    print(f"S_max (global peak CH2 SNR): {anchor_map['s_max']:.6f}")


if __name__ == "__main__":
    main()
