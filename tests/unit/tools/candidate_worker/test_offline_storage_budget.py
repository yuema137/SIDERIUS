"""Elapsed fixture I/O must reduce the real validator's transported worker budget."""

import importlib
from types import SimpleNamespace

import pytest

from agent.skills.generated_pytest import PytestLimit
from tools.candidate_worker import budget as budget_owner
from tools.candidate_worker import launch_candidate
from tools.candidate_worker.budget import WorkerBudget
from tools.candidate_worker.models import CandidateRunRequest

from .test_native import native_runner as native_runner


def test_validator_receives_remaining_budget_after_fixture_io(
    prepared: CandidateRunRequest, native_runner: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resetting or dropping the budget at native validation must fail this witness."""
    now = [0.0]
    monkeypatch.setattr(budget_owner, "time", SimpleNamespace(monotonic=lambda: now[0]))
    start = WorkerBudget.start

    def after_slow_io(cls: type[WorkerBudget], timeout_seconds: float) -> WorkerBudget:
        budget = start(timeout_seconds)
        now[0] = 90.0  # One elapsed interval; subsequent child anchors share this clock.
        return budget

    monkeypatch.setattr(WorkerBudget, "start", classmethod(after_slow_io))
    validator = importlib.import_module("nodes.ml_code_validator_agent.ml_code_validator_agent")
    run_pytest = validator.run_generated_pytest
    limits: list[PytestLimit | None] = []

    def observed_pytest(
        path: str, env: dict[str, str], *, limit: PytestLimit | None = None
    ) -> tuple[bool, str]:
        limits.append(limit)
        return run_pytest(path, env, limit=limit)

    monkeypatch.setattr(validator, "run_generated_pytest", observed_pytest)
    receipt = launch_candidate(prepared)
    assert receipt.status == "accepted", receipt.error
    assert receipt.validation_passed is True
    assert limits
    assert all(
        limit is not None
        and limit.source == "worker_budget"
        and limit.seconds == prepared.timeout_seconds - 90.0
        for limit in limits
    )
