"""Earlier-attempt history carried by a final generation or implementation failure.

A node that retries (the implementor's repair loop, the workflow's
implement-validate loop) used to report only its last error. That string is
what reaches the proposer's ``previous_failures``, so the proposer lost the
cause an earlier attempt exposed and proposed the same thing again (issue
#1538, user report #1530). Callers keep the final error where it was and
append the block rendered here.

Bound: one line per distinct earlier error string, so a history never exceeds
the caller's configured attempt count (``max_retries + 1`` or
``max_impl_attempts``), and each line is the exact error string an earlier
retry already carried to its own LLM request. No character cap is applied: a
cap would be a guess and could cut the very cause this block exists to carry.
Rendering is a pure function of the ordered history, so it is deterministic.

``proposal.failure_attempt_history`` is a published prompt boundary. Callers
enter it only when an earlier attempt exists, so a single-attempt failure is
byte-identical to the pre-#1538 text under native and historical profiles; an
experiment-owned profile restores the pre-#1538 text by returning ``""``.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent.prompt_rendering import prompt_boundary


def earlier_attempts_block(
    earlier: Sequence[tuple[int, str]], final_error: str, *, heading: str, unit: str
) -> str:
    """The earlier-attempt block, or ``""`` when the failure had a single attempt.

    ``earlier`` holds ``(attempt_number, error)`` pairs in chronological order,
    excluding the final attempt whose error is ``final_error``.
    """
    if not earlier:
        return ""
    return render_earlier_attempts(list(earlier), final_error, heading=heading, unit=unit)


@prompt_boundary("proposal.failure_attempt_history")
def render_earlier_attempts(
    earlier: list[tuple[int, str]], final_error: str, *, heading: str, unit: str
) -> str:
    """Render ``heading`` and one line per distinct earlier error, oldest first.

    Identical error strings share one line naming every attempt that produced
    them, ordered by first occurrence. An earlier error equal to the final one
    is written as a back-reference instead of being repeated.
    """
    attempts_by_error: dict[str, list[int]] = {}
    for number, error in earlier:
        attempts_by_error.setdefault(error, []).append(number)
    lines = [heading]
    for error, numbers in attempts_by_error.items():
        label = f"{unit} {numbers[0]}"
        if len(numbers) > 1:
            label = f"{unit}s {', '.join(str(n) for n in numbers)}"
        text = "same error as the final attempt" if error == final_error else error
        lines.append(f"  {label}: {text}")
    return "\n".join(lines)
