"""
Unit tests for execute_tools/dataset_config.py::DataScope

Pure logic tests — no I/O, no real data.
See docs/design/enable_partial_file_list.md (Commit DS1).
"""

import json

import pytest
from pydantic import ValidationError

from execute_tools.dataset_config import (
    NUM_FILES,
    TIDMAD,
    DataScope,
)

# ---------------------------------------------------------------------------
# default() / resolve() / is_full()
# ---------------------------------------------------------------------------


class TestDefaultScope:
    def test_default_resolves_to_all_files(self):
        assert DataScope.default().resolve(NUM_FILES) == list(range(20))

    def test_default_is_full(self):
        assert DataScope.default().is_full(NUM_FILES)

    def test_none_file_indices_is_default(self):
        assert DataScope(file_indices=None) == DataScope.default()

    def test_explicit_full_range_is_full(self):
        scope = DataScope(file_indices=list(range(20)))
        assert scope.is_full(NUM_FILES)

    def test_partial_scope_is_not_full(self):
        assert not DataScope(file_indices=[4, 5, 6]).is_full(NUM_FILES)


class TestResolve:
    def test_normalizes_sorted_and_deduped(self):
        scope = DataScope(file_indices=[9, 4, 4, 7])
        assert scope.resolve(NUM_FILES) == [4, 7, 9]

    def test_out_of_range_raises_with_index_and_bound(self):
        scope = DataScope(file_indices=[4, 25])
        with pytest.raises(ValueError, match=r"\[25\].*num_files=20.*0\.\.19"):
            scope.resolve(NUM_FILES)

    def test_boundary_index_is_valid(self):
        assert DataScope(file_indices=[19]).resolve(NUM_FILES) == [19]

    def test_resolve_returns_fresh_copy(self):
        scope = DataScope(file_indices=[4, 5])
        resolved = scope.resolve(NUM_FILES)
        resolved.append(99)
        assert scope.resolve(NUM_FILES) == [4, 5]


# ---------------------------------------------------------------------------
# Construction-time validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_list_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            DataScope(file_indices=[])

    def test_negative_index_rejected(self):
        with pytest.raises(ValidationError, match="non-negative"):
            DataScope(file_indices=[-1, 4])

    def test_frozen_assignment_raises(self):
        scope = DataScope(file_indices=[4])
        with pytest.raises(ValidationError):
            scope.file_indices = [5]


# ---------------------------------------------------------------------------
# from_cli()
# ---------------------------------------------------------------------------


class TestFromCli:
    def test_range_shorthand_equals_explicit_list(self):
        assert DataScope.from_cli("4-9") == DataScope.from_cli("4,5,6,7,8,9")

    def test_range_shorthand_values(self):
        assert DataScope.from_cli("4-9").file_indices == [4, 5, 6, 7, 8, 9]

    def test_single_index(self):
        assert DataScope.from_cli("7").file_indices == [7]

    def test_mixed_tokens(self):
        assert DataScope.from_cli("0-3,7").file_indices == [0, 1, 2, 3, 7]

    def test_whitespace_tolerated(self):
        assert DataScope.from_cli(" 4 , 6-7 ").file_indices == [4, 6, 7]

    def test_empty_spec_rejected(self):
        with pytest.raises(ValueError, match="empty scope spec"):
            DataScope.from_cli("")
        with pytest.raises(ValueError, match="empty scope spec"):
            DataScope.from_cli("   ")

    def test_empty_token_rejected(self):
        with pytest.raises(ValueError, match="empty token"):
            DataScope.from_cli("4,,7")

    def test_malformed_token_rejected(self):
        with pytest.raises(ValueError, match="malformed"):
            DataScope.from_cli("4,x")

    def test_malformed_range_rejected(self):
        with pytest.raises(ValueError, match="malformed range"):
            DataScope.from_cli("4-x")

    def test_descending_range_rejected(self):
        with pytest.raises(ValueError, match="descending range"):
            DataScope.from_cli("9-4")

    def test_negative_token_hits_validator(self):
        # "-3" parses as int(-3); the model validator rejects it with the
        # non-negative message rather than a confusing range error.
        with pytest.raises(ValidationError, match="non-negative"):
            DataScope.from_cli("-3")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_resolved_scope_is_json_serializable(self):
        resolved = DataScope.from_cli("4-9").resolve(NUM_FILES)
        assert json.loads(json.dumps(resolved)) == [4, 5, 6, 7, 8, 9]

    def test_model_round_trip(self):
        scope = DataScope(file_indices=[9, 4])
        again = DataScope.model_validate_json(scope.model_dump_json())
        assert again == scope
        assert again.file_indices == [4, 9]
