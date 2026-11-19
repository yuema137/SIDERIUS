"""Rejection history of one proposal's implementation attempts (#1538, #1553).

The native exploration loop gives each proposal up to ``max_impl_attempts``
implement-validate attempts and then reports one ``previous_failures`` entry
to the next proposal. That entry used to carry only the last validation
rejection, or only the exception that ended the proposal, so earlier
rejections that named the real cause never reached the proposer. Likewise
each implementation attempt saw only the latest rejection, so the implementor
could oscillate between mistakes (#1553). These pure helpers build both texts
from the recorded per-attempt validation failures; ``run_workflow`` only
records them and calls these helpers.

The earlier-attempt block, its bound and its prompt boundary are owned by
``agent.prompt_templates.attempt_history``. With at most one recorded
rejection both texts are exactly the pre-#1538 / pre-#1553 strings.

An implementor that runs out of repairs raises ``RepairExhaustedError``; its
entry keeps the cause and drops the assembled source (#1554, see
:func:`repair_exhausted_entry`).
"""

from __future__ import annotations

from collections.abc import Sequence

from agent.prompt_templates.attempt_history import (
    RepairExhaustedError,
    earlier_attempts_block,
    render_repair_failure_cause,
)

_HEADING = "Earlier implementation attempts for this proposal failed validation (oldest first):"
_UNIT = "Implementation attempt"


def _rejection_history(validation_failures: Sequence[tuple[int, str]]) -> str:
    """The latest rejection followed by every earlier one; non-empty input only."""
    *earlier, (_, latest) = validation_failures
    block = earlier_attempts_block(earlier, latest, heading=_HEADING, unit=_UNIT)
    return f"{latest}\n\n{block}" if block else latest


def exhausted_validation_feedback(validation_failures: Sequence[tuple[int, str]]) -> str:
    """Entry for a proposal whose every implementation failed validation.

    ``validation_failures`` holds ``(impl_attempt, error_message)`` in order.
    The final rejection leads, as before; earlier rejections follow.
    """
    if not validation_failures:
        return "Unknown error"
    return _rejection_history(validation_failures)


def next_attempt_validation_feedback(
    validation_failures: Sequence[tuple[int, str]],
) -> str | None:
    """``previous_validation_failure`` for the proposal's next implementation (#1553).

    ``None`` before any rejection. Otherwise the latest rejection leads, as
    before, and every earlier rejection follows, so the implementor cannot
    oscillate back to a mistake an earlier attempt was already rejected for.
    """
    if not validation_failures:
        return None
    return _rejection_history(validation_failures)


def implementation_error_feedback(
    error_message: str, validation_failures: Sequence[tuple[int, str]]
) -> str:
    """Entry for a proposal ended by an exception after earlier rejections.

    ``error_message`` is the rendered exception; validation rejections
    recorded before it follow, since the exception alone hides them.
    """
    block = earlier_attempts_block(validation_failures, error_message, heading=_HEADING, unit=_UNIT)
    return f"{error_message}\n\n{block}" if block else error_message


def repair_exhausted_entry(exc: RepairExhaustedError) -> str:
    """The ``previous_failures`` entry for an implementor that ran out of repairs.

    The label stays ``Node error: ValueError:``, the type this failure has always
    reported, so only the rendered cause differs from the pre-#1554 entry: the
    headline and earlier-attempt block, plus the source lines the final error
    names, through the ``proposal.failure_cause`` boundary. The full source
    stays in ``str(exc)`` for logs.
    """
    cause = render_repair_failure_cause(exc.cause, exc.final_error, exc.source_heading, exc.source)
    return f"Node error: ValueError: {cause}"
