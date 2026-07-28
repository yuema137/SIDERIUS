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

from typing import Any, Literal

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


def parse_file_order_cli(spec: str) -> list[int]:
    """Parse a CLI file order, PRESERVING the order given.

    Deliberately not ``DataScope.from_cli``: that sorts and dedupes, which is
    right for a scope (a set of files) and catastrophic for an order (a
    sequence). Routing a file order through it would silently rewrite every
    operator-specified permutation into ascending order — the feature would
    appear to work while doing nothing.

    Only a comma-separated list is accepted. Range syntax (``4-9``) is
    rejected because a range cannot express a permutation, so accepting it
    would invite exactly the ascending-order confusion this function exists
    to prevent.

    Args:
        spec: e.g. ``"4,6,5,9,7,8"``.

    Returns:
        File indices in the order written.

    Raises:
        OrderingValidationError: Empty, range syntax, or a non-integer token.
    """
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    if not tokens:
        raise OrderingValidationError(f"file order {spec!r} is empty.")
    order: list[int] = []
    for token in tokens:
        if "-" in token[1:]:  # allow a leading '-' to reach the int() error
            raise OrderingValidationError(
                f"file order {spec!r} uses range syntax ({token!r}). A range "
                f"cannot express a visitation order — list the indices "
                f"explicitly, e.g. '4,6,5,9,7,8'."
            )
        try:
            order.append(int(token))
        except ValueError as exc:
            raise OrderingValidationError(
                f"file order {spec!r} contains a non-integer token {token!r}."
            ) from exc
    return order


class RejectedOrderingProposal(BaseModel):
    """An agent ordering proposal that was received but not applied.

    Recovering from a malformed LLM proposal is acceptable — falling back
    silently is not. A rejected proposal is materially different from no
    proposal at all: the agent tried to steer the run and was overruled by
    the schema, which is a fact about agent behavior that downstream
    interpretation must be able to see (operator requirement, 2026-07-28).

    Attributes:
        strategy:   The raw strategy the agent asked for, if any. Untyped
                    (``str``) on purpose — a rejected value may be exactly
                    the thing that is not a valid ``OrderStrategy``.
        file_order: The raw file order the agent asked for, if any. Also
                    deliberately loose: it may be the malformed part.
        reason:     Why it was not applied, stating WHICH failure occurred —
                    the ordering itself was invalid, or the ordering was
                    well-formed but discarded because another field of the
                    plan failed validation. Reporting the second as the
                    first would misattribute the defect.
    """

    model_config = ConfigDict(frozen=True)

    strategy: str | None = Field(default=None)
    file_order: list[int] | None = Field(default=None)
    reason: str = Field(min_length=1)


class ResolvedOrdering(BaseModel):
    """The full ordering provenance for one round: intent, control, and fact.

    Only ``resolved_strategy`` / ``resolved_file_order`` describe what
    executed. The proposed and override values are context: they explain WHY
    the resolved value is what it is, and they must never be reported as what
    ran (``docs/design/v19_priorities/pr2_data_ordering.md`` §3.7).

    A rejected proposal is carried here too, in ``proposed_*`` plus
    ``proposal_rejected`` / ``proposal_rejection_reason``, so a reader can
    distinguish "the agent proposed nothing" from "the agent proposed
    something unusable". ``resolution_source`` is never ``agent_proposal``
    in that case.
    """

    model_config = ConfigDict(frozen=True)

    proposed_strategy: str | None = Field(
        default=None,
        description=(
            "What the agent proposed, or None when it proposed nothing. Typed "
            "as str rather than OrderStrategy because a REJECTED proposal is "
            "preserved here verbatim, and an unusable value may be exactly "
            "what the agent sent."
        ),
    )
    proposed_file_order: list[int] | None = Field(
        default=None,
        description="File order the agent proposed, if any (rejected or not).",
    )
    proposal_rejected: bool = Field(
        default=False,
        description=(
            "True when an ordering proposal was received but not applied. "
            "Distinguishes a rejected proposal from an absent one — the "
            "fallback must never look like agent silence."
        ),
    )
    proposal_rejection_reason: str | None = Field(
        default=None,
        description="Why the proposal was not applied. None unless rejected.",
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
    def from_record(cls, record: Any) -> ResolvedOrdering:
        """Read the ordering a persisted record says it ran.

        The single place the legacy rule lives, so the interpreter and the
        iteration manifest cannot drift apart on it: a record with no
        ``resolved_order_strategy`` predates the ordering option entirely and
        is read as the global shuffle with source ``legacy_default`` — read
        explicitly, never guessed, and never written back.

        Takes any object exposing the record's ordering attributes (duck
        typed, so this module stays free of a schema import cycle).
        """
        resolved = getattr(record, "resolved_order_strategy", None)
        if resolved is None:
            return cls.legacy_default()
        return cls(
            proposed_strategy=getattr(record, "proposed_order_strategy", None),
            proposed_file_order=getattr(record, "proposed_file_order", None),
            proposal_rejected=bool(getattr(record, "ordering_proposal_rejected", False)),
            proposal_rejection_reason=getattr(record, "ordering_proposal_rejection_reason", None),
            override_strategy=getattr(record, "override_order_strategy", None),
            override_file_order=getattr(record, "override_file_order", None),
            resolved_strategy=resolved,
            resolved_file_order=getattr(record, "resolved_file_order", None),
            resolution_source=getattr(record, "ordering_resolution_source", None) or "default",
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
        proposed = self.proposed_strategy or "none"
        if self.proposal_rejected:
            proposed = f"{proposed}(REJECTED)"
        return (
            f"proposed={proposed} "
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
    rejected_proposal: RejectedOrderingProposal | None = None,
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
        rejected_proposal:    A proposal that arrived but could not be
                              applied. Mutually exclusive with
                              ``proposed_strategy`` — a proposal is either
                              usable or rejected, never both. When given, the
                              resolution proceeds as if no proposal had been
                              made (so the override, else the default, wins)
                              while the rejection is preserved in the result.

    Returns:
        A fully populated :class:`ResolvedOrdering`.

    Raises:
        OrderingValidationError: Either level is structurally invalid, the
            resolved scope is empty, or the resolved file order is not a full
            permutation of the resolved scope.
        ValueError: Both a usable proposal and a rejected one were supplied.
    """
    if rejected_proposal is not None and (
        proposed_strategy is not None or proposed_file_order is not None
    ):
        raise ValueError(
            "resolve_ordering received both a usable proposal and a rejected "
            "one. A proposal is either applied or rejected — passing both "
            "would make the recorded provenance self-contradictory."
        )

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
        # A rejected proposal still populates proposed_*, so downstream can
        # see that the agent DID try to steer this round.
        proposed_strategy=(
            rejected_proposal.strategy if rejected_proposal is not None else proposed_strategy
        ),
        proposed_file_order=(
            rejected_proposal.file_order if rejected_proposal is not None else proposed_file_order
        ),
        proposal_rejected=rejected_proposal is not None,
        proposal_rejection_reason=(
            rejected_proposal.reason if rejected_proposal is not None else None
        ),
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
