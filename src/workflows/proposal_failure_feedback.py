"""Proposer feedback for a proposal whose implementation attempts all failed (#1538).

The native exploration loop gives each proposal up to ``max_impl_attempts``
implement-validate attempts and then reports one ``previous_failures`` entry
to the next proposal. That entry used to carry only the last validation
rejection, or only the exception that ended the proposal, so earlier
rejections that named the real cause never reached the proposer. These pure
helpers build the entry from the recorded per-attempt validation failures;
``run_workflow`` only records them and calls these helpers.

The earlier-attempt block, its bound and its prompt boundary are owned by
``agent.prompt_templates.attempt_history``. A proposal with at most one
recorded rejection produces exactly the pre-#1538 entry.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent.prompt_templates.attempt_history import earlier_attempts_block

_HEADING = "Earlier implementation attempts for this proposal failed validation (oldest first):"
_UNIT = "Implementation attempt"


def exhausted_validation_feedback(validation_failures: Sequence[tuple[int, str]]) -> str:
    """Entry for a proposal whose every implementation failed validation.

    ``validation_failures`` holds ``(impl_attempt, error_message)`` in order.
    The final rejection leads, as before; earlier rejections follow.
    """
    if not validation_failures:
        return "Unknown error"
    *earlier, (_, final) = validation_failures
    block = earlier_attempts_block(earlier, final, heading=_HEADING, unit=_UNIT)
    return f"{final}\n\n{block}" if block else final


def implementation_error_feedback(
    error_message: str, validation_failures: Sequence[tuple[int, str]]
) -> str:
    """Entry for a proposal ended by an exception after earlier rejections.

    ``error_message`` is the rendered exception; validation rejections
    recorded before it follow, since the exception alone hides them.
    """
    block = earlier_attempts_block(validation_failures, error_message, heading=_HEADING, unit=_UNIT)
    return f"{error_message}\n\n{block}" if block else error_message
