"""Shard planning — the properties whose violation looks like a green run.

The dangerous failures here are silent: a dropped file means tests never ran
and nobody notices, and a sensitive file leaking into a bulk shard produces a
confident failure that is really contention. Each test names one.
"""

from __future__ import annotations

import pytest

from tools.ci.shards import ShardPlan, plan_shards, verify_plan

FILES = [f"tests/unit/{d}/test_{i}.py" for d in ("agent", "core", "workflows") for i in range(7)]


class TestDeterminism:
    def test_input_order_does_not_change_the_plan(self):
        """Set iteration and caller discovery order must not reach the plan.

        A planner that iterates a set produces a different assignment run to
        run, so a shard's result cannot be compared against a previous run and
        "same files, same shards" stops being true. Fails as: reversed input
        yields a different assignment.
        """
        a = plan_shards(FILES, count=4)
        b = plan_shards(list(reversed(FILES)), count=4)
        assert [s.files for s in a.shards] == [s.files for s in b.shards]

    def test_duplicate_inputs_are_collapsed_not_duplicated(self):
        """A file listed twice must not be executed twice.

        Fails as: the same file appears in two shards, doubling its runtime and
        any state it mutates.
        """
        plan = plan_shards([*FILES, *FILES], count=3)
        assigned = plan.bulk_files
        assert len(assigned) == len(set(assigned)) == len(set(FILES))


class TestPartition:
    def test_every_file_lands_in_exactly_one_shard(self):
        """A dropped file is invisible: the run is green and the test never ran.

        This is the failure mode that makes sharding dangerous, so it is
        asserted directly rather than inferred from counts. Fails as: the union
        of shards is not the input set.
        """
        plan = plan_shards(FILES, count=5)
        assert sorted(plan.bulk_files) == sorted(set(FILES))
        assert verify_plan(plan, FILES) == []

    def test_more_shards_than_files_yields_empty_shards_not_lost_files(self):
        """Over-sharding must degrade gracefully.

        Fails as: files are dropped when count exceeds the file count.
        """
        plan = plan_shards(["a.py", "b.py"], count=5)
        assert sorted(plan.bulk_files) == ["a.py", "b.py"]
        assert sum(s.size for s in plan.shards) == 2

    def test_zero_or_negative_shard_count_is_rejected(self):
        """A count of 0 would silently execute nothing.

        Fails as: plan_shards(count=0) returns an empty plan that looks green.
        """
        with pytest.raises(ValueError, match="must be >= 1"):
            plan_shards(FILES, count=0)


class TestSensitiveIsolation:
    def test_sensitive_files_never_enter_a_bulk_shard(self):
        """Contention against a timing test produces a confident false RED.

        The five sensitive files assert that a preemption mechanism fired
        within a bound; run them under a saturated bulk lane and the failure is
        harness noise wearing a product failure's clothes. Fails as: a
        sensitive file appears in bulk_files.
        """
        sensitive = {FILES[0], FILES[9]}
        plan = plan_shards(FILES, count=3, sensitive=sensitive)
        assert not (set(plan.bulk_files) & sensitive)
        assert set(plan.sensitive) == sensitive
        assert verify_plan(plan, FILES) == []

    def test_a_sensitive_file_absent_from_the_input_is_still_excluded(self):
        """Exclusion must not depend on the file being discovered first.

        Fails as: naming a sensitive file the scanner missed silently drops the
        exclusion instead of recording it.
        """
        plan = plan_shards(["x.py"], count=2, sensitive={"not_scanned.py"})
        assert plan.sensitive == ("not_scanned.py",)
        assert plan.bulk_files == ["x.py"]


class TestWeighting:
    def test_weights_beat_file_count_for_balance(self):
        """Equal file counts can still mean a 10x wall-clock long pole.

        One dominant file must not sit alongside a fair share of the rest.
        Fails as: the weighted plan is no better balanced than round-robin.
        """
        files = [f"f{i}.py" for i in range(8)]
        weights = {"f0.py": 100.0, **{f"f{i}.py": 1.0 for i in range(1, 8)}}
        plan = plan_shards(files, count=2, weights=weights)
        heavy = next(s for s in plan.shards if "f0.py" in s.files)
        assert heavy.size == 1, "the dominant file should be alone in its shard"
        assert verify_plan(plan, files) == []

    def test_unweighted_imbalance_is_reported_not_hidden(self):
        """A plan that cannot balance must say so, so the operator sees it.

        Fails as: imbalance() returns 1.0 for a genuinely lopsided plan.
        """
        files = [f"f{i}.py" for i in range(4)]
        plan = plan_shards(files, count=2, weights={"f0.py": 97.0})
        assert plan.imbalance() > 1.5


class TestVerifyPlan:
    def test_verify_detects_a_dropped_file(self):
        """verify_plan is the runtime backstop; it must catch what it exists for.

        A planner bug and a green run are indistinguishable without it. Fails
        as: verify_plan returns clean for a plan missing a file.
        """
        good = plan_shards(FILES, count=3)
        broken = ShardPlan(shards=good.shards[:-1], sensitive=good.sensitive)
        problems = verify_plan(broken, FILES)
        assert problems and "never assigned" in problems[0]

    def test_verify_detects_a_sensitive_leak(self):
        """A leak is the isolation failure that invalidates evidence.

        Fails as: verify_plan accepts a plan whose bulk lane contains a file it
        also lists as sensitive.
        """
        plan = plan_shards(FILES, count=2)
        leaked = ShardPlan(shards=plan.shards, sensitive=(FILES[0],))
        problems = verify_plan(leaked, FILES)
        assert any("leaked into the bulk lane" in p for p in problems)
