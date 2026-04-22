"""
Anchor-map consistency — Phase 5.2 of the legacy-parity alignment.

Two checks on ``segment_anchors.json``:

A. **Static s_max consistency** (no I/O) — asserts that the top-level
   ``s_max`` field equals ``max(max(segs) for segs in anchors.values())``,
   which is what ``build_anchor_map.build_anchor_map`` computes at the
   end of its scan. Catches a corrupted JSON or a manually-edited
   ``s_max``.

B. **Strict-primitive recomputation** (sparse sample) — recomputes the
   CH2 SNR for ~15 (file, segment) pairs using the strict primitives
   (``get_one_sec_psd`` + ``get_snr``) and asserts each matches the
   stored anchor at ``|Δ| < 1e-10``. Catches a stale anchor map that
   was built with pre-refactor primitives (``scipy.fft`` / post-FFT
   scaling).

Both tests require the anchor map file and the raw validation HDF5s
to be present; they skip automatically otherwise. Test B is the
canonical gate for Phase D — if it fails, re-run
``python execute_tools/build_anchor_map.py``.

See ``docs/align_denoising_score.md`` §5.2.
"""
from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.real_run


try:
    from execute_tools.data_paths import TIDMAD_DATA_DIR
except Exception:
    TIDMAD_DATA_DIR = "/home/klz/Data/TIDMAD/"

_ANCHOR_PATH = os.path.join(TIDMAD_DATA_DIR, "segment_anchors.json")
_PARITY_TOL = 1e-10

# Sparse sample grid: 5 files × 3 segments each = 15 recomputations.
# Spans early/mid/late files and early/mid/late segments within each file.
_SAMPLE_FILES = [0, 5, 10, 15, 19]
_SAMPLE_SEGMENTS = [0, 100, 199]


@pytest.fixture(scope="module")
def anchor_map():
    if not os.path.exists(_ANCHOR_PATH):
        pytest.skip(f"Anchor map not found at {_ANCHOR_PATH}")
    with open(_ANCHOR_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestAnchorMapConsistency:

    def test_stored_s_max_matches_max_over_segments(self, anchor_map):
        """Top-level ``s_max`` must equal the maximum over all stored
        per-segment values — the invariant enforced by
        ``build_anchor_map.build_anchor_map`` at its computation site.
        """
        stored = float(anchor_map["s_max"])
        computed = max(max(segs) for segs in anchor_map["anchors"].values())
        delta = abs(stored - computed)
        assert delta < _PARITY_TOL, (
            f"s_max consistency FAILED: stored={stored!r} "
            f"computed={computed!r} |Δ|={delta:.3e} (tol {_PARITY_TOL:.0e})"
        )

    def test_stored_anchors_match_strict_primitives(self, anchor_map):
        """Recompute CH2 SNR for a sparse grid of (file, segment) pairs
        under the strict primitives; each must match the stored value
        at ``|Δ| < 1e-10``. If this fails, the anchor map was built
        under the pre-refactor primitives and must be rebuilt (Phase D).
        """
        from execute_tools.scoring_utils import get_one_sec_psd, get_snr

        mismatches: list[str] = []
        for fi in _SAMPLE_FILES:
            fname = f"abra_validation_{fi:04d}.h5"
            fpath = os.path.join(TIDMAD_DATA_DIR, fname)
            if not os.path.exists(fpath):
                pytest.skip(f"Raw file missing: {fpath}")

            stored_segs = anchor_map["anchors"][str(fi)]
            for si in _SAMPLE_SEGMENTS:
                freq, psd = get_one_sec_psd(TIDMAD_DATA_DIR, fname, ch=2, start=si)
                snr_recomputed, _ = get_snr(freq, psd)
                stored = float(stored_segs[si])
                delta = abs(snr_recomputed - stored)
                if delta >= _PARITY_TOL:
                    mismatches.append(
                        f"  file={fi:02d} seg={si:03d}: stored={stored!r} "
                        f"recomputed={snr_recomputed!r} |Δ|={delta:.3e}"
                    )

        assert not mismatches, (
            f"{len(mismatches)} anchor(s) diverge from strict primitives — "
            f"anchor map is stale. Rebuild with:\n"
            f"  python execute_tools/build_anchor_map.py "
            f"--data_dir {TIDMAD_DATA_DIR} --parallel -n 8\n"
            f"Divergences:\n" + "\n".join(mismatches)
        )
