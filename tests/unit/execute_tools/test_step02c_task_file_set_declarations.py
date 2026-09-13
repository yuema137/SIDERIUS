"""Generic legality and reachability for task-owned profile file sets.

Exact real-task file sets and Health rosters belong to external task packages.
SIDERIUS owns the profile-membership rule, explicit peek-list validation, and
the anchor consumer's use of the supplied declaration.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from execute_tools.dataset_config import DatasetProfile
from execute_tools.health_checks.config import CheckRef
from tests.helpers.two_family_profile import make_two_family_profile

BASE_PROFILE = make_two_family_profile(num_files=20)
DECLARED_FILE_SET_FIELDS = ("anchor_selection_files", "health_peek_files")


class TestDeclaredFileSetsMustBeLegalForTheTopology:
    """One rule spans every declared profile file-set field."""

    @pytest.mark.parametrize("field", DECLARED_FILE_SET_FIELDS)
    @pytest.mark.parametrize(
        ("case", "value", "expected_fragment"),
        [
            ("empty", [], "is empty"),
            ("duplicate", [3, 3, 10], "duplicate indices"),
            ("above_range", [0, 20], "does not have"),
            ("negative", [-1, 3], "does not have"),
        ],
    )
    def test_illegal_membership_is_rejected(
        self,
        field: str,
        case: str,
        value: list[int],
        expected_fragment: str,
    ) -> None:
        payload = {**BASE_PROFILE.to_wire(), field: value}
        with pytest.raises(ValidationError) as excinfo:
            DatasetProfile.model_validate(payload)
        message = str(excinfo.value)
        assert expected_fragment in message, f"{field}/{case}: {message!r}"
        assert field in message

    @pytest.mark.parametrize("field", DECLARED_FILE_SET_FIELDS)
    def test_legality_uses_this_profiles_partition_count(self, field: str) -> None:
        payload = BASE_PROFILE.to_wire()
        payload["dataset"]["num_files"] = 5
        payload["partition_count"] = 5
        payload["anchor_selection_files"] = [0, 2, 4]
        payload["health_peek_files"] = [1, 3]

        DatasetProfile.model_validate(payload)
        with pytest.raises(ValidationError, match="num_files=5"):
            DatasetProfile.model_validate({**payload, field: [0, 19]})


class TestExplicitPeekLists:
    """Explicit lists are copied exactly and malformed markers refuse."""

    def test_explicit_list_round_trips_without_default_substitution(self) -> None:
        explicit = CheckRef(
            name="output_diversity",
            config={"peek_file_indices": [4, 7, 9]},
        )
        again = CheckRef.model_validate(explicit.model_dump())
        assert explicit.config["peek_file_indices"] == [4, 7, 9]
        assert again.config["peek_file_indices"] == [4, 7, 9]

    def test_unrecognized_marker_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be an explicit list"):
            CheckRef(
                name="output_diversity",
                config={"peek_file_indices": "task_helth_peek"},
            )


def test_anchor_selection_reads_the_supplied_declaration() -> None:
    """A changed declaration must change the selected anchor partitions."""
    from execute_tools.sample_set_builder import build_sample_set

    declared = [1, 5, 12]
    profile = BASE_PROFILE.model_copy(update={"anchor_selection_files": declared})
    sample_set = build_sample_set(
        is_trial=True,
        trial_strategy="anchors",
        trial_portion=0.05,
        seed=42,
        profile=profile,
    )
    assert sorted(sample_set) == sorted(declared)
