"""Earlier-attempt history carried by a failure or a retry request.

A node that retries used to report only its last error. Two consumers lost the
cause an earlier attempt exposed:

* the proposer's ``previous_failures`` received only the final implementor or
  validator error, so it proposed the same thing again (issue #1538, user
  report #1530);
* each retry request (the next implementation attempt's validator feedback,
  the proposer's comparison and causal-reasoning correction requests) showed
  only the latest rejection, so a retry could oscillate back to a mistake an
  earlier attempt was already rejected for (issue #1553).

Callers keep the latest error where it was and append the block rendered here.

Bound: one line per distinct earlier error string, so a history never exceeds
the caller's configured attempt count (``max_retries + 1``,
``max_impl_attempts`` or a stage's correction budget), and each line is the
exact error string an earlier attempt already carried to its own LLM request.
No character cap is applied: a cap would be a guess and could cut the very
cause this block exists to carry. Rendering is a pure function of the ordered
history, so it is deterministic.

``proposal.failure_attempt_history`` is a published prompt boundary. Callers
enter it only when an earlier attempt exists, so a single-attempt failure or a
first retry is byte-identical to the pre-#1538 / pre-#1553 text under native and
historical profiles; an experiment-owned profile restores that text everywhere
by returning ``""``.

Repair exhaustion (#1554). A generate-validate-repair loop that runs out of
repairs raises :class:`RepairExhaustedError`. Its ``str()`` is the full failure
text, last assembled source included, for logs and tracebacks. The proposer's
``previous_failures`` entry is rendered through the ``proposal.failure_cause``
boundary instead: the headline and earlier-attempt block, plus only the source
lines the final error names. An experiment-owned profile restores the
pre-#1554 entry by returning ``cause``, a blank line, ``source_heading`` with a
colon, and ``source`` (exactly the tail of the ``str()`` text).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agent.prompt_rendering import prompt_boundary

_EARLIER_REPAIRS_HEADING = "Earlier attempt errors (oldest first):"
_LINE_REFERENCE = re.compile(r"\bline (\d+)\b")
_MAX_NAMED_LOCATIONS = 3
_EXCERPT_CONTEXT = 1
_MAX_EXCERPT_LINE_CHARS = 160


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


class RepairExhaustedError(ValueError):
    """A generate-validate-repair loop ended with an error after its last repair.

    ``str()`` keeps the established failure text (#1538): the headline with the
    final error, the earlier-attempt block, then the last assembled source. The
    proposer entry is rendered from the parts (:func:`render_repair_failure_cause`),
    so the source never reaches ``previous_failures`` (#1554). The type stays a
    ``ValueError`` for every existing handler.
    """

    def __init__(
        self,
        what: str,
        name: str,
        final_error: str,
        error_history: Sequence[tuple[int, str]],
        source_heading: str,
        source: str,
    ) -> None:
        history = earlier_attempts_block(
            error_history, final_error, heading=_EARLIER_REPAIRS_HEADING, unit="Attempt"
        )
        headline = (
            f"{what} failed after {len(error_history) + 1} attempts for '{name}': {final_error}"
        )
        self.cause = f"{headline}\n\n{history}" if history else headline
        self.final_error = final_error
        self.source_heading = source_heading
        self.source = source
        self._parts = (what, name, final_error, tuple(error_history), source_heading, source)
        super().__init__(f"{self.cause}\n\n{source_heading}:\n{source}")

    def __reduce__(self):
        return (type(self), self._parts)


def _named_source_lines(final_error: str, source: str) -> str:
    """The source lines ``final_error`` names as ``line N``, with one line of context.

    At most :data:`_MAX_NAMED_LOCATIONS` distinct in-range locations, in order of
    first mention; each printed line is cut to :data:`_MAX_EXCERPT_LINE_CHARS`
    and printed once even when two locations share context.
    ``""`` when the error names no line of ``source``.
    """
    lines = source.splitlines()
    named: list[int] = []
    for match in _LINE_REFERENCE.finditer(final_error):
        number = int(match.group(1))
        if 1 <= number <= len(lines) and number not in named:
            named.append(number)
        if len(named) == _MAX_NAMED_LOCATIONS:
            break
    if not named:
        return ""
    width = len(str(len(lines)))
    excerpt = ["Source lines named by the final error:"]
    shown: set[int] = set()
    for number in named:
        first = max(1, number - _EXCERPT_CONTEXT)
        last = min(len(lines), number + _EXCERPT_CONTEXT)
        for current in range(first, last + 1):
            if current in shown:
                continue
            shown.add(current)
            marker = ">" if current in named else " "
            text = lines[current - 1][:_MAX_EXCERPT_LINE_CHARS]
            excerpt.append(f"  {marker} {current:>{width}} | {text}".rstrip())
    return "\n".join(excerpt)


@prompt_boundary("proposal.failure_cause")
def render_repair_failure_cause(
    cause: str, final_error: str, source_heading: str, source: str
) -> str:
    """The proposer's view of a repair-exhausted failure, without the full source.

    ``cause`` is the headline plus earlier-attempt block; the source contributes
    only the lines the final error names (location and key lines). Bounded by
    the cause, which holds at most one line per distinct attempt error, plus at
    most three excerpts of three lines each.
    """
    excerpt = _named_source_lines(final_error, source)
    return f"{cause}\n\n{excerpt}" if excerpt else cause
