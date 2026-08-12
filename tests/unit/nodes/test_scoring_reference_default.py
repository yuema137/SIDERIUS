"""Reference-data portability tests (PR: reference data -> reference_data/).

The score-comparison reference data (raw_baseline + ground_truth) is a fixed
artifact uniquely determined by the TIDMAD data. It is committed under
reference_data/ and resolved package-relative (CWD-independent), so no server
regenerates it. These tests assert the default resolution and that the
committed data loads and matches the documented reference values.
"""

import os
from pathlib import Path

from nodes.scoring_reference import _default_reference_dir, load_reference_scores
from tests.helpers.golden import assert_json_golden

GOLDENS = Path(__file__).parent / "goldens"


def test_default_prefers_committed_reference_data():
    for name in ("raw_baseline", "ground_truth"):
        p = _default_reference_dir(name)
        assert os.path.isabs(p)
        assert p.endswith(os.path.join("reference_data", name))
        assert os.path.isdir(p), f"committed {name} must exist under reference_data/"


def test_default_is_cwd_independent(tmp_path, monkeypatch):
    before = _default_reference_dir("raw_baseline")
    monkeypatch.chdir(tmp_path)
    assert _default_reference_dir("raw_baseline") == before


def test_committed_reference_data_loads_and_matches_doc():
    """Step-00 NUM-1 (STR): FULL-PRECISION pins on every committed
    reference number, replacing the previous 5-value/1e-3 surface (which
    left ~4 significant digits unprotected — audit D). The JSON golden
    holds exact repr round-trip values for all 40 per-file scores, both
    anchor-normalized scalars, and the global s_max; comparison is exact
    equality on the parsed floats.

    Design: docs/design/generic_framework_upgrade/
    step_00_golden_baseline_harness.md §13.4 / §22 OD-3.
    """
    scores = load_reference_scores(use_cache=False)
    assert len(scores.raw_per_file_log) == 20
    assert len(scores.gt_per_file_log) == 20
    assert_json_golden(
        {
            "s_max": scores.s_max,
            "raw_per_file_log": list(scores.raw_per_file_log),
            "gt_per_file_log": list(scores.gt_per_file_log),
            "raw_scalar_full": scores.raw_scalar_full,
            "gt_scalar_full": scores.gt_scalar_full,
        },
        GOLDENS / "num1_reference_scores_full_precision.json",
        surface="NUM-1 full-precision committed reference scores",
    )
