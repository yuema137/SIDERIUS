"""Report seed calls hard-coded in LLM-generated source (issue #983, Q4).

Contract: ``docs/agent-reference/mechanisms/seeding.md`` "Generated code".

Generated plugins, losses and analysis programs may reseed a generator with
their own constant (``torch.manual_seed(42)``, ``np.random.seed(0)``,
``default_rng(7)``). That seed is part of the generated artifact and is kept
as written: this scan only reads the source and records each such call. It
never modifies, strips or overrides code, and it never reaches a prompt.
Best effort, by call name: it recognises the names below and reports their
calls; keyword-only seeds and other libraries are not covered. Source that
cannot be parsed (syntax, or nesting too deep for the parser) yields no calls;
recorded call text is bounded to ``MAX_CALL_TEXT`` characters.
"""

from __future__ import annotations

import ast
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: Final attribute (or bare name) of a call that seeds or constructs a seeded
#: generator. ``seed`` matches ``random.seed`` and ``np.random.seed``.
_SEEDING_NAMES: Final = frozenset(
    {"manual_seed", "manual_seed_all", "seed", "default_rng", "RandomState", "SeedSequence"}
)


#: Longest recorded call text; longer text is truncated with an ellipsis.
MAX_CALL_TEXT = 200


def _call_text(node: ast.Call, name: str) -> str:
    """The call as written, bounded; a call too deep to unparse keeps its name."""
    try:
        text = ast.unparse(node)
    except (RecursionError, ValueError, MemoryError):
        text = f"{name}(…)"
    return text if len(text) <= MAX_CALL_TEXT else text[: MAX_CALL_TEXT - 1] + "…"


class GeneratedSeedCall(BaseModel):
    """One seeding call found in generated source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    call: str = Field(min_length=1)


def scan_seed_calls(source: str, *, file: str) -> tuple[GeneratedSeedCall, ...]:
    """Every seeding call in ``source``, in source order; read-only."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, ValueError, MemoryError):
        return ()
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        # default_rng() / RandomState() without an argument draw entropy, not a constant.
        if name in _SEEDING_NAMES and (name not in {"default_rng", "RandomState"} or node.args):
            calls.append(
                GeneratedSeedCall(file=file, line=node.lineno, call=_call_text(node, name))
            )
    return tuple(sorted(calls, key=lambda item: (item.line, item.call)))
