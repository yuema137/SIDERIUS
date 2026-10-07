"""The production adapter dispatches only the task-authorized inference check."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from agent.schemas.preflight import StaticPhaseDecision, StaticPreflightEvidence
from agent.skills.evaluate_vram_skill import preflight_adapter as adapter
from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeResult, IsolatedProbeSpec
from core.inference_preflight_policy import (
    InferencePreflightPolicy,
    bind_inference_preflight_policy,
)
from core.runtime_control import inference_measurement_binding as source_binding
from core.runtime_control import inference_refusal_verification as verification
from core.subprocess_env import subprocess_env
from tests.helpers.inference_measurement import evaluation_probe
from tests.unit.agent.evaluate_vram_skill.test_preflight_adapter import _snapshot


def _phase(phase, *, vram=False, intensity=False):
    return StaticPhaseDecision(
        phase=phase,
        batch_size=11 if phase == "inference" else 3,
        vram_cap_bytes=1024,
        vram_estimate_bytes=2048 if vram else 512,
        estimator="inference_leaf_sum_v1" if phase == "inference" else "training_saved_tensors_v1",
        intensity_product=200 if intensity else None,
        intensity_limit=100 if intensity else None,
    )


def _invoke(tmp_path):
    return adapter.run_production_preflight(
        model_type="synthetic_candidate",
        model_config={"width": 17},
        train_config={"batch_size": 3},
        loss_config={},
        vram_budget_gb=None,
        hardware_context=_snapshot(),
        workspace=tmp_path,
        label="dispatch",
        plugin_dir=str(tmp_path / "models"),
        loss_dir=str(tmp_path / "losses"),
        deadline_seconds=91.0,
    )


@pytest.mark.parametrize(
    ("phases", "outcome", "dispatch"),
    [
        ((_phase("training"), _phase("inference", vram=True)), "STATIC_PREFLIGHT_REFUSAL", True),
        ((_phase("training", vram=True),), "STATIC_PREFLIGHT_REFUSAL", False),
        (
            (_phase("training", vram=True), _phase("inference", vram=True)),
            "STATIC_PREFLIGHT_REFUSAL",
            False,
        ),
        (
            (_phase("training"), _phase("inference", intensity=True)),
            "STATIC_PREFLIGHT_REFUSAL",
            False,
        ),
        (
            (_phase("training"), _phase("inference", vram=True, intensity=True)),
            "STATIC_PREFLIGHT_REFUSAL",
            False,
        ),
        ((_phase("inference", vram=True),), "STATIC_PREFLIGHT_REFUSAL", False),
        (
            (_phase("inference", vram=True), _phase("training")),
            "STATIC_PREFLIGHT_REFUSAL",
            False,
        ),
        ((_phase("training"), _phase("inference")), "COMPLETED_MEASUREMENT", False),
        (None, "PROBE_INFRASTRUCTURE_FAILURE", False),
    ],
    ids=[
        "inference-vram-only",
        "training-refusal",
        "both-phases-refuse",
        "inference-intensity",
        "inference-two-caps",
        "training-not-observed",
        "wrong-phase-order",
        "already-completed",
        "worker-failed",
    ],
)
def test_source_pin_precedes_static_and_only_eligible_refusal_dispatches(
    tmp_path, monkeypatch, phases, outcome, dispatch
):
    """Fails if policy is unreachable, sources are pinned late, or refusal scope broadens."""
    evidence = StaticPreflightEvidence(phases=phases) if phases else None
    sources = source_binding.MeasurementSources(
        assembly_sha256="a" * 64,
        plugin_sources_sha256="b" * 64,
        runtime_sha256="c" * 64,
    )
    events = []

    def pin(*, environ):
        assert environ["SIDERIUS_PLUGIN_DIRS"].split(os.pathsep)[0] == str(tmp_path / "models")
        assert environ["SIDERIUS_LOSS_DIRS"].split(os.pathsep)[0] == str(tmp_path / "losses")
        events.append("pin")
        return sources

    def inspect(spec, *, deadline_seconds):
        assert events == ["pin"]
        assert spec.candidate_sources == sources
        assert deadline_seconds == 91.0
        events.append("static")
        return IsolatedProbeResult(
            label=spec.label,
            outcome=outcome,
            candidate_sources=sources,
            static_preflight_evidence=evidence,
        )

    def verify(**kwargs):
        assert events == ["pin", "static"]
        assert kwargs["static_spec"].candidate_sources == sources
        assert kwargs["static_evidence"] == evidence
        assert kwargs["policy"].max_batches == 2
        assert kwargs["deadline_at"] == 191.0
        events.append("bounded")
        return verification.InferenceVerification(
            static_evidence=evidence, max_batches=2, unavailable_reason="CPU fixture"
        )

    monkeypatch.setattr(adapter.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(source_binding, "measurement_sources", pin)
    monkeypatch.setattr(adapter, "run_isolated_preflight", inspect)
    monkeypatch.setattr(verification, "verify_inference_refusal", verify)
    with bind_inference_preflight_policy(InferencePreflightPolicy(max_batches=2)):
        result = _invoke(tmp_path)
    assert events == (["pin", "static", "bounded"] if dispatch else ["pin", "static"])
    assert ("inference_verification" in result) is dispatch
    assert result["preflight_outcome"] == outcome
    if evidence is not None:
        assert result["static_preflight_evidence"] == evidence.model_dump()


def test_historical_static_only_policy_never_dispatches_verification(tmp_path, monkeypatch):
    """Even an eligible refusal stays static when the task requests historical policy."""
    evidence = StaticPreflightEvidence(phases=(_phase("training"), _phase("inference", vram=True)))

    def forbidden(*args, **kwargs):
        pytest.fail("static_only reached bounded measurement source inspection or execution")

    def inspect(spec, **kwargs):
        assert spec.candidate_sources is None
        return IsolatedProbeResult(
            label=spec.label, outcome="STATIC_PREFLIGHT_REFUSAL", static_preflight_evidence=evidence
        )

    monkeypatch.setattr(source_binding, "measurement_sources", forbidden)
    monkeypatch.setattr(verification, "verify_inference_refusal", forbidden)
    monkeypatch.setattr(adapter, "run_isolated_preflight", inspect)
    with bind_inference_preflight_policy(InferencePreflightPolicy(mode="static_only")):
        result = _invoke(tmp_path)
    assert result["feasible"] is False
    assert result["preflight_outcome"] == "STATIC_PREFLIGHT_REFUSAL"
    assert "inference_verification" not in result
    assert result["static_preflight_evidence"] == evidence.model_dump()


@pytest.mark.parametrize("state", ["matched", "changed_sources", "unpinned", "expired"])
def test_verification_requires_source_continuity_and_spends_only_remaining_budget(
    tmp_path, monkeypatch, state
):
    """A stale source, missing pin, or spent deadline must never reach the GPU runner."""
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(tmp_path))
    plugin_dir = tmp_path / "models"
    plugin_dir.mkdir()
    plugin = plugin_dir / "candidate.py"
    plugin.write_text("# implementation inspected by static worker\n")
    hardware = SimpleNamespace(
        **_snapshot().model_dump(exclude={"device_index"}),
        active_device_uuid="GPU-selected",
        # The nested active-device record owns this index, not a top-level hint.
        logical_index=0,
        devices=[SimpleNamespace(uuid="GPU-selected", physical_index=3, logical_index=1)],
    )
    snapshot = adapter.build_hardware_snapshot(hardware)
    assert snapshot.device_index == 1
    probe = evaluation_probe(tmp_path, rows=7)
    spec = IsolatedProbeSpec(
        label="bounded-source-continuity",
        model_type="synthetic_candidate",
        model_config_payload={"width": 17},
        train_config={"batch_size": 3},
        loss_config={"loss_type": "smooth_l1"},
        hardware=snapshot,
        task_probe_data=probe,
        plugin_dir=str(plugin_dir),
        loss_dir=str(tmp_path / "losses"),
        candidate_sources=source_binding.measurement_sources(
            environ=subprocess_env(plugin_dir=str(plugin_dir), loss_dir=str(tmp_path / "losses"))
        ),
        result_path=str(tmp_path / "static.json"),
        worker_memory_limit_bytes=2 * 1024**3,
    )
    evidence = StaticPreflightEvidence(phases=(_phase("training"), _phase("inference", vram=True)))
    if state == "changed_sources":
        plugin.write_text("# different implementation after static inspection\n")
    elif state == "unpinned":
        spec = spec.model_copy(update={"candidate_sources": None})
    deadline_at = 99.0 if state == "expired" else 150.0
    monkeypatch.setattr(verification.time, "monotonic", lambda: 100.0)

    class Dispatched(Exception):
        pass

    def capture(dispatched, *, device, deadline_at):
        assert state == "matched", "an unavailable observation reached GPU execution"
        assert deadline_at == 150.0
        assert dispatched.request.deadline_seconds == 50.0
        assert dispatched.max_phase_seconds == 50.0
        assert dispatched.sampler_ready_timeout_seconds == 50.0
        assert dispatched.device == "cuda:1"
        assert device.uuid == "GPU-selected"
        assert device.logical_index == 1
        assert dispatched.request.device_uuid == "GPU-selected"
        assert dispatched.request.phase == "inference"
        assert dispatched.inference_batch_size == 11
        assert dispatched.inference_batches == 2
        assert dispatched.model_config_payload == {"width": 17}
        assert dispatched.task_probe_data == probe
        assert dispatched.worker_memory_limit_bytes == 2 * 1024**3
        assert dispatched.inference_binding is not None
        raise Dispatched

    monkeypatch.setattr(verification, "run_prephase_measurement", capture)
    kwargs = dict(
        static_evidence=evidence,
        static_spec=spec,
        hardware_context=hardware,
        policy=InferencePreflightPolicy(max_batches=2),
        deadline_at=deadline_at,
    )
    if state == "matched":
        with pytest.raises(Dispatched):
            verification.verify_inference_refusal(**kwargs)
    else:
        result = verification.verify_inference_refusal(**kwargs)
        assert result.assessment[0] == "unavailable"
        assert result.measurement is None
        expected = (
            "deadline was spent" if state == "expired" else "sources changed or were not pinned"
        )
        assert expected in result.unavailable_reason
