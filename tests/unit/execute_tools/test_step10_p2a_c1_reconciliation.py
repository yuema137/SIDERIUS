"""Step 10 / P2a — C1: the shared reconciliation authority and the live-workflow sites.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2a_golden_metric_order_closure.md`` §4.1 (the truth table), §4.1a
(Q-P2a-3 = PROMOTE), §4.2 (per-artifact unrankable), §6 (three-task fixtures).

The two questions this file keeps apart
---------------------------------------
Reconciliation asks *"are these the SAME metric?"*. ``MetricOrder`` asks *"for
this already-known metric, which value is better?"*. They are separate
responsibilities and the design forbids merging them, because ordering values
whose identity was never reconciled is exactly how two incomparable metrics get
ranked against each other while every individual comparison looks correct.

Identity is not direction
-------------------------
Accuracy, PSNR and the TIDMAD score are all ``higher``, and none is comparable
to the others. So ``direction == "higher"`` on both sides is NEVER proof that
two artifacts may be ranked together — the tests below assert on WHICH spec was
selected or WHICH refusal fired, never merely that a comparison happened.
"""

from __future__ import annotations

import pytest

from execute_tools.evaluation_metric import (
    METRIC_IDENTITY_UNAVAILABLE,
    MetricIdentityConflictError,
    StampedMetricSpec,
    metric_identity_unavailable_notice,
    reconcile_metric_specs,
)
from execute_tools.metric_order import MetricOrder
from tests.helpers.metric_fixtures import (
    accuracy_like_spec,
    direction_only_spec,
    error_like_spec,
    shipped_spec,
)
from tests.unit.execute_tools.test_step10_p2a_c0_ordering_goldens import (
    DAVIS_DIRECTION_BLIND_TRAJECTORY,
    DAVIS_INCUMBENT_DECISIONS,
    DAVIS_INCUMBENT_TRAJECTORY,
    DAVIS_SCORES,
    DAVIS_TARGET,
    DAVIS_TARGET_SATISFIED_CORRECT,
    PETS_INCUMBENT_DECISIONS,
    PETS_INCUMBENT_TRAJECTORY,
    PETS_SCORES,
    TIDMAD_INCUMBENT_DECISIONS,
    TIDMAD_INCUMBENT_TRAJECTORY,
    TIDMAD_SCORES,
)

TIDMAD = shipped_spec()
TIDMAD_LOWER = direction_only_spec()
PETS = accuracy_like_spec()
DAVIS = error_like_spec()


def _stamp(label: str, spec=None) -> StampedMetricSpec:
    return StampedMetricSpec(label=label, spec=spec)


class TestTheReconciliationTruthTable:
    """All six frozen rows of §4.1, each asserting WHICH spec or WHICH refusal."""

    def test_bound_A_and_stamped_A_reconcile_to_A(self):
        got = reconcile_metric_specs([_stamp("artifact", TIDMAD)], bound=TIDMAD)
        assert got == TIDMAD

    def test_bound_A_with_no_stamp_reconciles_to_A(self):
        """A composed run whose artifact predates stamping still ranks — on the
        metric the operator actually bound."""
        got = reconcile_metric_specs([], bound=TIDMAD)
        assert got == TIDMAD

    def test_bound_A_against_stamped_B_FAILS_CLOSED(self):
        """The row this whole promotion exists for.

        A bound spec is an authoritative INPUT, never permission to ignore what
        the artifact was actually scored under. Preferring either side would
        rank a number on a metric it was not produced by.
        """
        with pytest.raises(MetricIdentityConflictError) as excinfo:
            reconcile_metric_specs([_stamp("'run_b' ('wavenet')", DAVIS)], bound=TIDMAD)
        message = str(excinfo.value)
        assert "run_b" in message, "the refusal must name the offending artifact"
        assert TIDMAD.id in message and DAVIS.id in message
        assert "higher" in message and "lower" in message

    def test_no_bound_and_all_stamps_A_reconcile_to_A(self):
        got = reconcile_metric_specs(
            [_stamp("a", TIDMAD), _stamp("b", TIDMAD), _stamp("c", TIDMAD)]
        )
        assert got == TIDMAD

    def test_no_bound_and_all_stamps_absent_reconciles_to_None(self):
        """A NAMED absence, not a default. The caller takes its §4.2
        unrankable state; nothing here invents a direction."""
        assert reconcile_metric_specs([_stamp("a"), _stamp("b")]) is None

    def test_no_bound_and_conflicting_stamps_FAIL_CLOSED(self):
        with pytest.raises(MetricIdentityConflictError) as excinfo:
            reconcile_metric_specs([_stamp("'higher_run'", TIDMAD), _stamp("'lower_run'", DAVIS)])
        message = str(excinfo.value)
        assert "higher_run" in message and "lower_run" in message

    def test_an_empty_set_with_no_bound_reconciles_to_None(self):
        assert reconcile_metric_specs([]) is None


