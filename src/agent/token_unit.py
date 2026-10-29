"""Token-ledger unit attribution for concurrently dispatched graph units (B3-4b).

A parallel unit child binds its unit once; every ``TokenUsageRow`` an
``LLMBridge`` writes while it is bound carries ``unit_id`` and the unit's own
``unit_sequence`` (1, 2, ...). The counter belongs to the unit, so every bridge
the unit constructs shares it. Unbound (serial runs), rows are unchanged.
"""

import itertools
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TypedDict


@dataclass
class TokenUnit:
    unit_id: str
    sequence: itertools.count = field(default_factory=lambda: itertools.count(1))


class TokenUnitFields(TypedDict, total=False):
    unit_id: str
    unit_sequence: int


_UNIT: ContextVar[TokenUnit | None] = ContextVar("token_unit", default=None)


@contextmanager
def bind_token_unit(unit_id: str) -> Iterator[TokenUnit]:
    unit = TokenUnit(unit_id)
    token = _UNIT.set(unit)
    try:
        yield unit
    finally:
        _UNIT.reset(token)


def token_unit_fields() -> TokenUnitFields:
    """``unit_id``/``unit_sequence`` for the next row, or nothing when unbound."""
    unit = _UNIT.get()
    if unit is None:
        return TokenUnitFields()
    return TokenUnitFields(unit_id=unit.unit_id, unit_sequence=next(unit.sequence))
