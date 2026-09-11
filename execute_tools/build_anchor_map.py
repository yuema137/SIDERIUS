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
            "0": [snr_0, snr_1, ..., snr_199],    # file 0, segments 0-199
            "1": [snr_0, snr_1, ..., snr_199],    # file 1, segments 0-199
            ...
            "19": [snr_0, snr_1, ..., snr_199],   # file 19, segments 0-199
        }
    }

Usage:
    python execute_tools/build_anchor_map.py --data_dir /home/klz/Data/TIDMAD/
    python execute_tools/build_anchor_map.py --data_dir /home/klz/Data/TIDMAD/ --parallel -n 8
"""

import argparse
import concurrent.futures
import json
import os

from tqdm import tqdm

from core.layout import checkout_root, require_checkout
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
    anchors: dict[int, list[float]] = {i: [0.0] * SEGMENTS_PER_FILE for i in range(NUM_FILES)}

    # Build task list: (file_index, segment_index)
    tasks = [(fi, si) for fi in range(NUM_FILES) for si in range(SEGMENTS_PER_FILE)]
    total = len(tasks)

    if parallel:
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_compute_ch2_snr, fi, si, data_dir) for fi, si in tasks]
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


def default_anchor_map_path() -> str:
    """Absolute path to the committed reference anchor map.

    The anchor map is a fixed reference artifact uniquely determined by the
    TIDMAD dataset, committed at ``reference_data/segment_anchors.json``. The
    path is resolved from this module's package location (the repo root),
    independent of the caller's current working directory, so the committed
    artifact is used automatically regardless of where a process is launched.
    """
    return str(require_checkout(checkout_root()) / "reference_data" / "segment_anchors.json")


def resolve_anchor_map_path(explicit: str | None) -> str:
    """Resolve the anchor-map path to use.

    An explicit override (``--anchor_map``) always wins; otherwise fall back to
    the committed reference artifact (:func:`default_anchor_map_path`). This
    function never touches the filesystem — existence/validity is enforced by
    :func:`load_anchor_map` at read time so a bad path fails clearly.
    """
    return explicit if explicit is not None else default_anchor_map_path()


def load_anchor_map(path: str) -> dict:
    """
    Load a pre-computed anchor map from a JSON file.

    Returns the same dict structure as ``build_anchor_map()``, with
    ``"anchors"`` keys as strings (JSON constraint).

    Raises:
        FileNotFoundError: if ``path`` does not exist (clear message pointing at
            the committed reference artifact).
        ValueError: if the file is not valid JSON, or is valid JSON but missing
            the required ``"s_max"`` / ``"anchors"`` keys.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"segment anchor map not found at {path!r}. The committed reference "
            "artifact is reference_data/segment_anchors.json; pass --anchor_map "
            "to override with a different path."
        )
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"segment anchor map at {path!r} is malformed JSON: {e}") from e
    if not isinstance(data, dict) or "s_max" not in data or "anchors" not in data:
        found = sorted(data) if isinstance(data, dict) else type(data).__name__
        raise ValueError(
            f"segment anchor map at {path!r} is missing required keys "
            f"('s_max', 'anchors'); found {found}."
        )
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Pre-compute the segment anchor map for physics-anchored scoring.",
    )
    parser.add_argument(
        "--data_dir",
        "-d",
        type=str,
        default=None,
        help="Directory containing abra_validation_XXXX.h5 files.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output JSON path. Defaults to <data_dir>/segment_anchors.json.",
    )
    parser.add_argument(
        "-p",
        "--parallel",
        action="store_true",
        help="Use multiprocessing for speed.",
    )
    parser.add_argument(
        "-n",
        "--num_workers",
        type=int,
        default=8,
        help="Number of parallel workers.",
    )
    args = parser.parse_args()

    from execute_tools.data_paths import resolve_dataset_dir

    args.data_dir = resolve_dataset_dir(args.data_dir, purpose="anchor-map construction")

    output_path = args.output or os.path.join(args.data_dir, "segment_anchors.json")

    print(
        f"Scanning {NUM_FILES} files × {SEGMENTS_PER_FILE} segments = "
        f"{NUM_FILES * SEGMENTS_PER_FILE} total segments"
    )
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
