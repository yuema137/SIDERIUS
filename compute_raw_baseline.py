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
import gc
import json
import math
import os
from datetime import datetime

import h5py
import numpy as np
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Scoring functions (copied verbatim from denoising_score_single.py to avoid
# import side-effects; do NOT modify the originals)
# ---------------------------------------------------------------------------

def _get_one_sec_psd(file_path, files, ch, start=0):
    file_list = []
    if isinstance(files, list):
        file_list = [os.path.join(file_path, f) for f in files]
    elif files.endswith(".h5"):
        file_list = [os.path.join(file_path, files)]

    N = 10_000_000
    file_num   = start // 200
    start_idx  = N * (start % 200)

    with h5py.File(file_list[file_num], 'r') as h5f:
        key = 'channel0001' if ch == 1 else 'channel0002'
        data = h5f['timeseries'][key]['timeseries'][start_idx:start_idx + N]
        volt_range    = h5f['timeseries']['channel0001'].attrs['voltage_range_mV']
        sampling_freq = h5f['timeseries']['channel0001'].attrs['sampling_frequency']

        scaling   = np.float32(volt_range / (2 * 128.0))
        ts        = np.array(data, dtype=np.float32) * scaling
        dt        = 1.0 / sampling_freq
        psd_chunk = dt / N * (abs(np.fft.rfft(ts)) ** 2)[1:]
        freq_arr  = np.linspace(0, sampling_freq / 2, int(N / 2))

    del data, ts
    gc.collect()
    return freq_arr, psd_chunk


def _find_peak(pwr):
    peakdiff  = pwr[1:-1] - pwr[:-2] - pwr[2:]
    peak_idx  = int(np.where(peakdiff == np.amax(peakdiff))[0][0]) + 1
    return peak_idx


def _get_snr(freq, pwr, target=0):
    center_id   = _find_peak(pwr) if target == 0 else int(np.where(freq == target)[0][0])
    sig_range   = 1
    noise_range = 50
    signal = np.sum(pwr[center_id - sig_range : center_id + sig_range + 1])
    noise  = np.sum(pwr[center_id - noise_range : center_id + noise_range + 1]) - signal
    if noise <= 0:
        noise = 1e-5
    return [signal / noise, freq[center_id]]


def _process_iteration(i, path, file, coarse):
    start_index = i * 10 if coarse else i
    freq_sg,    psd_sg    = _get_one_sec_psd(path, file, ch=2, start=start_index)
    snr_sg,     center_f  = _get_snr(freq_sg, psd_sg)
    freq_squid, psd_squid = _get_one_sec_psd(path, file, ch=1, start=start_index)
    snr_squid             = _get_snr(freq_squid, psd_squid, center_f)[0]
    return i, snr_sg, snr_squid


def _calculate_score(data_dir, fname, coarse, parallel, num_workers):
    fpath = os.path.join(data_dir, fname)
    with h5py.File(fpath, 'r') as f:
        length = f['/timeseries/channel0001/timeseries'].shape[0]
    n = min(length // 10_000_000, 200)  # cap at 200: single-file addressing assumes start < 200
    if coarse:
        n = max(1, n // 10)

    snr_squid = np.zeros(n)
    snr_sg    = np.zeros(n)

    if parallel:
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as ex:
            tasks = [ex.submit(_process_iteration, i, data_dir, fname, coarse)
                     for i in range(n)]
            for fut in tqdm(concurrent.futures.as_completed(tasks), total=n,
                            desc=f"  scoring {fname}"):
                i, s_sg, s_squid = fut.result()
                snr_sg[i]    = s_sg
                snr_squid[i] = s_squid
    else:
        for i in tqdm(range(n), desc=f"  scoring {fname}"):
            _, s_sg, s_squid = _process_iteration(i, data_dir, fname, coarse)
            snr_sg[i]    = s_sg
            snr_squid[i] = s_squid

    max_sg = np.amax(snr_sg)
    snr_sg = snr_sg / (max_sg if max_sg != 0 else 1.0)
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
        "--data_dir", "-d", type=str, default="/home/klz/Data/TIDMAD/",
        help="Directory containing abra_validation_*.h5 files.",
    )
    parser.add_argument(
        "--output_dir", "-o", type=str,
        default="/home/klz/Data/SIDEREIS_DATA/raw_baseline",
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
