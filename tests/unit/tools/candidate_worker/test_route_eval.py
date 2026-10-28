"""Pure route evaluator: hardcoded literals, no workspace except the projection record."""

import hashlib

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.validator import ValidatorOutput
from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
from tools.candidate_worker.route_eval import (
    RouteConditionError,
    RouteEvaluationInput,
    RouteObservation,
    admit_route_metrics,
    evaluate_route,
    project_observation,
)
from workflows.definition import (
    AnyOf,
    BoolIs,
    Branch,
    EnumIn,
    IsMissing,
    MetricAtLeast,
    Not,
    ResultSource,
    RouteCase,
)


def spec(direction="higher", metric_id="score"):
    return MetricSpec(
        id=metric_id,
        direction=direction,
        aggregation="mean",
        scoreability=PresenceScoreabilityContract(),
    )


def branch(*whens, default=("d",)):
    return Branch(
        id="b",
        source=ResultSource(node="s"),
        cases=tuple(RouteCase(when=when, targets=(f"c{i}",)) for i, when in enumerate(whens)),
        default=default,
    )


def decide(route, values, *, metric=None, stamp=None):
    observation = RouteObservation(
        source_node="s", iteration=1, record_sha256="0" * 64, values=values, metric_spec=stamp
    )
    return evaluate_route(
        RouteEvaluationInput(branch=route, observation=observation, metric=metric)
    )


PASSED = BoolIs(observable="validation.passed", value=True)
FAILED = BoolIs(observable="validation.passed", value=False)
AT_LEAST = MetricAtLeast(observable="tuning.valid_formal", metric_id="score", threshold=0.5)


def test_first_matching_case_wins_in_declared_order():
    """A last-match or unordered evaluator selects c1 or c2 here, not c0."""
    output = decide(branch(FAILED, PASSED, PASSED), (("validation.passed", True),))
    assert output.selected_case == 1
    assert output.leaf_results == (False, True)
    assert output.selected_targets == ("c1",)
    assert output.skipped_targets == ("c0", "c2", "d")


@pytest.mark.parametrize(
    ("default", "selected", "skipped"),
    [(("d",), ("d",), ("c0",)), (None, (), ("c0",))],
)
def test_no_match_runs_default_or_no_arm(default, selected, skipped):
    """Without a default nothing runs; with one, only the default arm runs."""
    output = decide(branch(PASSED, default=default), (("validation.passed", False),))
    assert output.selected_case is None
    assert output.leaf_results == (False,)
    assert (output.selected_targets, output.skipped_targets) == (selected, skipped)


@pytest.mark.parametrize(
    ("direction", "score", "expected"),
    [
        # Fails on a hardcoded `>=`: 0.4 clears 0.5 only when lower is better.
        ("higher", 0.6, True),
        ("higher", 0.4, False),
        ("lower", 0.6, False),
        ("lower", 0.4, True),
        # Ties satisfy at_least under both directions.
        ("higher", 0.5, True),
        ("lower", 0.5, True),
    ],
)
def test_metric_threshold_direction_comes_from_metric_spec(direction, score, expected):
    output = decide(branch(AT_LEAST), (("tuning.valid_formal", score),), metric=spec(direction))
    assert output.selected_case == (0 if expected else None)


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (AT_LEAST, False),
        (Not(term=AT_LEAST), True),
        (IsMissing(observable="tuning.valid_formal"), True),
        (AnyOf(terms=(AT_LEAST, IsMissing(observable="tuning.valid_formal"))), True),
    ],
)
def test_missing_metric_is_a_false_leaf_not_an_error(when, expected):
    """Decision B1-Q4: an absent score makes metric_at_least false; is_missing names it."""
    output = decide(branch(when), (("tuning.valid_formal", None),), metric=spec())
    assert output.selected_case == (0 if expected else None)


def test_present_metric_is_not_missing():
    output = decide(
        branch(IsMissing(observable="tuning.valid_formal")), (("tuning.valid_formal", 0.1),)
    )
    assert output.selected_case is None


@pytest.mark.parametrize("metric", [None, spec(metric_id="other")])
def test_unevaluable_metric_declaration_is_refused_even_behind_a_match(metric):
    """Case 0 matches first, but the later metric case must still be refused."""
    route = branch(PASSED, AT_LEAST)
    with pytest.raises(RouteConditionError, match="case 1 \\(metric_at_least\\)"):
        admit_route_metrics((route,), metric)
    with pytest.raises(RouteConditionError, match="case 1"):
        decide(route, (("validation.passed", True), ("tuning.valid_formal", 0.9)), metric=metric)


def test_record_stamp_conflicting_with_run_metric_is_refused():
    """Same id, opposite direction: the ranking would silently invert."""
    with pytest.raises(RouteConditionError):
        decide(
            branch(AT_LEAST),
            (("tuning.valid_formal", 0.9),),
            metric=spec("higher"),
            stamp=spec("lower"),
        )


@pytest.mark.parametrize(
    ("when", "values"),
    [
        (PASSED, ()),  # projection omitted a read observable
        (PASSED, (("validation.passed", None),)),  # wrong value kind is not "false"
        (EnumIn(observable="tuning.status", values=("failed",)), (("tuning.status", 1.0),)),
        (AnyOf(terms=(PASSED, FAILED)), (("validation.passed", "yes"),)),
    ],
)
def test_unevaluable_observation_fails_instead_of_false(when, values):
    with pytest.raises(RouteConditionError):
        decide(branch(when), values)


def test_projection_reads_only_branch_observables_and_binds_record_bytes(tmp_path):
    """A wrong field, an extra observable or a digest over other bytes changes equality."""
    record = HyperparamTuningOutput(
        run_name="r",
        model_type="m",
        file_index=0,
        status="partial",
        completed_rounds=1,
        total_attempts=1,
        started_at="t0",
        finished_at="t1",
        best_valid_formal_denoising_score=0.25,
        metric_spec=spec("lower"),
    )
    path = tmp_path / "tuning.json"
    path.write_text(record.model_dump_json())
    route = Branch(
        id="b",
        source=ResultSource(node="t"),
        cases=(
            RouteCase(when=EnumIn(observable="tuning.status", values=("failed",)), targets=("x",)),
            RouteCase(when=AT_LEAST, targets=("y",)),
        ),
    )
    observation = project_observation(route, "tuning", path, iteration=2)
    assert observation == RouteObservation(
        source_node="t",
        iteration=2,
        record_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        values=(("tuning.status", "partial"), ("tuning.valid_formal", 0.25)),
        metric_spec=spec("lower"),
    )
    output = evaluate_route(
        RouteEvaluationInput(branch=route, observation=observation, metric=spec("lower"))
    )
    assert output.selected_targets == ("y",)


def test_projection_of_validation_record(tmp_path):
    record = ValidatorOutput(
        passed=False,
        model_type="m",
        plugin_registered=True,
        tests_passed=True,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=True,
        gradient_check_passed=True,
        llm_review_passed=False,
    )
    path = tmp_path / "validation.json"
    path.write_text(record.model_dump_json())
    route = Branch(
        id="b", source=ResultSource(node="v"), cases=(RouteCase(when=FAILED, targets=("x",)),)
    )
    observation = project_observation(route, "validation", path, iteration=1)
    assert observation.values == (("validation.passed", False),)
    assert observation.metric_spec is None
    with pytest.raises(RouteConditionError, match=r"not on validation\.output"):
        project_observation(branch(AT_LEAST), "validation", path, iteration=1)
