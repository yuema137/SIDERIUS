"""
Per-file diversity + pearson scan across all 20 TIDMAD validation files.

Compares two reference denoised sets:
  1. FCNet paper reproduction (real learning) — from /tmp/fcnet_full_scan/
     plus files 10-14 from tidmad_reproduction/fcnet/official_10_15/
  2. Paper-spec wavenet baseline (collapse reference) — from
     diagnostic_baseline_pre_v17_baseline_trial/, exp_id 1784177030

Reports diversity (unique_int8, std_mv, mode_fraction) and per-file
pearson(CH1_denoised, CH2_target).

DIAGNOSTIC SCRIPT — do not commit.
"""

from __future__ import annotations

import math
from pathlib import Path

import h5py
import numpy as np
from scipy.stats import pearsonr

MV_PER_LSB: float = 40.0 / 128.0
PEEK_SAMPLES: int = 1_000_000

GROUND_TRUTH_DIR = Path("/home/klz/Data/TIDMAD/")
FCNET_NEW_DIR = Path("/tmp/fcnet_full_scan/")
FCNET_REPRO_DIR = Path(
    "/home/klz/Data/SIDEREIS_DATA/tidmad_reproduction/fcnet/official_10_15/inference/"
)
BASELINE_DIR = Path(
    "/home/klz/Data/SIDEREIS_DATA/wavenet/diagnostic_baseline_pre_v17_baseline_trial/"
)
BASELINE_EXP = "1784177030"


def _fcnet_path(file_index: int) -> Path:
    # Prefer newly-generated file (all 20). Fall back to tidmad_reproduction
    # for files 10-14 if the new scan skipped them.
    new = FCNET_NEW_DIR / f"abra_validation_denoised_fcnet_{file_index:04d}.h5"
    if new.exists():
        return new
    return FCNET_REPRO_DIR / f"abra_validation_denoised_fcnet_{file_index:04d}.h5"


def _baseline_path(file_index: int) -> Path:
    return BASELINE_DIR / (
        f"abra_validation_denoised_wavenet_baseline_wavenet_baseline_wavenet_"
        f"{BASELINE_EXP}_{file_index:04d}.h5"
    )


def _target_path(file_index: int) -> Path:
    return GROUND_TRUTH_DIR / f"abra_validation_{file_index:04d}.h5"


def _read_channel(path: Path, channel: str, n: int) -> np.ndarray:
    with h5py.File(str(path), "r") as f:
        return np.asarray(f["timeseries"][channel]["timeseries"][:n])


def scan_denoised(path: Path) -> dict:
    arr = _read_channel(path, "channel0001", PEEK_SAMPLES)
    counts = np.bincount(arr.astype(np.int64) + 128, minlength=256)
    return {
        "unique_int8": len(np.unique(arr)),
        "std_mv": float(np.std(arr.astype(np.float64)) * MV_PER_LSB),
        "mode_fraction": float(counts.max() / len(arr)),
        "_arr": arr,
    }


def compute_pearson(denoised_arr: np.ndarray, target_arr: np.ndarray) -> float:
    n = min(len(denoised_arr), len(target_arr))
    d = denoised_arr[:n].astype(np.float64) * MV_PER_LSB
    t = target_arr[:n].astype(np.float64) * MV_PER_LSB
    if np.std(d) < 1e-12 or np.std(t) < 1e-12:
        return float("nan")
    r, _ = pearsonr(d, t)
    return float(r) if np.isfinite(r) else float("nan")


def _fmt(x, w: int = 8):
    if isinstance(x, float):
        if math.isnan(x):
            return "  nan".rjust(w)
        return f"{x:{w}.4f}"
    return f"{x:{w}d}"


