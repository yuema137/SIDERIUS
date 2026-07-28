"""Data-ordering control: proposal, operator override, and resolution.

Ordering is the first option to adopt the project-wide configuration
principle (``docs/design/genericity_contract.md`` Seam 2):

    Agents propose configuration. The execution system resolves
    configuration. Only resolved values describe what actually ran.

Precedence is fixed and implemented HERE, exactly once::

    default -> agent proposal -> operator override -> resolved value
    operator override > agent proposal > default ("shuffle")

Callers (workflow, tuner, engine) consume :class:`ResolvedOrdering`; they
never re-derive precedence. The training engine receives only the
``resolved_*`` values and has no knowledge of how they were reached.

Validation happens in two stages, because one of them cannot be done until
the ``DataScope`` is resolved:

1. **Structural** (:func:`validate_ordering_shape`) — scope-independent, run
   at each intake as the value arrives. Every provided value is checked even
   when an override will discard it, so malformed agent output is surfaced
   rather than silently masked.
2. **Resolution** (inside :func:`resolve_ordering`) — the resolved
   ``file_order`` must be a full permutation of the resolved scope. Ordering
   must never change selection.

Design: ``docs/design/v19_priorities/pr2_data_ordering.md`` §3.1, §3.6, §3.7.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OrderStrategy = Literal["shuffle", "sequential"]
"""How selected samples are visited during training.

``shuffle``     — global uniform shuffle over the epoch's concatenated
                  dataset. The default, and byte-for-byte the pre-PR2 behavior.
``sequential``  — file blocks visited in a fixed order; samples within each
                  file shuffled per epoch.
"""

OrderingResolutionSource = Literal[
    "operator_override",
    "agent_proposal",
    "default",
    "legacy_default",
]
"""Which level supplied the resolved value.

