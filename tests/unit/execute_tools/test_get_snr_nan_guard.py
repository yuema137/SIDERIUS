"""v17 NaN guard in ``get_snr`` — the fix that stops the class-127
2^17 SNR artifact from propagating."""

from __future__ import annotations

import math

import numpy as np

from execute_tools.scoring_utils import get_snr


class TestNormalCase:
    def test_healthy_psd_returns_normal_snr(self):
        """A PSD with clear signal + clear noise returns a real SNR.

        Setup: broadband noise floor of 1e-3, peak of 1.0 at bin 100.
        signal window (±1): ~1.002
        noise window (±50) minus signal: ~0.098 (100 noise bins × 1e-3)
        SNR ≈ 10.2 — well above the 1e-10 subnormal guard.
        """
        pwr = np.full(500, 1e-3, dtype=np.float64)
        pwr[100] = 1.0
        freq = np.linspace(0, 5e6, 500)
        snr, center = get_snr(freq, pwr, target=freq[100])
        assert math.isfinite(snr)
        assert snr > 1.0  # actual value ~10.2 — non-artifact real number
        assert center == freq[100]


class TestSubnormalNoiseGuard:
    def test_subnormal_noise_returns_nan(self):
        """Constant-signal PSD produces subnormal noise → NaN return."""
        # Simulate what a constant input's PSD looks like: mostly zeros with
        # a few subnormal values from FP rounding.
        pwr = np.zeros(500, dtype=np.float64)
        pwr[100] = 1.5e-40  # the "signal" — a subnormal artifact
        freq = np.linspace(0, 5e6, 500)
        snr, _ = get_snr(freq, pwr, target=freq[100])
        assert math.isnan(snr)

    def test_zero_noise_returns_nan(self):
        """Exact zero noise (all-zero PSD) also hits the guard."""
        pwr = np.zeros(500, dtype=np.float64)
        freq = np.linspace(0, 5e6, 500)
        snr, _ = get_snr(freq, pwr, target=freq[100])
        assert math.isnan(snr)

    def test_noise_just_above_threshold_returns_finite_snr(self):
        """Noise = 1e-9 (just above the 1e-10 guard) → finite SNR."""
        pwr = np.zeros(500, dtype=np.float64)
        # Signal window covers indices 99, 100, 101
        pwr[100] = 1.0
        # Noise window (±50) needs total minus signal to be ~1e-9
        # Put 100 tiny values of 1e-11 in the noise window
        for i in list(range(50, 100)) + list(range(101, 151)):
            pwr[i] = 1e-11
        freq = np.linspace(0, 5e6, 500)
        snr, _ = get_snr(freq, pwr, target=freq[100])
        assert math.isfinite(snr)

    def test_2_to_the_17_artifact_no_longer_produced(self):
        """The specific class-127 2^17 = 131072 artifact case: signal is
        one subnormal value, noise is FP cancellation of subnormals."""
        pwr = np.zeros(5_000_000, dtype=np.float64)
        # File 19 peak is at bin ~3399999. Only one FP-noise value in the
        # ±50 window, sitting IN the signal window at center_id+1.
        pwr[3_400_000] = 1.522e-40
        freq = np.linspace(0, 5e6, 5_000_000)
        snr, _ = get_snr(freq, pwr, target=freq[3_399_999])
        # Pre-fix: this would return 131072.0 (= 2^17) exactly.
        # Post-fix: NaN.
        assert math.isnan(snr), (
            f"Class-127 collapse artifact returned {snr}, must be NaN. The 2^17 artifact is back."
        )
