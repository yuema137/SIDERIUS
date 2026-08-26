"""Oversized-file node-id splitting (operator local-CI ruling, 2026-08-26).

One measured file atom (727 s, 6 tests) exceeded total/4 and floored the bulk
makespan at its own duration; file-level balancing cannot fix an atom. These
tests pin the expansion's contract: split only what is oversized AND measured,
never a sensitive file, deterministically, with old behaviour byte-preserved
when no split applies.
"""

from tools.ci.shards import plan_shards

FILES = ["tests/a.py", "tests/b.py", "tests/big.py", "tests/c.py", "tests/d.py"]
WEIGHTS = {
    "tests/a.py": 10.0,
    "tests/b.py": 12.0,
    "tests/big.py": 400.0,
    "tests/c.py": 11.0,
    "tests/d.py": 9.0,
}
SPLITS = {"tests/big.py": {"T::t1": 130.0, "T::t2": 135.0, "T::t3": 135.0}}


class TestOversizedSplit:
    def test_an_oversized_measured_file_expands_into_node_atoms(self):
        plan = plan_shards(FILES, count=4, weights=WEIGHTS, splits=SPLITS)
        atoms = [f for s in plan.shards for f in s.files]
        assert "tests/big.py" not in atoms
        assert {a for a in atoms if a.startswith("tests/big.py::")} == {
            "tests/big.py::T::t1",
            "tests/big.py::T::t2",
            "tests/big.py::T::t3",
        }

    def test_the_makespan_drops_below_the_unsplit_atom(self):
        split = plan_shards(FILES, count=4, weights=WEIGHTS, splits=SPLITS)
        unsplit = plan_shards(FILES, count=4, weights=WEIGHTS)
        assert max(s.weight for s in unsplit.shards) >= 400.0
        assert max(s.weight for s in split.shards) < 400.0

    def test_node_atoms_land_in_distinct_shards_when_capacity_allows(self):
        plan = plan_shards(FILES, count=4, weights=WEIGHTS, splits=SPLITS)
        homes = [s.index for s in plan.shards for f in s.files if f.startswith("tests/big.py::")]
        # three ~equal heavy atoms across four shards: LPT must not co-locate two
        assert len(set(homes)) == 3

    def test_a_file_below_the_threshold_is_never_split(self):
        small_split = {"tests/a.py": {"T::x": 5.0, "T::y": 5.0}}
        plan = plan_shards(FILES, count=4, weights=WEIGHTS, splits={**SPLITS, **small_split})
        atoms = [f for s in plan.shards for f in s.files]
        assert "tests/a.py" in atoms
        assert not any(a.startswith("tests/a.py::") for a in atoms)

    def test_a_sensitive_file_is_never_split_even_when_oversized(self):
        plan = plan_shards(
            FILES, count=4, weights=WEIGHTS, splits=SPLITS, sensitive=["tests/big.py"]
        )
        atoms = [f for s in plan.shards for f in s.files]
        assert not any(a.startswith("tests/big.py::") for a in atoms)
        assert "tests/big.py" in plan.sensitive

    def test_no_splits_is_byte_identical_old_behaviour(self):
        a = plan_shards(FILES, count=4, weights=WEIGHTS)
        b = plan_shards(FILES, count=4, weights=WEIGHTS, splits=None)
        c = plan_shards(FILES, count=4, weights=WEIGHTS, splits={})
        assert a == b == c

    def test_determinism_same_inputs_same_plan(self):
        p1 = plan_shards(FILES, count=4, weights=WEIGHTS, splits=SPLITS)
        p2 = plan_shards(list(reversed(FILES)), count=4, weights=WEIGHTS, splits=SPLITS)
        assert p1 == p2


class TestVerifyPlanWithSplits:
    def test_a_fully_split_file_verifies_as_covered(self):
        from tools.ci.shards import verify_plan

        plan = plan_shards(FILES, count=4, weights=WEIGHTS, splits=SPLITS)
        assert verify_plan(plan, FILES, splits=SPLITS) == []

    def test_a_partial_atom_set_is_a_dropped_test_hole_not_a_pass(self):
        from tools.ci.shards import Shard, ShardPlan, verify_plan

        # hand-build a plan missing one of big.py's three atoms
        plan = ShardPlan(
            shards=(
                Shard(index=0, files=("tests/a.py", "tests/big.py::T::t1"), weight=1),
                Shard(index=1, files=("tests/b.py", "tests/big.py::T::t2"), weight=1),
                Shard(index=2, files=("tests/c.py",), weight=1),
                Shard(index=3, files=("tests/d.py",), weight=1),
            ),
            sensitive=(),
        )
        problems = verify_plan(plan, FILES, splits=SPLITS)
        assert any("partially assigned" in p for p in problems)
        assert any("dropped-test hole" in p for p in problems)

    def test_without_splits_argument_old_verification_is_unchanged(self):
        from tools.ci.shards import verify_plan

        plan = plan_shards(FILES, count=4, weights=WEIGHTS)
        assert verify_plan(plan, FILES) == []
