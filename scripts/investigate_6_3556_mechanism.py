"""
Empirical investigation: does noise <= 1e-10 guard catch the 6.3556 phantom?

Simulates "mostly-constant with tiny variation" int8 model outputs at several
perturbation rates, runs them through the actual scoring pipeline's PSD and
get_snr machinery, and reports segment-level statistics on whether the
subnormal-noise guard fires.

This is a DIAGNOSTIC script. Do not commit.

Guard version being tested: noise <= 1e-10 (from execute_tools/scoring_utils.py
on branch feat/parallel-session-fixes-and-improvements, PR #117).
"""

import math

import numpy as np

from execute_tools.scoring_utils import find_peak, get_snr

SEGMENT_LENGTH = 10_000_000  # 1 second at 10 MS/s (production)
SAMPLING_FREQ = 10e6  # Hz
N_SEGMENTS_PER_FILE = 200  # production SEGMENTS_PER_FILE
N_FILES = 20  # production NUM_FILES

PERTURBATION_RATES = [0.0, 0.0001, 0.001, 0.01, 0.1]
COLLAPSE_CONSTANTS = [-1, 0, 1]


def synthesize_output(constant_k: int, perturbation_rate: float, n_samples: int, rng) -> np.ndarray:
    """Constant-K int8 array with a fraction of samples perturbed by +/-2."""
    out = np.full(n_samples, constant_k, dtype=np.int8)
    if perturbation_rate > 0:
        n_perturb = int(n_samples * perturbation_rate)
        if n_perturb > 0:
            indices = rng.choice(n_samples, size=n_perturb, replace=False)
            out[indices] = np.clip(
                constant_k + rng.integers(-2, 3, size=n_perturb),
                -128,
                127,
            ).astype(np.int8)
    return out


def analyze_segment(signal_int8: np.ndarray, sampling_freq: float) -> dict:
    """PSD + get_snr for a single 10M-sample int8 segment.

    Mirrors the production PSD path in execute_tools.scoring_utils: int8 -> mV
    (40 mV / 128 = 0.3125 mV/LSB), rfft, PSD normalisation, freq axis linspace.
    """
    signal_mv = signal_int8.astype(np.float32) * (40.0 / 128.0)
    fft = np.fft.rfft(signal_mv)
    psd = (1.0 / sampling_freq / len(signal_mv)) * np.abs(fft) ** 2
    freq = np.linspace(0, sampling_freq / 2, len(psd))

    snr, peak_freq = get_snr(freq, psd)

    center_id = find_peak(psd)
    signal_win = float(np.sum(psd[center_id - 1 : center_id + 2]))
    noise_win = float(np.sum(psd[center_id - 50 : center_id + 51]) - signal_win)

    return {
        "snr": snr,
        "peak_freq": peak_freq,
        "signal_window": signal_win,
        "noise_window": noise_win,
        "guard_would_fire": noise_win <= 1e-10,
    }


def main() -> None:
    rng = np.random.default_rng(42)
    print("=" * 80)
    print("EMPIRICAL 6.3556 PHANTOM INVESTIGATION")
    print("Guard version being tested: noise <= 1e-10")
    print(
        f"Segment length: {SEGMENT_LENGTH} samples ({SEGMENT_LENGTH / SAMPLING_FREQ:.1f} sec at {SAMPLING_FREQ:.0e} Hz)"
    )
    print(f"Segments per cell: {N_SEGMENTS_PER_FILE}")
    print(
        f"Cells: {len(COLLAPSE_CONSTANTS)} constants x {len(PERTURBATION_RATES)} rates = {len(COLLAPSE_CONSTANTS) * len(PERTURBATION_RATES)}"
    )
    print("=" * 80)

    for K in COLLAPSE_CONSTANTS:
        for rate in PERTURBATION_RATES:
            print(f"\n--- constant_k = {K}, perturbation_rate = {rate} ---", flush=True)
            results = []
            for _seg_idx in range(N_SEGMENTS_PER_FILE):
                sig = synthesize_output(K, rate, SEGMENT_LENGTH, rng)
                r = analyze_segment(sig, SAMPLING_FREQ)
                results.append(r)

            guard_fires = sum(1 for r in results if r["guard_would_fire"])
            nan_count = sum(1 for r in results if math.isnan(r["snr"]))
            finite_snrs = [r["snr"] for r in results if math.isfinite(r["snr"])]
            noise_vals = [r["noise_window"] for r in results]
            signal_vals = [r["signal_window"] for r in results]

            print(f"  segments analysed: {N_SEGMENTS_PER_FILE}")
            print(f"  guard fires (noise <= 1e-10): {guard_fires}/{N_SEGMENTS_PER_FILE}")
            print(f"  NaN returned from get_snr:    {nan_count}/{N_SEGMENTS_PER_FILE}")
            print(f"  noise_window range: [{min(noise_vals):.3e}, {max(noise_vals):.3e}]")
            print(f"  noise_window median: {float(np.median(noise_vals)):.3e}")
            print(f"  signal_window range: [{min(signal_vals):.3e}, {max(signal_vals):.3e}]")
            if finite_snrs:
                print(f"  finite SNR count: {len(finite_snrs)}")
                print(f"  finite SNR range: [{min(finite_snrs):.3e}, {max(finite_snrs):.3e}]")
                print(f"  finite SNR mean:  {float(np.mean(finite_snrs)):.3e}")
                print(f"  finite SNR median:{float(np.median(finite_snrs)):.3e}")
            else:
                print("  finite SNR count: 0 (all segments produced NaN)")


if __name__ == "__main__":
    main()
