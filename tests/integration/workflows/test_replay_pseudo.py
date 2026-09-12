"""C11 pseudo integration — metadata replay feeding an executable replay
that measures through the REAL bounded probe.

Only the device seams are faked. What this proves is the property the
whole two-mode design exists for: a candidate that still has code gets a
real, comparable measurement, and a candidate that never had code stays
labeled as unknowable — in the same report, side by side, with the
difference visible rather than implied.
"""

from __future__ import annotations

import json

from core.runtime_control.calibration_policy import sample_contention_window
from core.runtime_control.probe import (
    ContentionSnapshot,
    ProbeCaps,
    ProbeExecutors,
    RealizedModelProperties,
    run_bounded_probe,
)
from tools.runtime_replay.executable_replay import run_executable_replay
from tools.runtime_replay.metadata_replay import run_metadata_replay
from tools.runtime_replay.schemas import MeasuredRuntime

IDLE = ContentionSnapshot(
    telemetry_available=True, foreign_compute_processes=0, gpu_utilization_pct=1.0
)


def _snapshot(tmp_path):
    root = tmp_path / "forensics"
    workspace = root / "arch" / "workspace" / "iter_001" / "iteration_001" / "attempt_001"
    workspace.mkdir(parents=True)
    (workspace / "proposal_iter_001.json").write_text(
        json.dumps(
            {
                "model_name": "replay_survivor",
                "parameter_count_estimate": 312_000,
                "preflight_estimated_minutes": 29.16,
                "preflight_factor": 1.458,
            }
        )
    )
    (root / "arch" / "chain.log").write_text(
        "   Pre-flight rejected (factor=84.64x); requesting revision 2/3.\n"
        "   Pre-flight rejected (factor=8.12x); requesting revision 3/3.\n"
    )
    return root


def _real_probe_measurement(_candidate) -> MeasuredRuntime:
    """Measure through the REAL probe engine and D3 classifier."""
    realized = RealizedModelProperties(
        parameter_count=45_408,
        trainable_parameter_count=45_408,
        parameter_memory_gb=0.001,
        dtype="float32",
    )
    train = iter([17.6] * 20)
    infer = iter([3.2] * 20)
    result = run_bounded_probe(
        model_identity="replay_survivor",
        executors=ProbeExecutors(
            setup=lambda: realized,
            train_step=lambda: next(train),
            inference_batch=lambda: next(infer),
            peak_vram_gb=lambda: 1.2,
        ),
        caps=ProbeCaps(n_warmup_steps=2, n_timed_train_steps=5, n_timed_inference_batches=3),
        device_vram_gb=32.0,
        contention_window=lambda **kw: sample_contention_window(
            device_vram_gb=32.0,
            capture=lambda *a, **k: IDLE,
            sleep=lambda _s: None,
        ),
    )
    return MeasuredRuntime(
        train_ms_per_step=result.train_ms_per_step,
        inference_ms_per_batch=result.inference_ms_per_batch,
        setup_seconds=result.setup_seconds,
        peak_vram_gb=result.peak_vram_gb,
        realized_parameter_count=result.realized.parameter_count if result.realized else None,
        concurrency_identity=result.concurrency_identity,
        probe_status=result.status,
    )


class TestReplayPseudo:
    def test_metadata_then_executable_over_the_real_probe(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ml_models.models_sandbox.MODEL_REGISTRY", {"replay_survivor": object()}
        )
        metadata = run_metadata_replay(_snapshot(tmp_path))
        assert metadata.mode == "metadata"
        assert all(c.measured is None for c in metadata.candidates)

        executable = run_executable_replay(metadata, probe=_real_probe_measurement)
        assert executable.mode == "executable"

        survivor = next(c for c in executable.candidates if c.stage == "surviving_proposal")
        assert survivor.measured is not None
        assert survivor.measured.probe_status == "ok"
        assert survivor.measured.train_ms_per_step == 17.6
        assert survivor.measured.concurrency_identity == "single_candidate_idle"

        # The estimate and the measurement sit side by side, both labeled.
        assert survivor.static_label == "static_estimate"
        assert survivor.measured.label == "empirical_measurement"
        # The LLM's 312K vs the realized 45,408 — the §16.7 divergence, visible.
        assert survivor.parameter_count_estimate == 312_000
        assert survivor.measured.realized_parameter_count == 45_408

    def test_the_never_implemented_drafts_stay_unknowable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "ml_models.models_sandbox.MODEL_REGISTRY", {"replay_survivor": object()}
        )
        executable = run_executable_replay(
            run_metadata_replay(_snapshot(tmp_path)), probe=_real_probe_measurement
        )
        drafts = [c for c in executable.candidates if c.stage == "rejected_draft"]
        assert len(drafts) == 2
        assert {d.static_factor for d in drafts} == {84.64, 8.12}
        for draft in drafts:
            assert draft.measured is None
            assert draft.runtime_truth_known is False
        rendered = executable.render()
        assert "no runtime ground truth for this candidate" in rendered
        assert "never implemented" in rendered
