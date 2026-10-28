"""The run seed an operation admission binds, and its readback check (issue #983).

Contract: ``candidate-operations-contract.md`` "Run seed".

Admission is the operations entry boundary: inside the store lock and before
``claim()``, a ``prepare``, ``prepare_reusable`` or ``candidate`` submission
binds its request's explicit ``run_seed`` or generates one. An idempotent
resubmission returns the existing record first, so a retry never mints a second
seed. A ``candidate_loop_resume`` copies its root record's seed; it never
generates one.
"""

from core.seeding import RunSeedBinding, resolve_run_seed

from .models import SEEDED_SUBMISSIONS, OperationFailure, OperationRecord, OperationSubmission


def admission_seed(
    submission: OperationSubmission, loop_root: OperationRecord | None = None
) -> RunSeedBinding | None:
    """The binding a new record carries: explicit or generated, inherited, or none.

    ``loop_root`` is the root record of a ``candidate_loop_resume``.
    """
    if isinstance(submission, SEEDED_SUBMISSIONS):
        return resolve_run_seed(submission.request.run_seed)
    if submission.kind == "candidate_loop_resume":
        if loop_root is None:
            raise OperationFailure("integrity", "loop resume admission lacks its root record")
        return require_root_seed(loop_root)
    return None


def require_root_seed(root: OperationRecord) -> RunSeedBinding:
    """A loop root admitted before the seed contract cannot be continued on this build."""
    if root.run_seed is None:
        raise OperationFailure(
            "loop_resume",
            "this loop predates recorded run seeds: its operation record has no "
            "run_seed, so a resumed segment could not prove it continues the same "
            "seed. Start a fresh candidate run (a new operation and workspace, "
            "optionally with --run-seed N); the old records stay readable",
        )
    return root.run_seed


def require_recorded_seed(record: OperationRecord, recorded: RunSeedBinding | None) -> None:
    """A native receipt records exactly the seed its operation admitted.

    ``recorded`` is the receipt's binding; a pre-seed record must have a
    pre-seed receipt.
    """
    if recorded != record.run_seed:
        raise OperationFailure("integrity", "native receipt run seed disagrees with admission")
