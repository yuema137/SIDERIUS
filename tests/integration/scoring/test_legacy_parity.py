"""
End-to-end parity test — canonical merge gate for the scoring alignment.

Asserts that our byte-strict scoring path reproduces
``denoising_score_old.calculateBenchmark`` bit-for-bit on a real TIDMAD
validation file. See ``docs/align_denoising_score.md`` §5.1.

Three comparisons, all against the same legacy reference:

1. ``compute_raw_baseline._calculate_score(coarse=True)``
   — fast (~seconds). Covers the legacy aggregation when driven through
   our ``process_segment`` helper.

2. ``compute_raw_baseline._calculate_score(coarse=False)``
   — the full fine scan. Slower (a few minutes) but guards against any
   subtle coarse-vs-fine divergence.

3. ``score_vector(legacy_mode=True)`` with ``sample_set = {0: range(200)}``
   — validates the production scoring entry point. This is the function
   that the rest of SIDERIUS actually calls; its parity is the merge
   gate for the whole alignment effort.

The reference is the fixture at ``tests/fixtures/legacy_scoring.py`` —
a verbatim copy of the five legacy functions with a **one-line**
``TS.astype(np.float64)`` patch inside ``GetOneSecPSD`` to restore the
numpy-1.x implicit promotion under which the canonical TIDMAD
benchmark numbers were generated. See §1.3 of the plan doc for why
this patch is necessary on numpy ≥ 2.0.

Markers: ``@pytest.mark.real_run`` — requires ``abra_validation_0000.h5``
at ``TIDMAD_DATA_DIR``. Skipped automatically if absent.
"""

from __future__ import annotations

import argparse
import os

import pytest

from tests.fixtures import legacy_scoring

pytestmark = pytest.mark.real_run


try:
    from execute_tools.data_paths import TIDMAD_DATA_DIR
except Exception:
    TIDMAD_DATA_DIR = "/home/klz/Data/TIDMAD/"

_FILE = "abra_validation_0000.h5"
_PARITY_TOL = 1e-10


@pytest.fixture(scope="module")
def data_paths():
    fpath = os.path.join(TIDMAD_DATA_DIR, _FILE)
    if not os.path.exists(fpath):
        pytest.skip(f"Real validation data not found at {fpath}")
    return TIDMAD_DATA_DIR, _FILE


@pytest.fixture(scope="module")
def legacy_coarse_score(data_paths):
    """Reference scalar from the patched-legacy fixture, coarse mode.

    Computed once per module so fine/coarse consumers don't re-run the
    ~20-segment scan. Uses ``parallel=True, num_workers=8`` to match
    the legacy invocation pattern.
    """
    data_dir, fname = data_paths
    args = argparse.Namespace(coarse=True, parallel=True, num_workers=8)
    return legacy_scoring.calculateBenchmark(data_dir, [fname], args)


@pytest.fixture(scope="module")
def legacy_fine_score(data_paths):
    """Reference scalar from the patched-legacy fixture, fine mode.

    Slow (~1-2 min on 8 cores). Shared across fine-mode tests.
    """
    data_dir, fname = data_paths
    args = argparse.Namespace(coarse=False, parallel=True, num_workers=8)
    return legacy_scoring.calculateBenchmark(data_dir, [fname], args)


class TestLegacyParity:
    def test_calculate_score_coarse(self, data_paths, legacy_coarse_score):
        """``compute_raw_baseline._calculate_score`` — coarse parity."""
        from scripts.compute_raw_baseline import _calculate_score

        data_dir, fname = data_paths
        score_new = _calculate_score(
            data_dir=data_dir,
            fname=fname,
            coarse=True,
            parallel=True,
            num_workers=8,
        )
        delta = abs(score_new - legacy_coarse_score)
        assert delta < _PARITY_TOL, (
            f"coarse parity FAILED: new={score_new!r} legacy={legacy_coarse_score!r} "
            f"|Δ|={delta:.3e} (tol {_PARITY_TOL:.0e})"
        )

    def test_calculate_score_fine(self, data_paths, legacy_fine_score):
        """``compute_raw_baseline._calculate_score`` — fine parity (slow)."""
        from scripts.compute_raw_baseline import _calculate_score

        data_dir, fname = data_paths
        score_new = _calculate_score(
            data_dir=data_dir,
            fname=fname,
            coarse=False,
            parallel=True,
            num_workers=8,
        )
        delta = abs(score_new - legacy_fine_score)
        assert delta < _PARITY_TOL, (
            f"fine parity FAILED: new={score_new!r} legacy={legacy_fine_score!r} "
            f"|Δ|={delta:.3e} (tol {_PARITY_TOL:.0e})"
        )

    def test_score_vector_legacy_mode_fine(self, data_paths, legacy_fine_score):
        """``score_vector(legacy_mode=True)`` — the production scorer's
        parity against legacy. This is the canonical merge gate: the
        rest of SIDERIUS drives evaluation through ``score_vector``,
        not through ``_calculate_score``.

        Fine-formal mode: ``sample_set = {0: range(200)}``, one file.
        Under this configuration ``local_idx == seg_idx`` so
        ``_collect_raw_pairs`` reads CH1 and CH2 from the same segment
        — matching legacy's ``process_iteration`` semantics.
        """
        from execute_tools.scoring_utils import score_vector

        data_dir, fname = data_paths
        _, score_new, _, _ = score_vector(
            data_dir=data_dir,
            sample_set={0: list(range(200))},
            anchor_map=None,
            s_max=None,
            denoised_filename_fn=lambda i: fname,
            raw_data_dir=data_dir,
            parallel=True,
            num_workers=8,
            legacy_mode=True,
        )
        delta = abs(score_new - legacy_fine_score)
        assert delta < _PARITY_TOL, (
            f"score_vector(legacy_mode=True) parity FAILED: new={score_new!r} "
            f"legacy={legacy_fine_score!r} |Δ|={delta:.3e} (tol {_PARITY_TOL:.0e})"
        )
