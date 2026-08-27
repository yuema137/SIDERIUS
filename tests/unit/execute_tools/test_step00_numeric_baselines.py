"""Step-00 NUM-2..NUM-6, NUM-8 — scorer/numeric baselines (OD-3 approved split).

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.4 / §22 OD-3 / §15.1 (roadmap step 06 A-surface).

The frozen scorer is IMMUTABLE: nothing here touches production scoring
code, and per §12 rule 3's exemption every formula with a production
implementation is routed THROUGH that implementation
(``compute_ground_truth`` ceiling functions, ``scoring_helpers.
_grand_mean_log_scalar``, ``per_file_best._log``) — deleting or rewriting
the production aggregation breaks these pins.

NUM-6 is a Type-5 MECHANISM replay ONLY (OD-3): a runtime-generated
tiny-N HDF5 under ``tmp_path`` (never committed) exercises the REAL
``score_vector(legacy_mode=False)`` body — aggregation choreography,
sentinels, the frozen raw-filename literal (MIGRATION PARITY), the
unconditional ``channel0001`` attrs read — with ``SEGMENT_LENGTH``
monkeypatched and ``parallel=False`` (the spawn path is a §15.2
deferral). It is explicitly NOT frozen-scorer numeric parity: shrinking N
changes the frequency grid and every SNR (design §13.4).
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import h5py
import numpy as np
import pytest

import execute_tools.scoring_utils as scoring_utils
from execute_tools.scoring_helpers import _grand_mean_log_scalar
from tests.helpers.golden import assert_json_golden

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE = REPO_ROOT / "reference_data"
GOLDENS = Path(__file__).parent / "goldens"

_S_MAX = 295715680.14248306


def _load_anchor_map() -> dict:
    return json.loads((REFERENCE / "segment_anchors.json").read_text(encoding="utf-8"))


class TestNUM2AnchorMap:
    def test_s_max_exact_and_shape(self):
        m = _load_anchor_map()
        assert m["s_max"] == _S_MAX
        assert m["segments_per_file"] == 200
        assert m["num_files"] == 20
        assert sorted(m["anchors"], key=int) == [str(i) for i in range(20)]
        for segs in m["anchors"].values():
            assert len(segs) == 200

    def test_s_max_is_the_global_anchor_maximum(self):
        m = _load_anchor_map()
        assert m["s_max"] == max(max(segs) for segs in m["anchors"].values())

    def test_canonical_content_digest(self):
        m = _load_anchor_map()
        digest = hashlib.sha256(json.dumps(m, sort_keys=True).encode("utf-8")).hexdigest()
        assert digest == "db806ecd1b05cc10e51b032ef41f0607c24d3daaedb3fcebe7a0999ffe8a2f17"


class TestNUM3GroundTruthDerivability:
    def test_committed_ground_truth_reproduces_from_committed_anchors(self):
        """The committed ground-truth set is EXACTLY the output of the
        production ceiling functions applied to the committed anchor map
        (held exactly at audit time, asserted nowhere before Step 00)."""
        from scripts.compute_ground_truth import (
            _anchor_normalized_ceiling,
            _global_per_file_ceiling,
        )

        m = _load_anchor_map()
        for i in range(20):
            expected = json.loads(
                (REFERENCE / "ground_truth" / f"ground_truth_score_file_{i:04d}.json").read_text(
                    encoding="utf-8"
                )
            )
            score, linear_sum, n = _global_per_file_ceiling(m["anchors"][str(i)], m["s_max"])
            assert score == expected["score"], f"file {i}"
            assert linear_sum == expected["linear_sum"], f"file {i}"
            assert n == expected["n_segments"], f"file {i}"

        ceiling = json.loads(
            (REFERENCE / "ground_truth" / "ceiling_anchor_normalized.json").read_text(
                encoding="utf-8"
            )
        )
        file_vector, scalar = _anchor_normalized_ceiling(m["anchors"], m["s_max"])
        assert scalar == ceiling["scalar_score"]
        assert file_vector == ceiling["file_vector"]


class TestNUM4PerFileArtifactConsistency:
    @pytest.mark.parametrize("family", ["raw_baseline", "ground_truth"])
    def test_score_equals_production_log_of_linear_mean(self, family):
        """Every committed per-file artifact satisfies
        ``score == _grand_mean_log_scalar(linear_sum, n_segments)`` — the
        PRODUCTION grand-mean/log helper, not a test-side formula."""
        prefix = (
            "raw_baseline_score_file_" if family == "raw_baseline" else "ground_truth_score_file_"
        )
        for i in range(20):
            d = json.loads(
                (REFERENCE / family / f"{prefix}{i:04d}.json").read_text(encoding="utf-8")
            )
            assert d["score"] == _grand_mean_log_scalar(d["linear_sum"], d["n_segments"]), (
                f"{family} file {i}"
            )


class TestNUM5LogBaseCrossModuleIdentity:
    def test_three_expressions_of_the_frozen_log_are_bit_identical(self):
        """One contract, three production expressions: the scorer's inline
        ``math.log(x, 5.27)``, ``scoring_helpers._grand_mean_log_scalar``,
        and ``per_file_best._log`` must agree bit-for-bit."""
        from execute_tools.per_file_best import LOG_BASE, _log

        assert LOG_BASE == 5.27
        for linear in (2.0, 0.5, 1.0006820423449074, 10.113400947352815, 1e-6, 3.7e8):
            inline = math.log(linear, 5.27)
            assert _grand_mean_log_scalar(linear, 1) == inline
            assert _log(linear) == inline


# ---------------------------------------------------------------------------
# NUM-6 — mechanism replay (Type 5; NOT numeric parity)
# ---------------------------------------------------------------------------

_N = 4096  # monkeypatched SEGMENT_LENGTH: >> the ±50-bin peak window
_SEGS = 2  # monkeypatched SEGMENTS_PER_FILE


def _write_h5(
    path: Path,
    n_segments: int,
    *,
    constant: bool = False,
    seed: int = 7,
    total_override: int | None = None,
) -> None:
    rng = np.random.default_rng(seed)
    total = total_override if total_override is not None else n_segments * _N
    if constant:
        data = np.zeros(total, dtype=np.int8)
    else:
        t = np.arange(total)
        sine = 20.0 * np.sin(2 * np.pi * t / 64.0)
        data = np.clip(sine + rng.normal(0, 3.0, total), -127, 127).astype(np.int8)
    with h5py.File(path, "w") as f:
        # Real TIDMAD layout: timeseries/channelNNNN is a GROUP carrying
        # the physics attrs, with the samples in a child dataset named
        # "timeseries". get_one_sec_psd reads channel0001's attrs
        # UNCONDITIONALLY, even for ch=2 (audited frozen behavior).
        for ch in ("channel0001", "channel0002"):
            grp = f.create_group(f"timeseries/{ch}")
            grp.create_dataset("timeseries", data=data)
            grp.attrs["voltage_range_mV"] = 80
            grp.attrs["sampling_frequency"] = 10_000_000


@pytest.fixture
def tiny_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(scoring_utils, "SEGMENT_LENGTH", _N)
    monkeypatch.setattr(scoring_utils, "SEGMENTS_PER_FILE", _SEGS)
    for i in (0, 1):
        _write_h5(tmp_path / f"abra_validation_{i:04d}.h5", _SEGS, seed=10 + i)
        _write_h5(tmp_path / f"denoised_{i:04d}.h5", _SEGS, seed=20 + i)
    return tmp_path


class TestNUM6MechanismReplay:
    def _score(self, data_dir: Path, sample_set: dict):
        return scoring_utils.score_vector(
            data_dir=str(data_dir),
            sample_set=sample_set,
            anchor_map=None,
            s_max=1000.0,
            denoised_filename_fn=lambda i: f"denoised_{i:04d}.h5",
            raw_data_dir=str(data_dir),
            parallel=False,
            legacy_mode=False,
        )

    def test_vector_shape_gaps_and_grand_mean_aggregation(self, tiny_scope):
        """The production-path aggregation choreography: length-20 vector
        with None at unsampled indices, and the scalar is the GRAND MEAN
        over all segments (unequal per-file counts prove it is not a
        mean-of-means), logged through the production helper."""
        vector, scalar = self._score(tiny_scope, {0: [0, 1], 1: [0]})
        assert len(vector) == 20
        assert [i for i, v in enumerate(vector) if v is not None] == [0, 1]
        counts = {0: 2, 1: 1}
        total_linear = sum(vector[f] * n for f, n in counts.items())
        assert scalar == _grand_mean_log_scalar(total_linear, 3)

    def test_determinism_bit_identical_across_runs(self, tiny_scope):
        first = self._score(tiny_scope, {0: [0, 1], 1: [0]})
        second = self._score(tiny_scope, {0: [0, 1], 1: [0]})
        assert first == second

    def test_empty_sample_set_yields_minus_inf(self, tiny_scope):
        vector, scalar = self._score(tiny_scope, {})
        assert scalar == float("-inf")
        assert vector == [None] * 20

    def test_nan_drop_excludes_only_the_degenerate_pair(self, monkeypatch, tmp_path):
        """A constant denoised segment trips the ``noise <= 1e-10`` guard
        and its pair is DROPPED from the aggregation, leaving the healthy
        pair's finite score. Mutation-hygiene note: an earlier all-constant
        variant could not distinguish the drop from the non-finite
        grand-mean sentinel (disabling the guard survived — classified
        EQUIVALENT for that fixture); this mixed fixture observes the drop
        itself: guard off → NaN propagates and the scalar degenerates."""
        monkeypatch.setattr(scoring_utils, "SEGMENT_LENGTH", _N)
        monkeypatch.setattr(scoring_utils, "SEGMENTS_PER_FILE", _SEGS)
        _write_h5(tmp_path / "abra_validation_0000.h5", _SEGS, seed=10)
        # Denoised: segment 0 healthy, segment 1 constant (degenerate).
        rng = np.random.default_rng(21)
        t = np.arange(_N)
        good = np.clip(
            20.0 * np.sin(2 * np.pi * t / 64.0) + rng.normal(0, 3.0, _N), -127, 127
        ).astype(np.int8)
        data = np.concatenate([good, np.zeros(_N, dtype=np.int8)])
        with h5py.File(tmp_path / "denoised_0000.h5", "w") as f:
            for ch in ("channel0001", "channel0002"):
                grp = f.create_group(f"timeseries/{ch}")
                grp.create_dataset("timeseries", data=data)
                grp.attrs["voltage_range_mV"] = 80
                grp.attrs["sampling_frequency"] = 10_000_000
        vector, scalar = self._score(tmp_path, {0: [0, 1]})
        # Exactly ONE pair survives: the file mean is over 1 pair, and the
        # scalar is the production log of that single-pair grand mean.
        assert vector[0] is not None and math.isfinite(vector[0])
        assert scalar == _grand_mean_log_scalar(vector[0], 1)
        assert math.isfinite(scalar)

    def test_frozen_raw_filename_literal(self, tiny_scope):
        """MIGRATION PARITY — NOT FINAL FRAMEWORK CONTRACT: the raw side
        is frozen to ``abra_validation_{i:04d}.h5`` (scoring_utils.py:389,
        444); ``validation_file_pattern`` is unwired (roadmap D10). A raw
        file under any other name is invisible to the scorer."""
        (tiny_scope / "abra_validation_0001.h5").rename(tiny_scope / "renamed_0001.h5")
        with pytest.raises(FileNotFoundError):
            self._score(tiny_scope, {1: [0]})

    def test_partial_segment_fails_at_reshape_boundary(self, monkeypatch, tmp_path):
        """A PARTIAL trailing segment errors at the frozen
        ``reshape(len//N, N)`` boundary (an empty slice reshapes cleanly
        to ``(0, N)`` and silent-drops instead — both behaviors are the
        frozen mechanism, discovered at first run of this test)."""
        monkeypatch.setattr(scoring_utils, "SEGMENT_LENGTH", _N)
        monkeypatch.setattr(scoring_utils, "SEGMENTS_PER_FILE", _SEGS)
        # 1.5 segments: requesting segment 1 slices a 0.5-segment tail.
        _write_h5(tmp_path / "abra_validation_0000.h5", 2, seed=10, total_override=_N + _N // 2)
        _write_h5(tmp_path / "denoised_0000.h5", _SEGS, seed=20)
        with pytest.raises(ValueError):
            self._score(tmp_path, {0: [1]})


class TestNUM8PerFileBestKeySet:
    def test_emitted_table_key_set(self, tmp_path):
        """The per_file_best artifact's KEY SET — roadmap step-06 A-surface;
        produced by the REAL ``build_table`` over the RES-1 committed
        workspace fixture. The key set is frozen; the header VALUES are
        resolved, and are asserted by the two tests below."""
        from execute_tools.per_file_best import build_table
        from tests.unit.core.test_step00_resume_replay import stage_workspace

        ws = stage_workspace(tmp_path)
        table = build_table(str(ws))
        assert_json_golden(
            sorted(table.keys()),
            GOLDENS / "num8_per_file_best_key_set.json",
            surface="NUM-8 per_file_best artifact key set",
        )

    def test_metric_id_is_null_when_the_workspace_declares_no_metric(self, tmp_path):
        """UPGRADED (per-file-best identity fix). This assertion previously
        read ``== "tidmad_denoising_score"``, and it passed for the wrong
        reason: the RES-1 fixture holds ZERO records and no stamped
        ``metric_spec``, so it declares no metric whatsoever — the header was
        simply emitting a literal. A workspace that has said nothing about its
        metric must report ``null``, not a fabricated name.

        Fails if the header ever reverts to emitting an unconditional
        identity."""
        from execute_tools.per_file_best import build_table
        from tests.unit.core.test_step00_resume_replay import stage_workspace

        ws = stage_workspace(tmp_path)
        table = build_table(str(ws))
        assert table["metric_id"] is None

    def test_metric_id_is_the_declared_identity_for_a_tidmad_workspace(self, tmp_path):
        """The positive half the old single assertion never had: a workspace
        whose records DO declare TIDMAD still reports TIDMAD, so the fix above
        cannot be satisfied by simply deleting the field."""
        from execute_tools.per_file_best import build_table
        from tests.unit.execute_tools.test_per_file_best import _record, _write_iter

        ws = str(tmp_path / "tidmad_ws")
        _write_iter(
            ws,
            1,
            [_record("a", file_vector=[1.0, 2.0] + [None] * 18, logical_round=1)],
            formal_eval_portion=1.0,
            formal_strategy="snapshot",
        )
        assert build_table(ws)["metric_id"] == "tidmad_denoising_score"
