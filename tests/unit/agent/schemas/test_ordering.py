"""Ordering resolution: precedence, provenance, and the permutation contract.

Covers the deterministic resolution matrix from
``docs/design/v19_priorities/pr2_data_ordering.md`` §7.1 — every row asserts
BOTH the resolved strategy and the resolution source, because "shuffle
executed" is only half the fact; which level decided it is the other half.
"""

import pytest
from pydantic import ValidationError

from agent.schemas.ordering import (
    DEFAULT_ORDER_STRATEGY,
    OrderingValidationError,
    ResolvedOrdering,
    resolve_ordering,
    validate_ordering_shape,
)

SCOPE = [4, 5, 6, 7, 8, 9]
PERMUTATION = [4, 6, 5, 9, 7, 8]


# ---- resolution matrix (§7.1 "Resolution logic") ----


def test_proposal_sequential_no_override():
    r = resolve_ordering(resolved_scope=SCOPE, proposed_strategy="sequential")
    assert r.resolved_strategy == "sequential"
    assert r.resolution_source == "agent_proposal"
    assert r.resolved_file_order == sorted(SCOPE)


def test_proposal_shuffle_no_override():
    r = resolve_ordering(resolved_scope=SCOPE, proposed_strategy="shuffle")
    assert r.resolved_strategy == "shuffle"
    assert r.resolution_source == "agent_proposal"
    assert r.resolved_file_order is None


def test_no_proposal_no_override_is_default_shuffle():
    r = resolve_ordering(resolved_scope=SCOPE)
    assert r.resolved_strategy == DEFAULT_ORDER_STRATEGY == "shuffle"
    assert r.resolution_source == "default"
    assert r.resolved_file_order is None


def test_override_shuffle_beats_proposal_sequential():
    r = resolve_ordering(
        resolved_scope=SCOPE,
        proposed_strategy="sequential",
        proposed_file_order=PERMUTATION,
        override_strategy="shuffle",
    )
    assert r.resolved_strategy == "shuffle"
    assert r.resolution_source == "operator_override"
    # The proposal survives as provenance but must NOT leak into execution.
    assert r.proposed_strategy == "sequential"
    assert r.proposed_file_order == PERMUTATION
    assert r.resolved_file_order is None


def test_override_sequential_beats_proposal_shuffle():
    r = resolve_ordering(
        resolved_scope=SCOPE,
        proposed_strategy="shuffle",
        override_strategy="sequential",
        override_file_order=PERMUTATION,
    )
    assert r.resolved_strategy == "sequential"
    assert r.resolution_source == "operator_override"
    assert r.resolved_file_order == PERMUTATION


def test_override_sequential_without_file_order_uses_ascending_scope():
    r = resolve_ordering(resolved_scope=[9, 4, 7], override_strategy="sequential")
    assert r.resolved_file_order == [4, 7, 9]
    assert r.resolution_source == "operator_override"


def test_proposal_sequential_with_explicit_permutation():
    r = resolve_ordering(
        resolved_scope=SCOPE,
        proposed_strategy="sequential",
        proposed_file_order=PERMUTATION,
    )
    assert r.resolved_file_order == PERMUTATION
    assert r.resolution_source == "agent_proposal"


def test_invalid_override_permutation_raises():
    with pytest.raises(OrderingValidationError) as exc:
        resolve_ordering(
            resolved_scope=SCOPE,
            override_strategy="sequential",
            override_file_order=[4, 6, 5],  # subset
        )
    assert "not a full permutation" in str(exc.value)
    assert "missing [7, 8, 9]" in str(exc.value)


def test_structurally_invalid_proposal_is_surfaced_even_when_overridden():
    """A malformed proposal must not be silently masked by a valid override —
    otherwise a real defect in agent output would never be seen."""
    with pytest.raises(OrderingValidationError) as exc:
        resolve_ordering(
            resolved_scope=SCOPE,
            proposed_strategy="sequential",
            proposed_file_order=[4, 4, 5, 6, 7, 8, 9],  # duplicate
            override_strategy="shuffle",
        )
    assert "agent proposal" in str(exc.value)
    assert "duplicate" in str(exc.value)


# ---- resolved-value permutation contract (§ Decision 5) ----


