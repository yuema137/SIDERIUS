"""C6b — production probe executors: F-1a/F-1b direct tests, realized
supersession, unit conversions, and the zero-LLM end-to-end pseudo chain
(implementation → probe → estimate → policy → registry artifacts).

CPU-only: a tiny REAL nn.Module is registered into the LIVE
MODEL_REGISTRY (the F-1b path — the probe loads the actual candidate,
not a lookalike) and probed on device="cpu" against the repo's standard
synthetic-H5 dataset fixture (the F-1a path through the canonical
resolver). No GPU, no LLM, no real dataset."""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.decision_policy import (
    RuntimeBudget,
    RuntimeDecisionPolicy,
    RuntimeMode,
)
from core.runtime_control.probe import (
    ContentionSnapshot,
    ProbeCaps,
    batches_for_segments,
    extrapolate_probe,
    probe_observations,
    run_bounded_probe,
    total_eval_segments,
)
from core.runtime_control.probe_production import production_probe_executors

SEG = 256
FRESH_TYPE = "c6_probe_fresh_candidate"

IDLE = ContentionSnapshot(foreign_compute_processes=0, telemetry_available=True)


def _idle_window(**kwargs):
    """C8e: the probe consumes a bounded D3 window; this test drives the
    REAL classifier with a deterministic idle sample set (no nvidia-smi)."""
    from core.runtime_control.calibration_policy import sample_contention_window

    return sample_contention_window(
        device_vram_gb=kwargs.get("device_vram_gb", 32.0),
        expected_peer_pids=kwargs.get("expected_peer_pids", ()),
        capture=lambda *a, **k: IDLE,
        sleep=lambda _s: None,
    )


@pytest.fixture
def fresh_plugin():
    """Register a tiny REAL model + config into the LIVE registries (the
    exact seam the validator uses), cleaned up afterwards."""
    import torch.nn as nn
    from pydantic import BaseModel

    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY

    class FreshConfig(BaseModel):
        segmentation_size: int = SEG
        hidden: int = 8

    class FreshModel(nn.Module):
        def __init__(self, cfg: FreshConfig):
            super().__init__()
            self.embed = nn.Embedding(256, cfg.hidden)
            self.head = nn.Linear(cfg.hidden, 256)

        def forward(self, x):
            # [B, T] int -> [B, 256, T] float (repo forward contract)
            return self.head(self.embed(x.long())).permute(0, 2, 1)

    MODEL_REGISTRY[FRESH_TYPE] = FreshModel
    PLUGIN_CONFIG_REGISTRY[FRESH_TYPE] = FreshConfig
    try:
        yield FreshModel, FreshConfig
    finally:
        MODEL_REGISTRY.pop(FRESH_TYPE, None)
        PLUGIN_CONFIG_REGISTRY.pop(FRESH_TYPE, None)


def _executors(data_dir: str):
    return production_probe_executors(
        model_type=FRESH_TYPE,
        model_config={"segmentation_size": SEG},
        train_config={
            "lr": 1e-3,
            "batch_size": 1,
            "epochs": 1,
            "optimizer_type": "adamw",
            "weight_decay": 0.0,
            "device": "cpu",
        },
        loss_config={"loss_type": "ce"},
        data_dir=data_dir,
        device="cpu",
    )


class TestF1bFreshPluginLoading:
    def test_unregistered_type_is_a_hard_error(self):
        ex = production_probe_executors(
            model_type="never_registered_xyz",
            model_config={},
            train_config={},
            loss_config={},
            data_dir="/nonexistent",
            device="cpu",
        )
        with pytest.raises(RuntimeError, match="not in the live MODEL_REGISTRY"):
            ex.setup()

    def test_actual_fresh_candidate_is_probed(self, fresh_plugin, synthetic_h5):
        """The probe loads the JUST-REGISTERED candidate and recomputes
        realized properties from the real module — hand-verified counts."""
        _FreshModel, _ = fresh_plugin
        data_dir, _ = synthetic_h5(seg_size=SEG)
        realized = _executors(data_dir).setup()
        expected_params = 256 * 8 + (8 * 256 + 256)  # embedding + linear(+bias)
        assert realized.parameter_count == expected_params
        assert realized.trainable_parameter_count == expected_params
        assert realized.dtype == "float32"
        assert realized.parameter_memory_gb == pytest.approx(expected_params * 4 / 2**30)


