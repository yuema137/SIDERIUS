"""Numbered ``previous_failures`` items in the proposer's reasoning prompt (#1555).

Each entry is one numbered item, ``  <n>. <entry>``. A multi-line entry (an
implementor failure with its earlier attempts, a validation history) used to
continue at column 0, so its later lines read like new list items. Its
continuation lines are now indented under the item text. Blank lines stay
empty, so no line gains trailing whitespace.

``proposal.failure_entry_layout`` is a published prompt boundary entered only
for an entry that spans several lines; a single-line entry is rendered natively
and keeps its bytes. An experiment-owned profile restores the pre-#1555 layout
by returning ``f"  {number}. {entry}"``.

The pipeline stages serialize ``previous_failures`` as JSON strings and do not
use this layout.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent.prompt_rendering import prompt_boundary


def previous_failure_items(failures: Sequence[str]) -> list[str]:
    """One rendered numbered item per entry, in order."""
    return [
        render_multiline_failure_entry(number, entry) if "\n" in entry else f"  {number}. {entry}"
        for number, entry in enumerate(failures, 1)
    ]


@prompt_boundary("proposal.failure_entry_layout")
def render_multiline_failure_entry(number: int, entry: str) -> str:
    """``entry`` as item ``number`` with its non-blank continuation lines indented."""
    prefix = f"  {number}. "
    indent = " " * len(prefix)
    first, *rest = entry.split("\n")
    continued = [f"{indent}{line}" if line.strip() else "" for line in rest]
    return "\n".join([f"{prefix}{first}", *continued])
