"""Portable ceilings must follow declared limits and actual device evidence.

These tests exercise precedence and production admission, not just schema
declarations. No hardware, dataset, provider or training is used.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from core.runtime_control.admission import GpuAdmissionPolicy
from core.runtime_control.pair_admission import (
    HOST_VRAM_QUOTA_MIB_ENV,
    PAIR_CEILING_GIB_ENV,
    PairMember,
    _cli,
    evaluate_pair_admission,
    evaluate_resolved_pair_admission,
    resolve_gpu_ceiling,
)
from core.runtime_control.process_visibility import PROCESS_VISIBILITY_ENV
from tests.unit.core.test_retained_gpu_occupancy import decide, snapshot
from workflows.run_config import WorkflowLaunchConfig


@pytest.fixture(autouse=True)
def clean_limits(monkeypatch):
    for variable in (HOST_VRAM_QUOTA_MIB_ENV, PAIR_CEILING_GIB_ENV, PROCESS_VISIBILITY_ENV):
        monkeypatch.delenv(variable, raising=False)


@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.parametrize("capacity", [8, 80, 192])
def test_real_admission_uses_actual_capacity_without_a_local_ceiling(
    monkeypatch, isolated, capacity
):
    if isolated:
        monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")
    result = decide(
        snapshot(total=capacity * 1024, own=capacity * 256),
        requirement_mib=capacity * 512,
        ceiling_gib=None,
    )
    assert result.admitted
    assert result.evidence["effective_ceiling_gib"] == capacity
    assert result.evidence["configured_ceiling_gib"] is None
    assert result.evidence["ceiling_resolution"]["operator_source"] == "none"
    assert result.evidence["aggregate_gib"] == capacity * 0.75


@pytest.mark.parametrize("isolated", [False, True])
def test_host_quota_constrains_even_an_explicit_higher_ceiling(monkeypatch, isolated):
    if isolated:
        monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")
    monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "1200")
    result = decide(snapshot(total=80 * 1024), ceiling_gib=72)
    assert not result.admitted
    assert result.evidence["effective_ceiling_gib"] == 1200 / 1024
    assert result.evidence["ceiling_resolution"]["operator_ceiling_gib"] == 72
    assert result.evidence["aggregate_gib"] == 1500 / 1024


@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.parametrize("bad", ["not-a-number", "nan", "inf", "-inf", "0"])
def test_bad_policy_becomes_a_decision_not_an_exception_fallback(monkeypatch, isolated, bad):
    if isolated:
        monkeypatch.setenv(PROCESS_VISIBILITY_ENV, "namespace_limited")
    monkeypatch.setenv(PAIR_CEILING_GIB_ENV, bad)
    result = decide(ceiling_gib=None)
    assert not result.admitted
    assert result.reason_code == (
        "environment_headroom_unproven" if isolated else "policy_unavailable"
    )
    assert PAIR_CEILING_GIB_ENV in result.reason


def test_explicit_source_overrides_bad_shadowed_environment_but_not_bad_quota(monkeypatch):
    monkeypatch.setenv(PAIR_CEILING_GIB_ENV, "not-selected")
    limits = resolve_gpu_ceiling(ceiling_gib=48, measured_capacity_gib=80)
    assert (limits.operator_source, limits.effective_gib) == ("caller", 48)
    monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "bad-quota")
    with pytest.raises(ValueError, match=HOST_VRAM_QUOTA_MIB_ENV):
        resolve_gpu_ceiling(ceiling_gib=48, measured_capacity_gib=80)


def test_resolved_arithmetic_does_not_reread_changed_environment(monkeypatch):
    monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "20480")
    limits = resolve_gpu_ceiling(ceiling_gib=72, measured_capacity_gib=80)
    monkeypatch.setenv(HOST_VRAM_QUOTA_MIB_ENV, "bad-after-resolution")
    decision = evaluate_resolved_pair_admission(
        [PairMember(run_name="one", predicted_peak_vram_gb=21, provenance="test")],
        limits=limits,
    )
    assert (decision.feasible, decision.ceiling_gib, decision.host_quota_gib) == (False, 20, 20)


def test_finite_member_demands_cannot_overflow_into_a_decision():
    members = [
        PairMember(run_name=str(i), predicted_peak_vram_gb=1e308, provenance="test")
        for i in range(2)
    ]
    with pytest.raises(ValueError, match="overflowed"):
        evaluate_pair_admission(members, ceiling_gib=1e308)


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_public_limits_and_policy_do_not_coerce_invalid_values_into_permission(value):
    with pytest.raises(ValueError):
        resolve_gpu_ceiling(ceiling_gib=value, measured_capacity_gib=80)
    with pytest.raises(ValidationError):
        GpuAdmissionPolicy(ceiling_gib=value)
    with pytest.raises(ValidationError):
        PairMember(run_name="one", predicted_peak_vram_gb=value, provenance="test")
    # The transit dataclass preserves the supplied value; the existing tuner
    # intake must reject it before Pydantic can turn True into a valid 1 GiB.
    launch = WorkflowLaunchConfig(gpu_pair_ceiling_gib=value)
    with pytest.raises(ValidationError, match="gpu_pair_ceiling_gib"):
        HyperparamTuningInput(
            model_type="synthetic", gpu_pair_ceiling_gib=launch.gpu_pair_ceiling_gib
        )


@pytest.mark.parametrize("args", [["--caps", "a=1"], ["--caps", "a=inf", "--ceiling-gib", "8"]])
def test_cli_reports_missing_or_invalid_limits_as_usage_errors(args, capsys):
    with pytest.raises(SystemExit) as error:
        _cli(args)
    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "error:" in stderr
    assert "Traceback" not in stderr