``legacy_default`` is produced ONLY when reading pre-PR2 artifacts that
carry no ordering fields (see :meth:`ResolvedOrdering.legacy_default`). A
live run never records it.
"""

DEFAULT_ORDER_STRATEGY: OrderStrategy = "shuffle"


class OrderingValidationError(ValueError):
    """An ordering value is structurally invalid or not a scope permutation.

    A distinct type so callers can tell an ordering-contract violation from
    an unrelated ``ValueError`` when deciding whether a run may continue.
    """


def validate_ordering_shape(
    strategy: OrderStrategy | None,
    file_order: list[int] | None,
    *,
    level: str,
) -> None:
    """Structural, scope-independent validation of one intake level.

    Applied to agent proposals and operator overrides alike, as the values
    arrive — BEFORE resolution, and regardless of whether this level will
    win. A malformed proposal that an override would have discarded is still
    an error: silently masking bad agent output would hide a real defect.

    The rule for ``file_order`` is uniform across levels: it may be supplied
    only alongside an explicit ``sequential`` strategy AT THE SAME LEVEL.
    This follows from ``file_order`` being meaningful for sequential ordering
    only, and it keeps "is an override present?" unambiguous — a file order
    can never arrive without the strategy that gives it meaning.

    Args:
        strategy:   The strategy at this level, or None when not supplied.
        file_order: The file order at this level, or None when not supplied.
        level:      Human-readable level name for error messages, e.g.
                    ``"agent proposal"`` or ``"operator override"``.

    Raises:
        OrderingValidationError: file order supplied without an explicit
            ``sequential`` strategy at this level, empty, containing
            duplicates, or containing a negative index.
    """
    if file_order is None:
        return

    if strategy != "sequential":
        supplied = "no strategy" if strategy is None else f"strategy={strategy!r}"
        raise OrderingValidationError(
            f"{level}: file_order was supplied with {supplied}. A file order is "
            f"meaningful only for sequential ordering — set the strategy to "
            f"'sequential' at the same level, or drop the file order."
        )
    if not file_order:
        raise OrderingValidationError(
            f"{level}: file_order is empty. Omit it to visit the resolved scope "
            f"in ascending order, or give a full permutation of the scope."
        )
    negatives = sorted({i for i in file_order if i < 0})
    if negatives:
        raise OrderingValidationError(
            f"{level}: file_order contains negative file indices {negatives}."
        )
    duplicates = sorted({i for i in file_order if file_order.count(i) > 1})
    if duplicates:
        raise OrderingValidationError(
            f"{level}: file_order contains duplicate file indices {duplicates}. "
            f"Ordering must not change selection — every scope file appears "
            f"exactly once."
        )


class ResolvedOrdering(BaseModel):
    """The full ordering provenance for one round: intent, control, and fact.

    Only ``resolved_strategy`` / ``resolved_file_order`` describe what
    executed. The proposed and override values are context: they explain WHY
    the resolved value is what it is, and they must never be reported as what
    ran (``docs/design/v19_priorities/pr2_data_ordering.md`` §3.7).
    """

    model_config = ConfigDict(frozen=True)

    proposed_strategy: OrderStrategy | None = Field(
        default=None,
        description="What the agent proposed, or None when it proposed nothing.",
    )
    proposed_file_order: list[int] | None = Field(
        default=None,
        description="File order the agent proposed, if any.",
    )
    override_strategy: OrderStrategy | None = Field(
        default=None,
        description="Operator override for the chain, or None when unset.",
    )
    override_file_order: list[int] | None = Field(
        default=None,
        description="File order the operator forced, if any.",
    )
    resolved_strategy: OrderStrategy = Field(
        description="The strategy that actually executed.",
    )
    resolved_file_order: list[int] | None = Field(
        default=None,
        description=(
            "The file visitation order that actually executed. None exactly "
            "when resolved_strategy is 'shuffle'; otherwise a full permutation "
            "of the resolved DataScope."
        ),
    )
    resolution_source: OrderingResolutionSource = Field(
        description="Which level supplied the resolved value.",
    )

    @classmethod
    def legacy_default(cls) -> ResolvedOrdering:
        """The reading of a pre-PR2 artifact that carries no ordering fields.

        Such runs predate the ordering option entirely, so they ran the
        global shuffle. Recorded with a distinct source so a reader can tell
        "no ordering fields existed yet" from "this run chose the default" —
        legacy artifacts are interpreted explicitly, never guessed at and
        never rewritten.
        """
        return cls(resolved_strategy=DEFAULT_ORDER_STRATEGY, resolution_source="legacy_default")

    def describes_execution(self) -> str:
        """One-line human summary suitable for logs and reports."""
        order = "none" if self.resolved_file_order is None else str(self.resolved_file_order)
        return (
            f"proposed={self.proposed_strategy or 'none'} "
            f"override={self.override_strategy or 'none'} "
            f"resolved={self.resolved_strategy} "
            f"source={self.resolution_source} "
            f"file_order={order}"
        )


def resolve_ordering(
    *,
    resolved_scope: list[int],
    proposed_strategy: OrderStrategy | None = None,
    proposed_file_order: list[int] | None = None,
    override_strategy: OrderStrategy | None = None,
    override_file_order: list[int] | None = None,
) -> ResolvedOrdering:
    """Resolve the ordering that will execute, with full provenance.

    The single implementation of the precedence rule
    ``operator override > agent proposal > default``. Both intake levels are
    re-validated structurally here, so a caller that skipped
    :func:`validate_ordering_shape` still cannot smuggle a malformed value
    past resolution.

    File-order resolution follows the WINNING level only:

    - resolved ``shuffle``    -> ``resolved_file_order`` is None. A proposed
      sequential file order is NOT carried over; it survives as provenance
      only.
    - resolved ``sequential`` -> the winning level's file order, or ascending
      ``resolved_scope`` when that level supplied none. Either way the result
      is validated as a full permutation of the scope.

    Args:
        resolved_scope:       The run's resolved DataScope (allowed file
                              indices). Ordering permutes exactly this set.
        proposed_strategy:    Agent proposal, or None.
        proposed_file_order:  Agent-proposed file order, or None.
        override_strategy:    Operator override, or None.
        override_file_order:  Operator-forced file order, or None.

    Returns:
        A fully populated :class:`ResolvedOrdering`.

    Raises:
        OrderingValidationError: Either level is structurally invalid, the
            resolved scope is empty, or the resolved file order is not a full
            permutation of the resolved scope.
    """
    validate_ordering_shape(proposed_strategy, proposed_file_order, level="agent proposal")
    validate_ordering_shape(override_strategy, override_file_order, level="operator override")

    if override_strategy is not None:
        strategy: OrderStrategy = override_strategy
        winning_file_order = override_file_order
        source: OrderingResolutionSource = "operator_override"
    elif proposed_strategy is not None:
        strategy = proposed_strategy
        winning_file_order = proposed_file_order
        source = "agent_proposal"
    else:
        strategy = DEFAULT_ORDER_STRATEGY
        winning_file_order = None
        source = "default"

    if strategy == "shuffle":
        resolved_file_order = None
    else:
        if not resolved_scope:
            raise OrderingValidationError(
                "sequential ordering requires a non-empty resolved DataScope."
            )
        resolved_file_order = (
            list(winning_file_order) if winning_file_order is not None else sorted(resolved_scope)
        )
        _assert_full_permutation(resolved_file_order, resolved_scope, source=source)

    return ResolvedOrdering(
        proposed_strategy=proposed_strategy,
        proposed_file_order=proposed_file_order,
        override_strategy=override_strategy,
        override_file_order=override_file_order,
        resolved_strategy=strategy,
        resolved_file_order=resolved_file_order,
        resolution_source=source,
    )


def _assert_full_permutation(
    file_order: list[int],
    resolved_scope: list[int],
    *,
    source: OrderingResolutionSource,
) -> None:
    """Require ``file_order`` to be a reordering of ``resolved_scope``, nothing more.

    Ordering must not change selection: a subset would silently drop training
    files, and an extra index would reach outside the run's DataScope. Both
    are contract violations, not values to normalize.
    """
    scope_set = set(resolved_scope)
    order_set = set(file_order)
    if order_set == scope_set and len(file_order) == len(scope_set):
        return

    missing = sorted(scope_set - order_set)
    extra = sorted(order_set - scope_set)
    problems = []
    if missing:
        problems.append(f"missing {missing}")
    if extra:
        problems.append(f"outside the scope {extra}")
    if len(file_order) != len(order_set):
        duplicates = sorted({i for i in file_order if file_order.count(i) > 1})
        problems.append(f"duplicated {duplicates}")

    raise OrderingValidationError(
        f"resolved file_order {file_order} (from {source}) is not a full permutation "
        f"of the resolved DataScope {sorted(scope_set)}: {'; '.join(problems)}. "
        "Ordering may reorder the scope but must never change which files are used."
    )
