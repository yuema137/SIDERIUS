"""Reference-data portability tests (PR: reference data -> reference_data/).

The score-comparison reference data (raw_baseline + ground_truth) is a fixed
artifact uniquely determined by the TIDMAD data. It is committed under
reference_data/ and resolved package-relative (CWD-independent), so no server
regenerates it. These tests assert the default resolution and that the
committed data loads and matches the documented reference values.
"""

import os

from nodes.scoring_reference import _default_reference_dir, load_reference_scores


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
    scores = load_reference_scores(use_cache=False)
    assert len(scores.raw_per_file_log) == 20
    assert len(scores.gt_per_file_log) == 20
    # Values from reference_data/raw_and_ground_score.md (global s_max convention).
    assert abs(scores.s_max - 295715680.14248306) < 1e-3
    assert abs(scores.raw_per_file_log[0] - (-11.4402)) < 1e-3
    assert abs(scores.gt_per_file_log[0] - (-8.2610)) < 1e-3
    assert abs(scores.raw_scalar_full - 1.0007) < 1e-3
    assert abs(scores.gt_scalar_full - 10.1134) < 1e-3
