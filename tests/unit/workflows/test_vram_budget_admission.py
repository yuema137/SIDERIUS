"""#1044: one owner refuses malformed operator VRAM budgets on every launch path.

Before the fix the tuner fields accepted any float and ``ProposalInput``
accepted 0 and inf. The direct workflow launched with any of these; the
candidate ingress refused negatives but admitted 0 (which the VRAM gate read as
"reject every model" and feedback as "no budget") and inf (which overflows in
the gate's ``int(budget * GB)``).
"""

from __future__ import annotations

import pytest

from workflows import model_exploration
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.run_config import WorkflowLaunchConfig

FIELDS = ("trial_vram_budget_gb", "formal_vram_budget_gb")


class _StartupReached(Exception):
    pass


def _stop_startup(*args, **kwargs):
    raise _StartupReached


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
def test_direct_workflow_refuses_malformed_vram_budget(tmp_path, monkeypatch, field, value):
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", _stop_startup)
    with pytest.raises(ValueError, match=f"is refused by HyperparamTuningInput.{field}"):
        model_exploration.run_workflow(
            workspace=str(tmp_path / "uncreated-run"),
            run_name="preflight",
            launch=WorkflowLaunchConfig(**{field: value}),
        )


def test_direct_workflow_refuses_an_inactive_negative_formal_budget(tmp_path, monkeypatch):
    """Only the active budget reached ProposalInput, so a negative formal
    budget behind a trial budget launched on the CLI path but not candidate."""
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", _stop_startup)
    launch = WorkflowLaunchConfig(trial_vram_budget_gb=8.0, formal_vram_budget_gb=-1.0)
    with pytest.raises(ValueError, match="formal_vram_budget_gb"):
        model_exploration.run_workflow(
            workspace=str(tmp_path / "uncreated-run"), run_name="preflight", launch=launch
        )


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [0.0, float("inf")])
def test_candidate_ingress_refuses_zero_and_infinite_vram_budget(field, value):
    with pytest.raises(ValueError, match=f"HyperparamTuningInput.{field}"):
        CandidateTrainingSettings(launch=WorkflowLaunchConfig(**{field: value}))


@pytest.mark.parametrize("field", FIELDS)
def test_positive_vram_budget_still_launches(tmp_path, monkeypatch, field):
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", _stop_startup)
    with pytest.raises(_StartupReached):
        model_exploration.run_workflow(
            workspace=str(tmp_path / "uncreated-run"),
            run_name="preflight",
            launch=WorkflowLaunchConfig(**{field: 12.0}),
        )