class TestIdentityIsNotDirection:
    """Matching direction is NEVER proof of comparability."""

    def test_two_different_metrics_that_are_both_higher_are_refused(self):
        """TIDMAD and an accuracy are both ``higher`` and are NOT comparable.

        A reconciliation that compared only ``direction`` would wave this
        through and then rank a dB-scale score against a [0,1] accuracy.
        """
        assert TIDMAD.direction == PETS.direction == "higher"
        with pytest.raises(MetricIdentityConflictError) as excinfo:
            reconcile_metric_specs([_stamp("'tidmad_run'", TIDMAD), _stamp("'pets_run'", PETS)])
        message = str(excinfo.value)
        assert TIDMAD.id in message and PETS.id in message

    def test_the_same_id_with_opposite_direction_is_refused(self):
        """The most dangerous disagreement: nothing about the identity looks
        wrong, and the ranking inverts."""
        assert TIDMAD.id != TIDMAD_LOWER.id or TIDMAD.direction != TIDMAD_LOWER.direction
        flipped = TIDMAD.model_copy(update={"direction": "lower"})
        assert flipped.id == TIDMAD.id
        with pytest.raises(MetricIdentityConflictError) as excinfo:
            reconcile_metric_specs([_stamp("'as_higher'", TIDMAD), _stamp("'as_lower'", flipped)])
        message = str(excinfo.value)
        assert "'higher'" in message and "'lower'" in message

    def test_partial_stamping_is_refused_and_names_the_offender(self):
        """A set mixing stamped and unstamped spans more than one binding.

        Callers that legitimately rank a SUBSET (§4.2 case B) must exclude
        their identity-less members BEFORE calling, so the exclusion is a
        visible act rather than a side effect of reconciliation.
        """
        with pytest.raises(MetricIdentityConflictError) as excinfo:
            reconcile_metric_specs([_stamp("'stamped'", TIDMAD), _stamp("'legacy'")])
        message = str(excinfo.value)
        assert "legacy" in message
        assert "No replacement spec is derived" in message


class TestExactlyOneReconciliationImplementation:
    """Q-P2a-3's structural half: the promotion must LEAVE one authority."""

    def test_the_interpreter_delegates_rather_than_reimplementing(self):
        """The node's function must not contain its own decision logic.

        MUTATION TARGET: restore the node's old inline comparison. The node
        keeps a PROJECTION (outputs -> labelled identity sources) and its own
        error type; the decision belongs to the shared authority.

        Read as SOURCE rather than imported: ``evidence`` is node-private, and
        ``tests/unit/nodes/test_node_public_boundary.py`` forbids importing a
        node's private modules from outside the node. Asserting on the text
        keeps this census from being the one place that breaks that rule.
        """
        import ast
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        module = repo_root / "nodes/result_interpretation_agent/evidence.py"
        tree = ast.parse(module.read_text(encoding="utf-8"))
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "reconcile_metric_spec"
        ]
        assert len(functions) == 1, "the node's projection function is missing or duplicated"
        source = ast.unparse(functions[0])

        assert "reconcile_metric_specs(" in source, (
            "the interpreter no longer delegates to the shared authority"
        )
        for reimplementation in (
            "cannot reconcile the run MetricSpec:",
            "disagreeing = ",
            "unstamped = ",
        ):
            assert reimplementation not in source, (
                f"the node re-implements reconciliation ({reimplementation!r}); "
                "exactly ONE implementation may exist, and it lives in "
                "execute_tools/evaluation_metric.py"
            )

    def test_the_repository_holds_one_reconciliation_decision_site(self):
        """Census: only the shared authority may raise the conflict.

        Counts production modules that construct the refusal, not modules that
        merely call or re-raise it.
        """
        import ast
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        raisers: list[str] = []
        for directory in ("agent", "core", "execute_tools", "nodes", "scripts", "workflows"):
            for path in sorted((repo_root / directory).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Raise) or node.exc is None:
                        continue
                    if "MetricIdentityConflictError(" in ast.unparse(node.exc):
                        raisers.append(str(path.relative_to(repo_root)))
        assert raisers == ["execute_tools/evaluation_metric.py"] * len(raisers), (
            f"metric-identity conflicts are constructed outside the one authority: {raisers}"
        )
        assert raisers, "the census found no raiser at all — it is looking at nothing"

    def test_reconciliation_is_not_inside_metric_order(self):
        """§4.1a: the two responsibilities stay apart.

        ``MetricOrder`` must remain the interpreter of a KNOWN metric's
        direction and must not acquire identity semantics.
        """
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        source = (repo_root / "execute_tools/metric_order.py").read_text(encoding="utf-8")
        assert "reconcile" not in source.lower().replace("reconciliation", "")
        assert "MetricIdentityConflictError" not in source


