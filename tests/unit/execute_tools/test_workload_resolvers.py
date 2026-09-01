"""RT2-A — workload resolvers: exact-match against production semantics.

Design: docs/design/runtime_estimation_and_watchdog.md §1.2. Each
resolver is tested against an independent re-derivation of its
production authority:
- training: `train_engine_sandbox.py:300-304` + DataLoader(drop_last)
- inference: `inference_single.py` sample_set mode (per-file lazy
  slice → reshape → range(0, dim1, bs) batches → 2-channel int8 write)
- scoring: `score_vector` PSD-segment parallelism
"""

from __future__ import annotations

import pytest

from agent.skills.training_skill.estimator import _total_train_steps
from execute_tools.workload_resolvers import (
    resolve_formal_workloads,
    resolve_inference_workload,
    resolve_scoring_workload,
    resolve_training_workload,
)
from tests.helpers.two_family_profile import make_two_family_profile

PHYSICAL_SEGMENT_LENGTH = 1_600_000
PROFILE = make_two_family_profile(
    num_files=6,
    psd_segment_length=PHYSICAL_SEGMENT_LENGTH,
    segments_per_file=20,
)
SAMPLE_SET = {str(i): list(range(20)) for i in range(6)}  # 120 physical segments


class TestTrainingResolver:
    def _loader_steps(self, ss, seg, bs, portion, epochs):
        ml = PHYSICAL_SEGMENT_LENGTH // seg
        n_psd = sum(
            max(1, round(portion * len(v))) if (portion is not None and portion < 1.0) else len(v)
            for v in ss.values()
        )
        return (n_psd * ml // bs) * epochs

    def test_declared_profile_exact(self):
        w = resolve_training_workload(
            SAMPLE_SET,
            profile=PROFILE,
            seg_size=1250,
            batch_size=2,
            train_portion=1.0,
            epochs=1,
        )
        assert w.unit == "optimizer_step"
        assert w.unit_count == 76_800
        assert w.detail["samples_per_epoch"] == 153_600
        assert w.detail["n_psd_kept"] == 120

    def test_grid_exact_match_vs_trainer(self):
        ss = {"4": list(range(20)), "5": list(range(7)), "9": [0]}
        for seg in (1250, 10_000, 40_000):
            for bs in (2, 3, 64):
                for portion in (1.0, 0.5, 0.1, None):
                    for epochs in (1, 3):
                        w = resolve_training_workload(
                            ss,
                            profile=PROFILE,
                            seg_size=seg,
                            batch_size=bs,
                            train_portion=portion,
                            epochs=epochs,
                        )
                        assert w.unit_count == self._loader_steps(ss, seg, bs, portion, epochs)

    def test_estimator_delegates_here(self):
        """RT1's `_total_train_steps` and the colocated resolver are ONE
        authority — identical on the declared-profile case and a floor case."""
        assert _total_train_steps(SAMPLE_SET, 1250, 2, 1.0, 1, PROFILE) == 76_800
        ss = {str(i): [0] for i in range(20)}
        assert (
            _total_train_steps(ss, 10_000, 8, 0.1, 1, PROFILE)
            == resolve_training_workload(
                ss,
                profile=PROFILE,
                seg_size=10_000,
                batch_size=8,
                train_portion=0.1,
                epochs=1,
            ).unit_count
        )

    def test_invalid_inputs_raise(self):
        with pytest.raises(ValueError, match="batch_size"):
            resolve_training_workload(
                SAMPLE_SET,
                profile=PROFILE,
                seg_size=1250,
                batch_size=0,
                train_portion=1.0,
                epochs=1,
            )
        with pytest.raises(ValueError, match="seg_size"):
            resolve_training_workload(
                SAMPLE_SET,
                profile=PROFILE,
                seg_size=0,
                batch_size=2,
                train_portion=1.0,
                epochs=1,
            )


class TestInferenceResolver:
    def _engine_batches(self, ss, seg, bs):
        """Independent re-derivation of inference_single.py:354-360:
        dim1 = n_psd × (physical_length // seg); batches = len(range(0, dim1, bs))."""
        ml = PHYSICAL_SEGMENT_LENGTH // seg
        return sum(len(range(0, len(v) * ml, bs)) for v in ss.values())

    def test_grid_exact_match_vs_engine(self):
        ss = {"4": list(range(3)), "7": [0], "9": list(range(20))}
        for seg in (1250, 10_000, 40_000):
            for bs in (16, 64, 1000):
                w = resolve_inference_workload(
                    ss, profile=PROFILE, seg_size=seg, inference_batch_size=bs
                )
                assert w.unit == "inference_batch"
                assert w.unit_count == self._engine_batches(ss, seg, bs)

    def test_output_write_cost_exposed(self):
        """The indexed writer emits two storage channels per physical segment."""
        w = resolve_inference_workload(
            SAMPLE_SET, profile=PROFILE, seg_size=1250, inference_batch_size=64
        )
        assert w.detail["output_bytes"] == 120 * PHYSICAL_SEGMENT_LENGTH * 2
        assert w.detail["output_files"] == 6
        assert w.detail["n_psd"] == 120

    def test_partial_batch_counts_as_one(self):
        # One physical segment at seg 40,000 yields 40 model segments: one batch.
        w = resolve_inference_workload(
            {"4": [0]}, profile=PROFILE, seg_size=40_000, inference_batch_size=64
        )
        assert w.unit_count == 1


class TestScoringResolver:
    def test_unit_is_psd_segment(self):
        w = resolve_scoring_workload(SAMPLE_SET, num_workers=8)
        assert w.unit == "psd_segment"
        assert w.unit_count == 120
        assert w.detail["effective_serial_units"] == pytest.approx(120 / 8)

    def test_workers_floor_at_one(self):
        w = resolve_scoring_workload({"4": [0, 1]}, num_workers=0)
        assert w.detail["num_workers"] == 1
        assert w.detail["effective_serial_units"] == pytest.approx(2.0)


class TestFormalWorkloads:
    def test_all_compute_phases_resolved_with_correct_scopes(self):
        eval_ss = {"4": [0, 1], "5": [3]}  # eval scope ≠ train scope
        workloads = resolve_formal_workloads(
            SAMPLE_SET,
            eval_ss,
            profile=PROFILE,
            seg_size=1250,
            batch_size=2,
            train_portion=1.0,
            epochs=1,
            inference_batch_size=64,
            scoring_num_workers=8,
        )
        assert set(workloads) == {"training", "inference", "scoring"}
        assert workloads["training"].unit_count == 76_800
        assert workloads["inference"].detail["n_psd"] == 3  # eval scope
        assert workloads["scoring"].unit_count == 3
        for phase, w in workloads.items():
            assert w.phase == phase
