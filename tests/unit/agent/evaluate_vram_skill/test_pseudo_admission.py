"""CPU pseudo admission never constructs GPU evidence; real admission stays literal."""

from types import SimpleNamespace

import pytest

from agent.skills.evaluate_vram_skill import preflight_adapter as adapter
from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeResult
from core.execution_calibration import MalformedCeilingOverride


def _run(tmp_path, **kwargs):
    return adapter.run_production_preflight(
        model_type="stub",
        model_config={},
        train_config={},
        loss_config={},
        vram_budget_gb=12.0,
        workspace=tmp_path,
        label="candidate",
        plugin_dir=None,
        loss_dir=None,
        **kwargs,
    )


@pytest.mark.parametrize("gpu_available", [False, True])
def test_pseudo_uses_declared_roles_without_gpu_measurement(tmp_path, monkeypatch, gpu_available):
    """Reverting pseudo dispatch reaches the forbidden snapshot constructor."""
    monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "training=16,inference=8,scoring=4")

    def forbidden(*args, **kwargs):
        pytest.fail("pseudo admission must not discover or measure GPU capacity")

    monkeypatch.setattr(adapter, "build_hardware_snapshot", forbidden)
    monkeypatch.setattr(adapter, "run_isolated_preflight", forbidden)
    result = _run(
        tmp_path,
        hardware_context=SimpleNamespace(device_available=gpu_available),
        pseudo_training=True,
    )
    assert result["preflight_outcome"] == "PSEUDO_NO_EXECUTION_ENVELOPE"
    assert result["pseudo_admission"] == {
        "decision": "pseudo: no execution envelope (StubSandbox launches no subprocess)",
        "training": {"role": "training", "gib": 16, "source": "environment"},
        "inference": {"role": "inference", "gib": 8, "source": "environment"},
        "scoring": {"role": "scoring", "gib": 4, "source": "environment"},
    }
    assert "estimated_gb" not in result
    assert (tmp_path / "preflight_workers/candidate.json").is_file()


@pytest.mark.parametrize("declaration", [None, "0", "training=16,inference=0,scoring=4"])
def test_pseudo_needs_no_execution_envelope(tmp_path, monkeypatch, declaration):
    """An omitted or zero ceiling must not prevent a no-subprocess smoke."""
    monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
    if declaration is not None:
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", declaration)
    result = _run(tmp_path, hardware_context=None, pseudo_training=True)
    assert result["feasible"] is True
    assert result["pseudo_admission"]["decision"] == (
        "pseudo: no execution envelope (StubSandbox launches no subprocess)"
    )
    assert result["pseudo_admission"]["inference"]["gib"] == (None if declaration is None else 0)


def test_pseudo_still_validates_optional_override(tmp_path, monkeypatch):
    """Pseudo routing must not discard a malformed operator declaration."""
    monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "training=16,inference=bad,scoring=4")
    with pytest.raises(MalformedCeilingOverride):
        _run(tmp_path, hardware_context=None, pseudo_training=True)
    assert not (tmp_path / "preflight_workers").exists()


def test_real_gpu_admission_preserves_fixed_literal_witness(tmp_path, monkeypatch):
    """Pseudo configuration must not replace the real worker's cap or result."""
    monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "16")
    hardware = SimpleNamespace(
        usable_cap_bytes=26843545600,
        usable_cap_gb=25.0,
        total_memory_bytes=34359738368,
        total_memory_gb=32.0,
        device_name="test GPU",
        device_available=True,
        fingerprint="fixed-gpu",
    )

    def worker(spec, *, deadline_seconds):
        assert spec.effective_cap_gb() == 12.0
        assert spec.hardware.total_memory_bytes == 34359738368
        assert deadline_seconds == 900.0
        return IsolatedProbeResult(label="candidate", outcome="MEASURED_PEAK_ABOVE_VRAM_CAP")

    monkeypatch.setattr(adapter, "run_isolated_preflight", worker)
    result = _run(tmp_path, hardware_context=hardware)
    assert result == {
        "status": "success",
        "truncated": False,
        "feasible": False,
        "preflight_outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP",
        "message": "",
        "verdict": "",
        "suggestion": "",
        "effective_vram_limit_gb": 12.0,
        "effective_limit_source": "operator_vram_budget",
        "operator_vram_budget_gb": 12.0,
    }
