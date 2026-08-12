"""
Legacy-parity evidence — Step-00 NUM-7 (real_run higher tier).

Asserts that the production scoring entry point in legacy mode,
``score_vector(legacy_mode=True)``, reproduces
``denoising_score_old.calculateBenchmark`` bit-for-bit on a real TIDMAD
validation file. The reference is the fixture at
``tests/fixtures/legacy_scoring.py`` — a verbatim copy of the five legacy
functions with a **one-line** ``TS.astype(np.float64)`` patch inside
``GetOneSecPSD`` to restore the numpy-1.x implicit promotion under which
the canonical TIDMAD benchmark numbers were generated.

Step-00 OD-4 disposition (operator-approved 2026-08-12; design
``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§22.2): the former tests 1-2 (``_calculate_score`` coarse/fine parity)
were DELETED — their bit-parity property is obsolete by three intentional
frozen decisions (global ``s_max`` ruler vs legacy file-local ``amax``;
``round(·, 2)`` removal; ``+1e-10`` offset removal), so it is
unsatisfiable by design, and their signature had already drifted
(missing the now-required ``s_max``). Their still-valid coverage is owned
by ``tests/unit/test_compute_raw_baseline.py`` (1e-12 aggregation pins)
and the Step-00 NUM-1/NUM-4 full-precision committed-artifact pins.

The remaining test IS the legacy-reproduction property: ``legacy_mode``
re-derives the file-local ``np.amax`` internally, matching legacy
semantics. GREEN-BEFORE-CITE (design §16 tier 3): any Stage-A claim
citing NUM-7 must attach a fresh green run of this test from the data
machine.

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
def legacy_fine_score(data_paths):
    """Reference scalar from the patched-legacy fixture, fine mode.

    Slow (~1-2 min on 8 cores). Shared across fine-mode tests.
    """
    data_dir, fname = data_paths
    args = argparse.Namespace(coarse=False, parallel=True, num_workers=8)
    return legacy_scoring.calculateBenchmark(data_dir, [fname], args)


class TestLegacyParity:
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
        _, score_new = score_vector(
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
