"""F-12d-34 — generic engine sites that consume an optional scope carrier.

F-12d-27 made ``run_experiment_streaming`` admit ``sample_set=None``, because a
COMPOSED run trains from its transported task scope and carries no legacy
SampleSet by construction. The dispatch was widened; three sites downstream of
it still read the value as though it were always a dict. CI pyright named all
three (``reportOptionalIterable`` + two ``reportOptionalMemberAccess``), and
they are not one defect repeated — they differ in whether the absent case is
REACHABLE:

The real-task storage-provenance incident and its scientific topology fixture
live with that external task. This framework module retains the two generic
decisions: ordering cannot inspect a missing legacy scope, and training may
proceed when either the legacy mapping or the transported task scope exists.
"""

import pytest

from execute_tools import train_engine_sandbox as tes


class TestOrderingRefusesWithoutAScope:
    def test_sequential_file_order_without_a_sample_set_is_refused(self):
        with pytest.raises(ValueError, match="no sample set to order against"):
            tes.validate_ordering_against_scope("sequential", [4, 5], None)

    def test_the_absent_scope_is_refused_only_when_an_order_needs_checking(self):
        """No file order means nothing to validate — absence is not an error."""
        tes.validate_ordering_against_scope("sequential", None, None)
        tes.validate_ordering_against_scope("shuffle", None, None)


class TestTrainingScopePresence:
    @pytest.mark.parametrize(
        ("sample_set", "task_scope_ref", "expected"),
        [
            (None, None, False),
            ({"0": [0]}, None, True),
            (None, "/workspace/task_scope.json", True),
        ],
    )
    def test_either_scope_carrier_is_sufficient(self, sample_set, task_scope_ref, expected):
        class Args:
            pass

        args = Args()
        args.task_scope_ref = task_scope_ref
        assert tes._has_scope_to_train_from(args, sample_set) is expected