class TestF1aDatasetResolution:
    def test_missing_dataset_dir_raises_f1a_error(self, fresh_plugin):
        ex = _executors("/definitely/not/a/dir")
        with pytest.raises(RuntimeError, match="no silent synthetic fallback"):
            ex.setup()

    def test_no_data_dir_is_refused_rather_than_defaulted(self, fresh_plugin):
        """07c C4. This test previously asserted the opposite: that
        `data_dir=None` resolved `execute_tools.data_paths.TIDMAD_DATA_DIR`,
        "the single source of truth, not any second convention".

        That was the right rule when TIDMAD was the only task, and it is the
        defect now — generic runtime-control reaching for one task's dataset
        means every other task either measures the wrong data or reports a
        path its caller never chose. The intent survives ("never a second
        convention, never a silent fallback"); the correct destination
        changed from "the canonical path" to "an explicit refusal".
        """
        ex = production_probe_executors(
            model_type=FRESH_TYPE,
            model_config={"segmentation_size": SEG},
            train_config={
                "lr": 1e-3,
                "batch_size": 1,
                "epochs": 1,
                "optimizer_type": "adamw",
                "weight_decay": 0.0,
                "device": "cpu",
            },
            loss_config={"loss_type": "ce"},
            data_dir=None,
            device="cpu",
        )
        with pytest.raises(RuntimeError, match="no dataset directory was supplied") as excinfo:
            ex.setup()
        # The refusal must say what the CALLER has to do, or an operator
        # cannot act on it.
        assert "measurement capability" in str(excinfo.value)

    def test_empty_dataset_dir_raises(self, fresh_plugin, tmp_path):
        (tmp_path / "d").mkdir()
        ex = _executors(str(tmp_path / "d"))
        with pytest.raises(RuntimeError, match="no declared training file exists"):
            ex.setup()


class TestUnitConversions:
    def test_segment_and_batch_math(self):
        assert total_eval_segments(n_files=5, segments_per_file=200, eval_portion=0.01) == 10
        assert total_eval_segments(n_files=5, segments_per_file=200, eval_portion=1.0) == 1000
        # per-file floor of 1 segment
        assert total_eval_segments(n_files=5, segments_per_file=200, eval_portion=0.001) == 5
        assert total_eval_segments(n_files=5, segments_per_file=200, eval_portion=0.0) == 0
        assert batches_for_segments(1000, 25) == 40
        assert batches_for_segments(1001, 25) == 41
        assert batches_for_segments(0, 25) == 0

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError):
            total_eval_segments(n_files=0, segments_per_file=200, eval_portion=0.5)
        with pytest.raises(ValueError):
            batches_for_segments(10, 0)


class TestEndToEndPseudoChain:
    def test_implementation_to_policy_and_artifacts(self, fresh_plugin, synthetic_h5, tmp_path):
        """Zero-LLM chain: fresh implementation (registered candidate) →
        REAL CPU probe through the production executors → structured
        estimate → C4 policy decision → C5 registry artifacts. The
        propagation layers under test are not mocked."""
        data_dir, _ = synthetic_h5(seg_size=SEG)
        result = run_bounded_probe(
            model_identity=FRESH_TYPE,
            executors=_executors(data_dir),
            caps=ProbeCaps(
                max_wall_seconds=60.0,
                n_warmup_steps=1,
                n_timed_train_steps=3,
                n_timed_inference_batches=2,
            ),
            device_vram_gb=32.0,
            contention_window=_idle_window,
        )
        assert result.status == "ok"
        assert result.realized is not None
        assert result.realized.parameter_count == 256 * 8 + (8 * 256 + 256)
        assert result.train_ms_per_step is not None
        assert result.inference_ms_per_batch is not None
        assert result.peak_vram_gb is None  # CPU probe: no fabricated VRAM

        segments = total_eval_segments(n_files=5, segments_per_file=200, eval_portion=0.01)
        est = extrapolate_probe(
            result,
            train_steps=100,
            inference_batches=batches_for_segments(segments, 25),
            producer_identity="test",
        )
        assert est.provenance == "bounded_live_probe"
        assert est.training_seconds is not None and est.inference_seconds is not None

        decision = RuntimeDecisionPolicy().decide(
            est,
            RuntimeBudget(time_seconds=3600.0),
            RuntimeMode(phase="trial", candidate_stage="post_implementation"),
        )
        assert decision.kind == "ALLOW"

        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        obs = probe_observations(
            result,
            hardware_compatibility_id="sha256:" + "a" * 64,
            execution_environment_id="sha256:" + "b" * 64,
            workload={"batch_size": 1, "segment_length": SEG},
            software_stack={},
            source_run={"run_name": "c6_pseudo_chain"},
        )
        ids = [registry.record_observation(o) for o in obs]
        assert len(ids) == 2  # training + inference, distinct
        # realized supersession: the records carry the REAL count, and no
        # LLM-authored figure exists anywhere in the artifacts.
        for oid in ids:
            rec = registry.load_observation(oid)
            assert rec.realized_model["parameter_count"] == 256 * 8 + (8 * 256 + 256)


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