class TestTheCanonicalUnavailableNotice:
    """Q-P2a-2: ONE formatter, owned beside the reconciliation authority."""

    def test_the_notice_carries_the_canonical_phrase(self):
        notice = metric_identity_unavailable_notice("the chain incumbent")
        assert METRIC_IDENTITY_UNAVAILABLE in notice
        assert "the chain incumbent" in notice
        assert "NOT ranked" in notice

    def test_the_notice_never_claims_a_direction(self):
        notice = metric_identity_unavailable_notice("anything", detail="iteration 3")
        assert "iteration 3" in notice
        lowered = notice.lower()
        assert "higher is better" not in lowered
        assert "descending" not in lowered

    def test_the_notice_is_not_defined_in_metric_order(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        source = (repo_root / "execute_tools/metric_order.py").read_text(encoding="utf-8")
        assert "METRIC_IDENTITY_UNAVAILABLE" not in source


# ---------------------------------------------------------------------------
# The migrated fold — three tasks, on the VISITED DECISION SEQUENCE
# ---------------------------------------------------------------------------


def _visit(scores, order: MetricOrder) -> tuple[list[bool], list[float]]:
    """Replay sites 1/2's migrated predicate over a score sequence.

    Mirrors the production fold exactly: adopt when there is no incumbent,
    otherwise advance only on ``order.is_better`` — strictly better, so a tie
    keeps the earliest holder.
    """
    incumbent: float | None = None
    decisions: list[bool] = []
    trajectory: list[float] = []
    for score in scores:
        advanced = incumbent is None or order.is_better(score, incumbent)
        decisions.append(advanced)
        if advanced:
            incumbent = score
        assert incumbent is not None
        trajectory.append(incumbent)
    return decisions, trajectory


class TestTheMigratedFoldAcrossThreeTasks:
    """Every assertion is the C0 golden, compared as a SEQUENCE not a winner."""

    def test_tidmad_higher_with_negative_values_matches_the_c0_golden(self):
        decisions, trajectory = _visit(TIDMAD_SCORES, MetricOrder(TIDMAD))
        assert tuple(decisions) == TIDMAD_INCUMBENT_DECISIONS
        assert tuple(trajectory) == TIDMAD_INCUMBENT_TRAJECTORY
        assert trajectory[-1] == -1.4

    def test_pets_higher_matches_the_c0_golden(self):
        decisions, trajectory = _visit(PETS_SCORES, MetricOrder(PETS))
        assert tuple(decisions) == PETS_INCUMBENT_DECISIONS
        assert tuple(trajectory) == PETS_INCUMBENT_TRAJECTORY
        assert trajectory[-1] == 0.61

    def test_davis_lower_advances_on_a_DECREASE(self):
        """The inversion this commit exists to fix, asserted on the sequence."""
        decisions, trajectory = _visit(DAVIS_SCORES, MetricOrder(DAVIS))
        assert tuple(decisions) == DAVIS_INCUMBENT_DECISIONS
        assert tuple(trajectory) == DAVIS_INCUMBENT_TRAJECTORY
        assert trajectory[-1] == 0.0172

    def test_davis_no_longer_produces_the_direction_blind_trajectory(self):
        """The counterfactual C0 froze: proof the migration CHANGED something.

        Without this, a still-broken fold that happens to pass the other
        assertions would be indistinguishable from a fixed one.
        """
        _, trajectory = _visit(DAVIS_SCORES, MetricOrder(DAVIS))
        assert tuple(trajectory) != DAVIS_DIRECTION_BLIND_TRAJECTORY
        assert trajectory[-1] != max(DAVIS_SCORES)

    def test_a_tie_keeps_the_earliest_holder_under_both_directions(self):
        """`is_better` is STRICT, so the §3.3 earliest-wins rule survives."""
        for spec in (TIDMAD, DAVIS):
            decisions, _ = _visit((5.0, 5.0, 5.0), MetricOrder(spec))
            assert decisions == [True, False, False], (
                f"a tie advanced the incumbent under {spec.direction!r}"
            )


class TestTheMigratedEarlyStop:
    """Site 3 — ``is_at_least``, which under ``lower`` means ``<=``."""

    def test_davis_target_is_satisfied_by_the_smaller_score(self):
        order = MetricOrder(DAVIS)
        satisfied = [order.is_at_least(score, DAVIS_TARGET) for score in DAVIS_SCORES]
        assert tuple(satisfied) == DAVIS_TARGET_SATISFIED_CORRECT
        assert order.is_at_least(0.0172, DAVIS_TARGET) is True
        assert order.is_at_least(0.0174, DAVIS_TARGET) is False

    def test_tidmad_target_keeps_its_higher_semantics(self):
        order = MetricOrder(TIDMAD)
        assert order.is_at_least(-1.4, -2.0) is True
        assert order.is_at_least(-3.2, -2.0) is False

    def test_an_exact_hit_counts_as_reached_under_both_directions(self):
        assert MetricOrder(TIDMAD).is_at_least(-2.0, -2.0) is True
        assert MetricOrder(DAVIS).is_at_least(0.0173, 0.0173) is True


class TestTheWorkflowAcquiresItsOrderByReconciliation:
    """The production helper, exercised directly."""

    def test_a_composed_run_reconciles_bound_and_stamp(self):
        from workflows.model_exploration import _acquire_iteration_order

        order = _acquire_iteration_order(
            _Bindings(_Composition(_Metric(TIDMAD))), _Output(metric_spec=TIDMAD)
        )
        assert order is not None
        assert order.direction == "higher"

    def test_a_legacy_run_with_no_composition_uses_the_artifact_stamp(self):
        from workflows.model_exploration import _acquire_iteration_order

        order = _acquire_iteration_order(_Bindings(None), _Output(metric_spec=DAVIS))
        assert order is not None
        assert order.direction == "lower", (
            "an uncomposed run must still rank on what the artifact was scored under"
        )

    def test_no_identity_anywhere_yields_the_unrankable_state(self):
        from workflows.model_exploration import _acquire_iteration_order

        assert _acquire_iteration_order(_Bindings(None), _Output(metric_spec=None)) is None

    def test_a_bound_spec_covers_an_unstamped_legacy_artifact(self):
        from workflows.model_exploration import _acquire_iteration_order

        order = _acquire_iteration_order(
            _Bindings(_Composition(_Metric(DAVIS))), _Output(metric_spec=None)
        )
        assert order is not None
        assert order.direction == "lower"

    def test_a_bound_stamp_conflict_raises_rather_than_ranking(self):
        from workflows.model_exploration import _acquire_iteration_order

        with pytest.raises(MetricIdentityConflictError):
            _acquire_iteration_order(
                _Bindings(_Composition(_Metric(TIDMAD))), _Output(metric_spec=DAVIS)
            )


class TestTheOncePerRunNotice:
    """The unrankable notice fires ONCE, and counts what followed."""

    def test_it_prints_once_and_records_every_affected_context(self, capsys):
        from workflows.model_exploration import _OncePerRunNotice

        notice = _OncePerRunNotice()
        notice.warn_once("iteration 1")
        notice.warn_once("iteration 2")
        notice.warn_once("iteration 3")

        printed = capsys.readouterr().out
        assert printed.count(METRIC_IDENTITY_UNAVAILABLE) == 1, (
            "the notice must not repeat on every iteration"
        )
        assert "iteration 1" in printed
        assert notice.affected == ("iteration 1", "iteration 2", "iteration 3"), (
            "later unrankable iterations must still be counted, not discarded"
        )

    def test_a_run_that_never_hits_the_state_prints_nothing(self, capsys):
        from workflows.model_exploration import _OncePerRunNotice

        _OncePerRunNotice()
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Minimal stand-ins for the production carriers
# ---------------------------------------------------------------------------


class _Metric:
    def __init__(self, spec):
        self.spec = spec


class _Composition:
    def __init__(self, metric):
        self.metric = metric


class _Bindings:
    def __init__(self, task_composition):
        self.task_composition = task_composition


class _Output:
    run_name = "run_x"
    model_type = "wavenet"

    def __init__(self, metric_spec):
        self.metric_spec = metric_spec
