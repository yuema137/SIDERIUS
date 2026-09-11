"""Step 10 / P2a — C3: consumers of PERSISTED artifacts rank by declared identity.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2a_golden_metric_order_closure.md`` §4.2 (the four cases), §4.4 (what a
persisted record carries), §6; parent Q-10-2.

The situation these consumers are in
------------------------------------
The dashboard and the two diagnostic scripts read artifacts whose producing run
is long gone. There is no bound composition to consult and no live tuner — the
ONLY thing that can say which way is better is what the record itself declares.
So the failure this file guards is specific: a consumer that keeps ranking after
the declaration is missing, using the one convention it happens to remember.

Every case is asserted on the RANKING RESULT, not on the presence of a notice: a
warning printed beside a silently inverted leaderboard is worse than no warning,
because it reads like the system noticed.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from dashboard.data_sources.local_json import LocalJsonDataSource
from execute_tools.evaluation_metric import METRIC_IDENTITY_UNAVAILABLE
from execute_tools.persisted_ranking import (
    best_by_declared_metric,
    corpus_order,
    partition_by_metric_identity,
)

TIDMAD_ID = ("tidmad_denoising_score", "higher")
DAVIS_ID = ("fixture_mse", "lower")


def _rec(exp_id: str, score: float | None, identity: tuple[str, str] | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-01-01 00:00:00",
        "denoising_score": score,
    }
    if identity is not None:
        record["metric_result"] = {
            "metric_id": identity[0],
            "direction": identity[1],
            "scalar": score,
        }
    return record


# ---------------------------------------------------------------------------
# The shared corpus helper — the four §4.2 cases
# ---------------------------------------------------------------------------


class TestTheFourArtifactCases:
    def test_case_A_all_known_compatible_yields_an_order(self):
        order, conflict = corpus_order([_rec("a", -1.0, TIDMAD_ID), _rec("b", -2.0, TIDMAD_ID)])
        assert conflict is None
        assert order is not None and order.direction == "higher"

    def test_case_A_lower_corpus_yields_a_lower_order(self):
        order, conflict = corpus_order([_rec("a", 0.017, DAVIS_ID)])
        assert conflict is None
        assert order is not None and order.direction == "lower"

    def test_case_B_missing_rows_are_partitioned_out_individually(self):
        records = [
            _rec("a", -1.0, TIDMAD_ID),
            _rec("legacy", -0.1, None),
            _rec("c", -2.0, TIDMAD_ID),
        ]
        rankable, unranked = partition_by_metric_identity(records)
        assert [r["exp_id"] for r in rankable] == ["a", "c"]
        assert [r["exp_id"] for r in unranked] == ["legacy"]
        order, conflict = corpus_order(rankable)
        assert order is not None and conflict is None, (
            "one legacy row poisoned an otherwise compatible corpus"
        )

    def test_case_C_all_missing_yields_no_order_and_no_conflict(self):
        """Absence is NOT a conflict — the two states are reported differently."""
        order, conflict = corpus_order([_rec("a", -1.0, None), _rec("b", -2.0, None)])
        assert order is None
        assert conflict is None

    def test_case_D_conflicting_known_identities_refuse_and_NAME_the_conflict(self):
        order, conflict = corpus_order([_rec("a", -1.0, TIDMAD_ID), _rec("b", 0.017, DAVIS_ID)])
        assert order is None
        assert conflict is not None
        assert METRIC_IDENTITY_UNAVAILABLE in conflict
        assert "tidmad_denoising_score" in conflict and "fixture_mse" in conflict

    def test_an_empty_corpus_is_unrankable_without_a_conflict(self):
        assert corpus_order([]) == (None, None)

    def test_the_module_contains_no_ordering_of_its_own(self):
        """It COMPOSES the two authorities; it must not become a third.

        MUTATION TARGET: implement the comparison inline here instead of
        delegating to ``MetricOrder``.
        """
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/execute_tools/persisted_ranking.py"
        ).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Compare):
                text = ast.unparse(node)
                assert "score" not in text, f"a score comparison leaked into the composer: {text}"
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", "")
                if name in {"max", "min", "sorted", "sort"}:
                    assert isinstance(func, ast.Attribute) and func.value.id == "order", (  # type: ignore[union-attr]
                        f"a raw extremum leaked into the composer: {ast.unparse(node)}"
                    )


# ---------------------------------------------------------------------------
# The diagnostic scripts' entry point
# ---------------------------------------------------------------------------


class TestBestByDeclaredMetric:
    def test_tidmad_higher_selects_the_largest(self):
        best = best_by_declared_metric(
            [_rec("a", -3.2, TIDMAD_ID), _rec("b", -1.4, TIDMAD_ID), _rec("c", -7.9, TIDMAD_ID)],
            context="test",
        )
        assert best is not None and best["exp_id"] == "b"

    def test_davis_lower_selects_the_smallest(self):
        """The inversion: under a minimised metric the best is the MINIMUM."""
        best = best_by_declared_metric(
            [
                _rec("a", 0.0174, DAVIS_ID),
                _rec("b", 0.0172, DAVIS_ID),
                _rec("c", 0.0210, DAVIS_ID),
            ],
            context="test",
        )
        assert best is not None and best["exp_id"] == "b"

    def test_the_two_directions_disagree_on_the_same_scores(self):
        """Anti-vacuity: the same numbers, two declarations, opposite winners."""
        scores = [("a", 1.0), ("b", 5.0)]
        higher = best_by_declared_metric([_rec(e, s, TIDMAD_ID) for e, s in scores], context="test")
        lower = best_by_declared_metric([_rec(e, s, DAVIS_ID) for e, s in scores], context="test")
        assert higher is not None and lower is not None
        assert higher["exp_id"] == "b" and lower["exp_id"] == "a"

    def test_all_missing_identity_reports_no_best_and_says_so(self, capsys):
        best = best_by_declared_metric([_rec("a", -1.0, None)], context="diagnostic")
        assert best is None
        assert METRIC_IDENTITY_UNAVAILABLE in capsys.readouterr().err

    def test_a_conflicting_corpus_reports_no_best_and_names_the_conflict(self, capsys):
        best = best_by_declared_metric(
            [_rec("a", -1.0, TIDMAD_ID), _rec("b", 0.017, DAVIS_ID)], context="diagnostic"
        )
        assert best is None
        out = capsys.readouterr().err
        assert "tidmad_denoising_score" in out and "fixture_mse" in out

    def test_a_mixed_corpus_still_selects_among_the_known_rows(self, capsys):
        """Case B end to end: the legacy row has the numerically best score and
        must still lose, because it was never rankable."""
        best = best_by_declared_metric(
            [_rec("a", -3.2, TIDMAD_ID), _rec("legacy", 99.0, None), _rec("c", -1.4, TIDMAD_ID)],
            context="diagnostic",
        )
        assert best is not None and best["exp_id"] == "c"
        assert METRIC_IDENTITY_UNAVAILABLE in capsys.readouterr().err

    def test_an_empty_record_set_returns_none(self):
        assert best_by_declared_metric([], context="test") is None


# ---------------------------------------------------------------------------
# The dashboard, end to end over a real temp workspace
# ---------------------------------------------------------------------------


def _workspace(tmp_path, records: list[dict[str, Any]]) -> str:
    path = os.path.join(str(tmp_path), "punet", "v1", "agent", "summary_v1_agent.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(records, handle)
    return str(tmp_path)


class TestTheDashboardRanksByDeclaredIdentity:
    def test_a_lower_corpus_ranks_ASCENDING_and_best_is_the_minimum(self, tmp_path):
        root = _workspace(
            tmp_path,
            [
                _rec("a", 0.0174, DAVIS_ID),
                _rec("b", 0.0172, DAVIS_ID),
                _rec("c", 0.0210, DAVIS_ID),
            ],
        )
        source = LocalJsonDataSource(root)

        entries = source.get_leaderboard("punet", top_n=10)
        assert [e["denoising_score"] for e in entries] == [0.0172, 0.0174, 0.0210]
        assert entries[0]["rank"] == 1

        overview = source.get_model_overview("punet")
        assert overview["best_agent_score"] == 0.0172
        assert overview["metric_ranking_unavailable"] is None

    def test_a_higher_corpus_keeps_its_descending_order(self, tmp_path):
        """TIDMAD backward parity, including the negative-value regime."""
        root = _workspace(
            tmp_path,
            [_rec("a", -3.2, TIDMAD_ID), _rec("b", -1.4, TIDMAD_ID), _rec("c", -7.9, TIDMAD_ID)],
        )
        source = LocalJsonDataSource(root)
        entries = source.get_leaderboard("punet", top_n=10)
        assert [e["denoising_score"] for e in entries] == [-1.4, -3.2, -7.9]
        assert source.get_model_overview("punet")["best_agent_score"] == -1.4

    def test_a_missing_identity_row_is_shown_UNRANKED_beside_ranked_rows(self, tmp_path):
        root = _workspace(
            tmp_path,
            [_rec("a", -3.2, TIDMAD_ID), _rec("legacy", 99.0, None), _rec("c", -1.4, TIDMAD_ID)],
        )
        source = LocalJsonDataSource(root)
        entries = source.get_leaderboard("punet", top_n=10)
        by_id = {e["exp_id"]: e for e in entries}

        assert by_id["legacy"]["rank"] is None
        assert METRIC_IDENTITY_UNAVAILABLE in by_id["legacy"]["metric_ranking"]
        assert by_id["legacy"]["denoising_score"] == 99.0, "the raw value must stay visible"
        assert by_id["a"]["rank"] == 2 and by_id["c"]["rank"] == 1

        overview = source.get_model_overview("punet")
        assert overview["best_agent_score"] == -1.4, (
            "the unranked row's larger score was treated as best"
        )
        assert overview["metric_identity_unavailable_rows"] == 1

    def test_an_all_missing_corpus_ranks_NOTHING_but_still_lists_the_rows(self, tmp_path):
        root = _workspace(tmp_path, [_rec("a", -3.2, None), _rec("b", -1.4, None)])
        source = LocalJsonDataSource(root)

        entries = source.get_leaderboard("punet", top_n=10)
        assert len(entries) == 2
        assert all(e["rank"] is None for e in entries)
        assert all(METRIC_IDENTITY_UNAVAILABLE in e["metric_ranking"] for e in entries)
        assert {e["denoising_score"] for e in entries} == {-3.2, -1.4}

        overview = source.get_model_overview("punet")
        assert overview["best_agent_score"] is None
        assert overview["best_run_name"] is None
        assert METRIC_IDENTITY_UNAVAILABLE in overview["metric_ranking_unavailable"]

    def test_a_conflicting_corpus_refuses_to_rank_across_the_conflict(self, tmp_path):
        root = _workspace(tmp_path, [_rec("a", -3.2, TIDMAD_ID), _rec("b", 0.017, DAVIS_ID)])
        source = LocalJsonDataSource(root)

        entries = source.get_leaderboard("punet", top_n=10)
        assert all(e["rank"] is None for e in entries)
        assert all("fixture_mse" in e["metric_ranking"] for e in entries)

        overview = source.get_model_overview("punet")
        assert overview["best_agent_score"] is None
        assert "fixture_mse" in overview["metric_ranking_unavailable"]

    def test_best_run_name_follows_the_declared_direction(self, tmp_path):
        """`best_run_name` must not drift from `best_agent_score`."""
        root = _workspace(tmp_path, [_rec("a", 0.02, DAVIS_ID), _rec("b", 0.01, DAVIS_ID)])
        overview = LocalJsonDataSource(root).get_model_overview("punet")
        assert overview["best_agent_score"] == 0.01
        assert overview["best_run_name"] == "v1"


class TestTheOperatorProseStatesNoFixedDirection:
    """P-1 / P-2: the two prose sites that literally said 'higher is better'."""

    @pytest.mark.parametrize(
        "relative",
        ["src/dashboard/data_sources/base.py", "src/dashboard/api/router.py"],
    )
    def test_the_prose_no_longer_asserts_a_universal_direction(self, relative):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[3] / relative).read_text(encoding="utf-8")
        offending = "ranked by denoising_score descending (higher is better)"
        assert offending not in source, (
            f"{relative} still states a direction that is only true of TIDMAD"
        )
