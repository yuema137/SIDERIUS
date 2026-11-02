"""Success receipts survive slow fixture I/O without bypassing worker supervision."""

from tools.candidate_worker import launch_candidate
from tools.candidate_worker.budget import WorkerBudget

from .test_native import native_runner as native_runner


def test_native_success_after_fixture_io_exceeds_the_old_budget(
    prepared, native_runner, monkeypatch
):
    """Reverting the fixture budget rejects real validator pytest after 90 seconds of I/O."""
    start = WorkerBudget.start

    def after_slow_io(cls, timeout_seconds: float) -> WorkerBudget:
        budget = start(timeout_seconds)
        # Model elapsed fixture publication without sleeping or changing the clock
        # used by the actual validator subprocess supervisor.
        return WorkerBudget(deadline=budget.deadline - 90.0)

    monkeypatch.setattr(WorkerBudget, "start", classmethod(after_slow_io))
    receipt = launch_candidate(prepared)
    assert receipt.status == "accepted", receipt.error
    assert receipt.validation_passed is True
