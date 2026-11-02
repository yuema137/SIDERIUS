"""Formula arithmetic must change selection without changing source Health units."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from execute_tools.evaluation_aggregation import aggregate_evaluation
from execute_tools.evaluation_child import source_health_inputs, validate_child_evaluation
from execute_tools.evaluation_metric import (
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    PresenceScoreabilityContract,
)
from execute_tools.metric_order import MetricOrder
from workflows.evaluation_composition import compose_evaluation
from workflows.evaluation_selection import effective_metric_spec, selection_binding


def declared_metric(name, direction):
    return MetricSpec(
        id=name,
        direction=direction,
        aggregation="mean",
        scoreability=PresenceScoreabilityContract(),
    )


def composed(*, policy="refuse", huge=False):
    primary = declared_metric("accuracy", "higher")
    secondary = declared_metric("error", "lower")
    weight = 1e308 if huge else 3.0
    spec = {
        "components": [
            {"kind": "metric", "id": "quality", "metric": "accuracy", "meaning": "Accuracy"},
            {"kind": "metric", "id": "error", "metric": "error", "meaning": "Error"},
        ],
        "selection": {
            "kind": "formula",
            "formula": {
                "family": "weighted_sum",
                "params": {
                    "terms": [
                        {
                            "component": "quality",
                            "weight": weight,
                            "lower": 0.0,
                            "upper": 1.0,
                            "out_of_range": policy,
                        },
                        {
                            "component": "error",
                            "weight": 1e308 if huge else 1.0,
                            "lower": 0.0,
                            "upper": 10.0,
                            "out_of_range": policy,
                        },
                    ]
                },
            },
        },
    }
    evaluation = compose_evaluation(
        {"evaluation": spec}, ".", {m.id: m for m in (primary, secondary)}, None
    )
    assert evaluation is not None
    return primary, evaluation


def result(name, direction, value, **kwargs):
    return MetricResult(metric_id=name, direction=direction, scalar=value, **kwargs)


def test_weighted_selection_reverses_primary_preference_and_keeps_source():
    """Reverting scalar replacement or lower-direction conversion chooses the wrong candidate."""
    spec, evaluation = composed()
    first, evidence = aggregate_evaluation(
        evaluation, spec, result("accuracy", "higher", 0.8), [result("error", "lower", 2.0)]
    )
    second, _ = aggregate_evaluation(
        evaluation, spec, result("accuracy", "higher", 0.9), [result("error", "lower", 10.0)]
    )
    assert isinstance(first, MetricResult) and isinstance(second, MetricResult)
    assert first.scalar == 0.8 and second.scalar == 0.675
    assert [c.normalized for c in evidence.components] == [0.8, 0.2]
    assert [c.contribution for c in evidence.components] == [0.6, 0.2]
    assert evidence.source_metric_result.scalar == 0.8
    assert (
        MetricOrder(effective_metric_spec(spec, evaluation)).best(
            [first, second], key=lambda r: r.scalar
        )
        is first
    )
    assert first.per_sample is None


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_required_nonfinite_component_is_a_named_refusal(value):
    spec, evaluation = composed()
    outcome, evidence = aggregate_evaluation(
        evaluation, spec, result("accuracy", "higher", 0.8), [result("error", "lower", value)]
    )
    assert isinstance(outcome, NotScoreableResult)
    assert any(f.requirement == "error" for f in outcome.verdict.failures)
    assert evidence.aggregate is None
    assert "NaN" not in evidence.model_dump_json()


def test_clip_and_refuse_never_use_descriptive_ranges_or_drop_terms():
    spec, evaluation = composed()
    refused, _ = aggregate_evaluation(evaluation, spec, result("accuracy", "higher", 2.0), [])
    assert isinstance(refused, NotScoreableResult)
    assert {f.requirement for f in refused.verdict.failures} == {"quality", "error"}
    spec, evaluation = composed(policy="clip")
    success, evidence = aggregate_evaluation(
        evaluation, spec, result("accuracy", "higher", 2.0), [result("error", "lower", 2.0)]
    )
    assert success.scalar == 0.95
    assert evidence.components[0].raw == 2.0 and evidence.components[0].normalized == 1.0
    assert evidence.components[0].clipped


def test_finite_weight_sum_overflow_is_not_a_refusal_or_nan():
    spec, evaluation = composed(huge=True)
    outcome, _ = aggregate_evaluation(
        evaluation, spec, result("accuracy", "higher", 0.8), [result("error", "lower", 2.0)]
    )
    assert outcome.scalar == 0.8


def test_child_identity_and_health_projection_are_distinct():
    spec, evaluation = composed()
    source = result("accuracy", "higher", 0.2, per_sample=[0.1, 0.3])
    outcome, evidence = aggregate_evaluation(
        evaluation, spec, source, [result("error", "lower", 0.0)]
    )
    composition = SimpleNamespace(metric=SimpleNamespace(spec=spec), evaluation=evaluation)
    carrier = SimpleNamespace(selection_binding=selection_binding(composition))
    payload = {
        "evaluation_result": evidence.model_dump(mode="json"),
        "denoising_score": outcome.scalar,
        "metric_result": outcome.model_dump(mode="json"),
        "file_vector": None,
        "secondary_metric_results": [result("error", "lower", 0.0).model_dump(mode="json")],
    }
    assert validate_child_evaluation(payload, carrier) == evidence
    health = source_health_inputs(
        payload, {"denoising_score": outcome.scalar, "file_vector": [], "per_sample_evidence": None}
    )
    assert health["denoising_score"] == 0.2
    assert health["file_vector"] == [0.1, 0.3]
    payload["evaluation_result"]["evaluation_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="identity"):
        validate_child_evaluation(payload, carrier)


def test_listed_but_unreferenced_secondary_stays_observational():
    spec, evaluation = composed()
    selection = evaluation.spec.selection
    formula = selection.formula.model_copy(
        update={
            "params": selection.formula.params.model_copy(
                update={"terms": selection.formula.params.terms[:1]}
            )
        }
    )
    evaluation = replace(
        evaluation,
        spec=evaluation.spec.model_copy(
            update={"selection": selection.model_copy(update={"formula": formula})}
        ),
    )
    outcome, _ = aggregate_evaluation(evaluation, spec, result("accuracy", "higher", 0.8), [])
    assert outcome.scalar == 0.8


def test_production_child_emits_utility_and_source_evidence(monkeypatch, tmp_path):
    """Exercise the child scoring entry and its real JSON emitter, not a copied formula."""
    import json
    from contextlib import nullcontext

    from execute_tools import denoising_score_single as scoring

    spec, evaluation = composed()
    composition = SimpleNamespace(metric=SimpleNamespace(spec=spec), evaluation=evaluation)

    class DataPath:
        task_data_path_id = "evaluation_fixture"

        def read_evaluation_payload(self, request):
            return {"prediction": 1}

    class Metric:
        def evaluate(self, deliverables, **kwargs):
            return result("accuracy", "higher", 0.8, per_sample=[0.7, 0.9])

    output = tmp_path / "score.json"
    output.write_text("{}")
    args = SimpleNamespace(
        task_eval_scope_ref="scope",
        task_eval_scope_digest="digest",
        data_dir=str(tmp_path),
        raw_data_dir=str(tmp_path),
        exp_id="e",
        run_name="run",
        denoising_model="model",
        output_json=str(output),
    )
    monkeypatch.setattr(scoring, "_resolve_child_data_path", lambda _: DataPath())
    monkeypatch.setattr(
        "execute_tools.scope_artifact.load_transported_scope", lambda *a, **kw: object()
    )
    monkeypatch.setattr(
        "execute_tools.deliverable_spec.declared_naming_binding", lambda _: nullcontext()
    )
    monkeypatch.setattr(
        "execute_tools.task_data_path.task_declared_deliverable_name", lambda *a: "prediction.bin"
    )
    monkeypatch.setattr(
        scoring,
        "_evaluate_task_owned_secondaries",
        lambda *a: {
            "secondary_metric_results": [result("error", "lower", 10.0).model_dump(mode="json")]
        },
    )
    scoring._emit_task_owned_score(args, object(), Metric(), composition=composition)
    payload = json.loads(output.read_text())
    assert payload["denoising_score"] == 0.6
    assert payload["metric_result"]["metric_id"] == effective_metric_spec(spec, evaluation).id
    assert payload["file_vector"] is None
    assert payload["evaluation_result"]["source_metric_result"]["per_sample"] == [0.7, 0.9]


def test_persisted_evidence_cannot_change_the_effective_scalar():
    from execute_tools.evaluation_results import validate_record_evaluation

    spec, evaluation = composed()
    outcome, evidence = aggregate_evaluation(
        evaluation, spec, result("accuracy", "higher", 0.8), [result("error", "lower", 2.0)]
    )
    validate_record_evaluation(evidence, outcome, None)
    with pytest.raises(ValueError, match="disagrees"):
        validate_record_evaluation(evidence.model_copy(update={"aggregate": 0.9}), outcome, None)


def test_record_readback_rejects_a_tampered_aggregate():
    from agent.schemas.hyperparam_tuning import ExperimentRecord

    spec, evaluation = composed()
    outcome, evidence = aggregate_evaluation(
        evaluation, spec, result("accuracy", "higher", 0.8), [result("error", "lower", 2.0)]
    )
    payload = {
        "exp_id": "a",
        "status": "success",
        "model_type": "synthetic",
        "timestamp": "2026-11-01",
        "params": {},
        "denoising_score": 0.8,
        "metric_result": outcome.model_dump(mode="json"),
        "evaluation_result": evidence.model_dump(mode="json"),
    }
    ExperimentRecord.model_validate(payload)
    payload["evaluation_result"]["aggregate"] = 0.9
    with pytest.raises(ValueError, match="Evaluation evidence disagrees"):
        ExperimentRecord.model_validate(payload)


def test_duplicate_source_result_ids_fail_transport_instead_of_keeping_the_last():
    """Review N2: a dict build silently kept the later of two `error` results."""
    from execute_tools.evaluation_results import EvaluationTransportError

    spec, evaluation = composed()
    with pytest.raises(EvaluationTransportError, match="duplicate source metric result 'error'"):
        aggregate_evaluation(
            evaluation,
            spec,
            result("accuracy", "higher", 0.8),
            [result("error", "lower", 10.0), result("error", "lower", 2.0)],
        )


def test_source_primary_refusal_blocks_a_formula_that_does_not_reference_it():
    """The source primary is required evidence even when no term names it.

    Health and scientific scoring read it; dropping the rule would publish a
    utility for a candidate whose task metric refused.
    """
    spec, evaluation = composed()
    selection = evaluation.spec.selection
    formula = selection.formula.model_copy(
        update={
            "params": selection.formula.params.model_copy(
                update={"terms": selection.formula.params.terms[1:]}
            )
        }
    )
    evaluation = replace(
        evaluation,
        spec=evaluation.spec.model_copy(
            update={"selection": selection.model_copy(update={"formula": formula})}
        ),
    )
    refused = NotScoreableResult(
        metric_id="accuracy",
        direction="higher",
        verdict=PresenceScoreabilityContract().check({}),
    )
    outcome, evidence = aggregate_evaluation(
        evaluation, spec, refused, [result("error", "lower", 2.0)]
    )
    assert isinstance(outcome, NotScoreableResult)
    assert [f.requirement for f in outcome.verdict.failures] == ["source_primary"]
    assert evidence.aggregate is None and evidence.source_metric_result is None


def test_persisted_effective_spec_round_trips_to_an_equal_spec():
    """Worker/tuner `!=` checks compare a composed effective spec with its JSON readback.

    Without the framework contract registration the readback was a data-only
    PersistedScoreabilityContract and every formula candidate was refused.
    """
    import json

    from execute_tools.evaluation_metric import metric_spec_from_persisted_record

    spec, evaluation = composed()
    effective = effective_metric_spec(spec, evaluation)
    readback = metric_spec_from_persisted_record(json.loads(effective.model_dump_json()))
    assert readback == effective


@pytest.mark.parametrize("declares_evaluation", [False, True])
def test_scoring_child_composes_full_bindings_only_for_declared_evaluation(
    monkeypatch, tmp_path, declares_evaluation
):
    """Review B3: every absent-evaluation scoring child paid a full plugin/code load.

    Drives the production child entry `main`; the full composer must not run
    without an `evaluation` section and must run exactly once with one.
    """
    from execute_tools import denoising_score_single as scoring
    from execute_tools.task_registration_scope import run_registration_scope
    from tests.helpers.composed_manifest import write_complete_manifest
    from workflows import task_composition

    evaluation = {
        "components": [
            {"kind": "metric", "id": "quality", "metric": "accuracy", "meaning": "Accuracy"}
        ],
        "selection": {
            "kind": "formula",
            "formula": {
                "family": "weighted_sum",
                "params": {
                    "terms": [
                        {
                            "component": "quality",
                            "weight": 1.0,
                            "lower": 0.0,
                            "upper": 1.0,
                            "out_of_range": "refuse",
                        }
                    ]
                },
            },
        },
    }
    manifest = write_complete_manifest(
        tmp_path, **({"evaluation": evaluation} if declares_evaluation else {})
    )
    composed_calls = []
    real_compose = task_composition.compose_run_task_bindings

    def spy(path):
        composed_calls.append(path)
        return real_compose(path)

    emitted = {}
    monkeypatch.setattr(task_composition, "compose_run_task_bindings", spy)
    monkeypatch.setattr(
        scoring,
        "_emit_task_owned_score",
        lambda args, profile, metric, **kw: emitted.update(metric=metric, **kw),
    )
    data = tmp_path / "data"
    data.mkdir()
    argv = ["--task_manifest", str(manifest), "--task_data_path_id", "quickstart_tabular"]
    profile = tmp_path / "examples/quickstart/declared/dataset_profile.json"
    argv += ["--dataset_profile_json", str(profile), "--task_eval_scope_ref", "scope.json"]
    argv += ["--task_eval_scope_digest", "0" * 64, "--data_dir", str(data)]
    argv += ["--raw_data_dir", str(data)]
    with run_registration_scope():
        scoring.main(argv)
    assert emitted["metric"].spec.id == "accuracy"
    if declares_evaluation:
        assert composed_calls == [str(manifest)]
        assert emitted["composition"].selection_binding is not None
    else:
        assert composed_calls == []
        assert emitted["composition"] is None
