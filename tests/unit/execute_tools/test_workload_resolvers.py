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
from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_LEN
from execute_tools.workload_resolvers import (
    resolve_formal_workloads,
    resolve_inference_workload,
    resolve_scoring_workload,
    resolve_training_workload,
)

INCIDENT_SS = {str(i): list(range(20)) for i in range(4, 10)}  # 120 PSD


class TestTrainingResolver:
    def _loader_steps(self, ss, seg, bs, portion, epochs):
        ml = PSD_LEN // seg
        n_psd = sum(
            max(1, round(portion * len(v))) if (portion is not None and portion < 1.0) else len(v)
            for v in ss.values()
        )
        return (n_psd * ml // bs) * epochs

    def test_incident_exact(self):
        w = resolve_training_workload(
            INCIDENT_SS, seg_size=1250, batch_size=2, train_portion=1.0, epochs=1
        )
        assert w.unit == "optimizer_step"
        assert w.unit_count == 480_000
        assert w.detail["samples_per_epoch"] == 960_000
        assert w.detail["n_psd_kept"] == 120

    def test_grid_exact_match_vs_trainer(self):
        ss = {"4": list(range(20)), "5": list(range(7)), "9": [0]}
        for seg in (1250, 10_000, 40_000):
            for bs in (2, 3, 64):
                for portion in (1.0, 0.5, 0.1, None):
                    for epochs in (1, 3):
                        w = resolve_training_workload(
                            ss, seg_size=seg, batch_size=bs, train_portion=portion, epochs=epochs
                        )
                        assert w.unit_count == self._loader_steps(ss, seg, bs, portion, epochs)

    def test_estimator_delegates_here(self):
        """RT1's `_total_train_steps` and the colocated resolver are ONE
        authority — identical on the incident case and a floor case."""
        assert _total_train_steps(INCIDENT_SS, 1250, 2, 1.0, 1) == 480_000
        ss = {str(i): [0] for i in range(20)}
        assert (
            _total_train_steps(ss, 10_000, 8, 0.1, 1)
            == resolve_training_workload(
                ss, seg_size=10_000, batch_size=8, train_portion=0.1, epochs=1
            ).unit_count
        )

    def test_invalid_inputs_raise(self):
        with pytest.raises(ValueError, match="batch_size"):
            resolve_training_workload(
                INCIDENT_SS, seg_size=1250, batch_size=0, train_portion=1.0, epochs=1
            )
        with pytest.raises(ValueError, match="seg_size"):
            resolve_training_workload(
                INCIDENT_SS, seg_size=0, batch_size=2, train_portion=1.0, epochs=1
            )


class TestInferenceResolver:
    def _engine_batches(self, ss, seg, bs):
        """Independent re-derivation of inference_single.py:354-360:
        dim1 = n_psd × (PSD_LEN // seg); batches = len(range(0, dim1, bs))."""
        ml = PSD_LEN // seg
        return sum(len(range(0, len(v) * ml, bs)) for v in ss.values())

    def test_grid_exact_match_vs_engine(self):
        ss = {"4": list(range(3)), "7": [0], "9": list(range(20))}
        for seg in (1250, 10_000, 40_000):
            for bs in (16, 64, 1000):
                w = resolve_inference_workload(ss, seg_size=seg, inference_batch_size=bs)
                assert w.unit == "inference_batch"
                assert w.unit_count == self._engine_batches(ss, seg, bs)

    def test_output_write_cost_exposed(self):
        """create_abra_file writes denoised + injected int8 channels,
        n_psd × PSD_LEN bytes each (§2.6: output cost priced separately)."""
        w = resolve_inference_workload(INCIDENT_SS, seg_size=1250, inference_batch_size=64)
        assert w.detail["output_bytes"] == 120 * PSD_LEN * 2
        assert w.detail["output_files"] == 6
        assert w.detail["n_psd"] == 120

    def test_partial_batch_counts_as_one(self):
        # 1 PSD at seg 40000 → 250 segments; bs 64 → ceil = 4 batches.
        w = resolve_inference_workload({"4": [0]}, seg_size=40_000, inference_batch_size=64)
        assert w.unit_count == 4


class TestScoringResolver:
    def test_unit_is_psd_segment(self):
        w = resolve_scoring_workload(INCIDENT_SS, num_workers=8)
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
            INCIDENT_SS,
            eval_ss,
            seg_size=1250,
            batch_size=2,
            train_portion=1.0,
            epochs=1,
            inference_batch_size=64,
            scoring_num_workers=8,
        )
        assert set(workloads) == {"training", "inference", "scoring"}
        assert workloads["training"].unit_count == 480_000
        assert workloads["inference"].detail["n_psd"] == 3  # eval scope
        assert workloads["scoring"].unit_count == 3
        for phase, w in workloads.items():
            assert w.phase == phase
