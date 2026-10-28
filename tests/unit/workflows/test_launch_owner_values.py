"""#1045: timeouts, safety factors and the degenerate penalty refuse inf/NaN.

Their tuner owners declared only ``gt``/``ge`` bounds, which accept ``inf``
(and the penalty accepted any float), so an infinite timeout silently removed
its bound and an infinite safety factor made every forecast infeasible. The
direct workflow also never checked these values before composition, and the
candidate ingress accepted them.
"""

from __future__ import annotations

import pytest

from workflows import model_exploration
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.run_config import WorkflowLaunchConfig

INF = float("inf")
NAN = float("nan")
REFUSED = [
    ("vram_probe_step_timeout_seconds", INF),
    ("vram_preflight_total_timeout_seconds", INF),
    ("vram_preflight_host_memory_limit_gb", INF),
    ("runtime_safety_factor", INF),
    ("runtime_trial_safety_factor", INF),
    ("runtime_formal_safety_factor", INF),
    ("runtime_watchdog_safety_factor", INF),
    ("runtime_watchdog_floor_seconds", INF),
    ("runtime_verification_max_wall_seconds", INF),
    ("validation_max_phase_seconds", INF),
    ("degenerate_penalty_score", -INF),
    ("degenerate_penalty_score", INF),
    ("degenerate_penalty_score", NAN),
]


class _StartupReached(Exception):
    pass


def _stop_startup(*args, **kwargs):
    raise _StartupReached


@pytest.mark.parametrize("field,value", REFUSED)
def test_direct_workflow_refuses_nonfinite_owner_value_before_composition(
    tmp_path, monkeypatch, field, value
):
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", _stop_startup)
    launch = WorkflowLaunchConfig(**{field: value})
    if field == "validation_max_phase_seconds":
        # Its owner also requires the watchdog that enforces it.
        launch = WorkflowLaunchConfig(**{field: value, "runtime_watchdog_enabled": True})
    with pytest.raises(ValueError, match=f"is refused by HyperparamTuningInput.{field}"):
        model_exploration.run_workflow(
            workspace=str(tmp_path / "uncreated-run"), run_name="preflight", launch=launch
        )
    assert not (tmp_path / "uncreated-run").exists()


@pytest.mark.parametrize("field,value", REFUSED)
def test_candidate_ingress_refuses_the_same_values(field, value):
    extra = {"runtime_watchdog_enabled": True} if field == "validation_max_phase_seconds" else {}
    with pytest.raises(ValueError, match=f"HyperparamTuningInput.{field}"):
        CandidateTrainingSettings(launch=WorkflowLaunchConfig(**{field: value}, **extra))