def main() -> None:
    print("=" * 130)
    print(
        f"{'':6}{'target_std_mv':>14} | {'FCNet (real learning)':^54} | {'Paper-spec baseline (collapse)':^54}"
    )
    print(
        f"{'file':>6}{'':14} | "
        f"{'uniq':>6} {'std_mv':>10} {'mode%':>8} {'pearson':>10}   | "
        f"{'uniq':>6} {'std_mv':>10} {'mode%':>8} {'pearson':>10}"
    )
    print("-" * 130)

    fcnet_rows: dict[int, dict] = {}
    baseline_rows: dict[int, dict] = {}
    target_std_row: dict[int, float] = {}

    for i in range(20):
        tgt_path = _target_path(i)
        if not tgt_path.exists():
            print(f"{i:>6}  MISSING target file {tgt_path}")
            continue
        target = _read_channel(tgt_path, "channel0002", PEEK_SAMPLES)
        target_std = float(np.std(target.astype(np.float64)) * MV_PER_LSB)
        target_std_row[i] = target_std

        # FCNet
        fp = _fcnet_path(i)
        if fp.exists():
            f_stats = scan_denoised(fp)
            f_stats["pearson"] = compute_pearson(f_stats["_arr"], target)
            fcnet_rows[i] = f_stats
            f_cells = (
                f"{f_stats['unique_int8']:>6d} "
                f"{f_stats['std_mv']:>10.4f} "
                f"{100 * f_stats['mode_fraction']:>7.2f}% "
                f"{_fmt(f_stats['pearson'], 10)}   "
            )
        else:
            f_cells = f"{'MISSING':^42}   "

        # Baseline
        bp = _baseline_path(i)
        if bp.exists():
            b_stats = scan_denoised(bp)
            b_stats["pearson"] = compute_pearson(b_stats["_arr"], target)
            baseline_rows[i] = b_stats
            b_cells = (
                f"{b_stats['unique_int8']:>6d} "
                f"{b_stats['std_mv']:>10.4f} "
                f"{100 * b_stats['mode_fraction']:>7.2f}% "
                f"{_fmt(b_stats['pearson'], 10)}"
            )
        else:
            b_cells = f"{'MISSING':^42}"

        print(f"{i:>6}  {target_std:>12.4e}  | {f_cells} | {b_cells}")

    # Summary stats
    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)

    def _stats(label, values):
        v = [x for x in values if x == x]
        if not v:
            print(f"  {label:30s}: n/a")
            return
        print(
            f"  {label:30s}: "
            f"min={min(v):.4f}  median={float(np.median(v)):.4f}  "
            f"max={max(v):.4f}  mean={float(np.mean(v)):.4f}"
        )

    fcnet_uniq = [r["unique_int8"] for r in fcnet_rows.values()]
    fcnet_std = [r["std_mv"] for r in fcnet_rows.values()]
    fcnet_mode = [r["mode_fraction"] for r in fcnet_rows.values()]
    fcnet_pearson = [r["pearson"] for r in fcnet_rows.values()]

    base_uniq = [r["unique_int8"] for r in baseline_rows.values()]
    base_std = [r["std_mv"] for r in baseline_rows.values()]
    base_mode = [r["mode_fraction"] for r in baseline_rows.values()]
    base_pearson = [r["pearson"] for r in baseline_rows.values()]

    print(f"\nFCNet (n={len(fcnet_rows)}):")
    _stats("unique_int8", fcnet_uniq)
    _stats("std_mv", fcnet_std)
    _stats("mode_fraction", fcnet_mode)
    _stats("pearson", fcnet_pearson)

    print(f"\nBaseline (n={len(baseline_rows)}):")
    _stats("unique_int8", base_uniq)
    _stats("std_mv", base_std)
    _stats("mode_fraction", base_mode)
    _stats("pearson", base_pearson)

    # Explicit files 0-3 spotlight
    print("\nFiles 0-3 spotlight (low-signal region):")
    for i in [0, 1, 2, 3]:
        if i in fcnet_rows and i in baseline_rows:
            fr, br = fcnet_rows[i], baseline_rows[i]
            print(
                f"  file {i}: target_std={target_std_row.get(i, float('nan')):.3e} mV | "
                f"FCNet uniq={fr['unique_int8']:3d} std={fr['std_mv']:.3e} pearson={_fmt(fr['pearson'], 8)} | "
                f"Baseline uniq={br['unique_int8']:3d} std={br['std_mv']:.3e} pearson={_fmt(br['pearson'], 8)}"
            )

    # Threshold gap analysis
    print("\nThreshold gap analysis:")
    if fcnet_uniq and base_uniq:
        print(
            f"  FCNet min unique_int8: {min(fcnet_uniq)}   vs   Baseline max unique_int8: {max(base_uniq)}"
        )
        gap = min(fcnet_uniq) - max(base_uniq)
        print(f"  Gap: {gap} unique values ({min(fcnet_uniq) / max(base_uniq):.1f}× ratio)")
    if fcnet_std and base_std:
        print(
            f"  FCNet min std_mv:      {min(fcnet_std):.4f}   vs   Baseline max std_mv: {max(base_std):.4f}"
        )
        print(f"  Ratio: {min(fcnet_std) / max(base_std):.1f}× headroom")


if __name__ == "__main__":
    main()
