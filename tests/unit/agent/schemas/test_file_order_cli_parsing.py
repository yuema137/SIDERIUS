"""CLI parsing for a file ORDER must preserve the order given.

This exists because the obvious reuse is wrong in a way that fails
silently. ``DataScope.from_cli`` sorts and dedupes — correct for a scope
(a SET of files), catastrophic for an order (a SEQUENCE). Routing a file
order through it rewrites every operator-specified permutation into
ascending order, so the feature would appear to work while doing nothing
at all.
"""

import pytest

from agent.schemas.ordering import OrderingValidationError, parse_file_order_cli
from execute_tools.dataset_config import DataScope


def test_order_is_preserved_exactly_as_written():
    assert parse_file_order_cli("4,6,5,9,7,8") == [4, 6, 5, 9, 7, 8]


def test_descending_order_survives():
    assert parse_file_order_cli("9,8,7") == [9, 8, 7]


def test_whitespace_is_tolerated():
    assert parse_file_order_cli(" 4 , 6 , 5 ") == [4, 6, 5]


def test_single_index_is_valid():
    assert parse_file_order_cli("7") == [7]


def test_regression_datascope_would_have_destroyed_the_order():
    """Pins the exact bug this parser exists to prevent: if anyone 'simplifies'
    this back to DataScope.from_cli, this test fails loudly."""
    spec = "4,6,5,9,7,8"
    scope_parsed = DataScope.from_cli(spec).file_indices
    order_parsed = parse_file_order_cli(spec)
    assert scope_parsed == [4, 5, 6, 7, 8, 9], "DataScope sorts — that is its job"
    assert order_parsed == [4, 6, 5, 9, 7, 8], "an ORDER must not be sorted"
    assert order_parsed != scope_parsed


def test_duplicates_are_preserved_for_the_shape_validator_to_reject():
    """Parsing does not dedupe: silently collapsing duplicates would hide an
    operator error that validate_ordering_shape is meant to report."""
    assert parse_file_order_cli("4,4,5") == [4, 4, 5]


def test_range_syntax_is_rejected():
    with pytest.raises(OrderingValidationError) as exc:
        parse_file_order_cli("4-9")
    assert "cannot express a visitation order" in str(exc.value)


def test_empty_spec_is_rejected():
    with pytest.raises(OrderingValidationError):
        parse_file_order_cli("")
    with pytest.raises(OrderingValidationError):
        parse_file_order_cli("  ,  ")


def test_non_integer_token_is_rejected():
    with pytest.raises(OrderingValidationError) as exc:
        parse_file_order_cli("4,five,6")
    assert "non-integer token" in str(exc.value)


def test_negative_index_parses_so_the_shape_validator_can_name_it():
    """A negative index is a shape error, reported with the other shape
    errors rather than as an opaque parse failure."""
    assert parse_file_order_cli("-1,4") == [-1, 4]