@pytest.mark.parametrize(
    "bad_order, expected_fragment",
    [
        ([4, 6, 5], "missing [7, 8, 9]"),
        ([4, 5, 6, 7, 8], "missing [9]"),
        ([4, 5, 6, 7, 8, 9, 12], "outside the scope [12]"),
        ([4, 5, 6, 7, 8, 99], "outside the scope [99]"),
    ],
)
def test_resolved_file_order_must_be_full_permutation(bad_order, expected_fragment):
    with pytest.raises(OrderingValidationError) as exc:
        resolve_ordering(
            resolved_scope=SCOPE,
            override_strategy="sequential",
            override_file_order=bad_order,
        )
    message = str(exc.value)
    assert "not a full permutation" in message
    assert expected_fragment in message


def test_partial_scope_permutation_is_validated_against_the_resolved_scope():
    """DS8 interaction: the contract is against the RESOLVED scope, whatever
    it is — not against the full dataset."""
    partial = [2, 3]
    ok = resolve_ordering(
        resolved_scope=partial,
        override_strategy="sequential",
        override_file_order=[3, 2],
    )
    assert ok.resolved_file_order == [3, 2]

    with pytest.raises(OrderingValidationError):
        # Valid for the full dataset, invalid for THIS scope.
        resolve_ordering(
            resolved_scope=partial,
            override_strategy="sequential",
            override_file_order=[0, 1, 2, 3],
        )


def test_sequential_with_empty_scope_raises():
    with pytest.raises(OrderingValidationError) as exc:
        resolve_ordering(resolved_scope=[], override_strategy="sequential")
    assert "non-empty resolved DataScope" in str(exc.value)


# ---- structural validation (scope-independent, per intake) ----


@pytest.mark.parametrize("level", ["agent proposal", "operator override"])
def test_file_order_without_sequential_rejected(level):
    with pytest.raises(OrderingValidationError) as exc:
        validate_ordering_shape("shuffle", [4, 5], level=level)
    assert level in str(exc.value)
    assert "meaningful only for sequential" in str(exc.value)


def test_file_order_without_any_strategy_rejected():
    """Keeps 'is an override present?' unambiguous: a file order can never
    arrive without the strategy that gives it meaning."""
    with pytest.raises(OrderingValidationError) as exc:
        validate_ordering_shape(None, [4, 5], level="operator override")
    assert "no strategy" in str(exc.value)


def test_empty_file_order_rejected():
    with pytest.raises(OrderingValidationError) as exc:
        validate_ordering_shape("sequential", [], level="agent proposal")
    assert "empty" in str(exc.value)


def test_duplicate_file_order_rejected():
    with pytest.raises(OrderingValidationError) as exc:
        validate_ordering_shape("sequential", [4, 5, 4], level="agent proposal")
    assert "duplicate file indices [4]" in str(exc.value)


def test_negative_file_index_rejected():
    with pytest.raises(OrderingValidationError) as exc:
        validate_ordering_shape("sequential", [-1, 4], level="agent proposal")
    assert "negative file indices [-1]" in str(exc.value)


def test_shape_validation_is_a_noop_without_a_file_order():
    validate_ordering_shape(None, None, level="agent proposal")
    validate_ordering_shape("shuffle", None, level="agent proposal")
    validate_ordering_shape("sequential", None, level="operator override")


# ---- provenance object ----


def test_legacy_default_is_distinguishable_from_a_chosen_default():
    legacy = ResolvedOrdering.legacy_default()
    assert legacy.resolved_strategy == "shuffle"
    assert legacy.resolution_source == "legacy_default"
    assert legacy.proposed_strategy is None and legacy.override_strategy is None

    chosen = resolve_ordering(resolved_scope=SCOPE)
    assert chosen.resolved_strategy == "shuffle"
    assert chosen.resolution_source == "default"


def test_resolved_ordering_is_immutable():
    """Frozen: a resolved fact must not be edited after the fact."""
    r = resolve_ordering(resolved_scope=SCOPE)
    with pytest.raises(ValidationError):
        r.resolved_strategy = "sequential"


def test_resolved_ordering_round_trips_through_json():
    r = resolve_ordering(
        resolved_scope=SCOPE,
        proposed_strategy="sequential",
        proposed_file_order=PERMUTATION,
        override_strategy="shuffle",
    )
    assert ResolvedOrdering.model_validate_json(r.model_dump_json()) == r


def test_describes_execution_shows_all_levels():
    r = resolve_ordering(
        resolved_scope=SCOPE,
        proposed_strategy="sequential",
        override_strategy="shuffle",
    )
    line = r.describes_execution()
    assert "proposed=sequential" in line
    assert "override=shuffle" in line
    assert "resolved=shuffle" in line
    assert "source=operator_override" in line
    assert "file_order=none" in line
