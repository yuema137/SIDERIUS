"""Operator budget-file intake and its run-invariant projection.

The operator declares a ``HostBudget`` in one JSON file (decision B3-Q8: no
environment variable). ``load_host_budget_file`` parses and validates it once;
consumers read the returned typed object, never the raw file. The scheduling
mode a budget implies is a canonical run invariant (decision B3-Q7); the
budget's digest and concurrency limit are provenance. Contract: scheduling.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from core.runtime_control.scheduling import BudgetSource, HostBudget, PositiveCount, Sha256Hex

#: ``serial``: no budget, one unit at a time (every existing run).
#: ``parallel-v1``: budgeted dispatch with drain-on-failure trace semantics.
SchedulingMode = Literal["serial", "parallel-v1"]
#: A budget is a few slots and scalars; anything larger is not a budget file.
MAX_HOST_BUDGET_FILE_BYTES = 64 * 1024


class HostBudgetFileError(ValueError):
    """The budget file is unreadable, malformed or not a valid ``HostBudget``."""


def _refuse_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise HostBudgetFileError(f"duplicate JSON keys {duplicates}: the declaration is ambiguous")
    return dict(pairs)


def load_host_budget_file(path: str | Path) -> HostBudget:
    """Read one operator budget file into a validated ``HostBudget``.

    The file holds every ``HostBudget`` field except ``source``, which intake
    sets to ``"file"``; a file that declares ``source`` itself is refused so
    provenance cannot be authored. Duplicate keys are refused rather than
    resolved last-wins. Nothing is defaulted, discovered or read from the
    environment. The path must be a regular file of at most
    ``MAX_HOST_BUDGET_FILE_BYTES``; it is read once, bounded, before parsing.
    """
    budget_path = Path(path)
    if not budget_path.is_file():
        raise HostBudgetFileError(f"host budget file {budget_path} is not a regular file")
    try:
        with budget_path.open("rb") as handle:
            data = handle.read(MAX_HOST_BUDGET_FILE_BYTES + 1)
        if len(data) > MAX_HOST_BUDGET_FILE_BYTES:
            raise HostBudgetFileError(f"exceeds {MAX_HOST_BUDGET_FILE_BYTES} bytes")
        text = data.decode("utf-8")
        payload = json.loads(text, object_pairs_hook=_refuse_duplicate_keys)
    except HostBudgetFileError as exc:
        raise HostBudgetFileError(f"host budget file {budget_path}: {exc}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostBudgetFileError(f"host budget file {budget_path} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise HostBudgetFileError(f"host budget file {budget_path} must contain a JSON object")
    if "source" in payload:
        raise HostBudgetFileError(
            f"host budget file {budget_path} declares 'source'; intake records it as 'file'"
        )
    try:
        return HostBudget.model_validate({**payload, "source": "file"})
    except ValidationError as exc:
        raise HostBudgetFileError(f"host budget file {budget_path} is invalid: {exc}") from exc


class HostBudgetProvenance(BaseModel):
    """What a parallel run's lock records about its budget; never compared."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    digest: Sha256Hex
    max_concurrent_units: PositiveCount
    source: BudgetSource

    @classmethod
    def of(cls, budget: HostBudget) -> HostBudgetProvenance:
        return cls(
            digest=budget.digest,
            max_concurrent_units=budget.max_concurrent_units,
            source=budget.source,
        )


def scheduling_mode_for(budget: HostBudget | None) -> SchedulingMode:
    """The one rule: a declared budget selects parallel-v1; none keeps serial."""
    return "serial" if budget is None else "parallel-v1"
