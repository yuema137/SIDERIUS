"""#1296 builtin measurements: protocol, child execution, aggregation and transport."""

from types import SimpleNamespace

import pytest
import torch

from execute_tools import candidate_measurement
from execute_tools.candidate_measurement import MeasurementRequest, measure_components, time_forward
from execute_tools.evaluation_aggregation import aggregate_evaluation
from execute_tools.evaluation_child import validate_child_evaluation
from execute_tools.evaluation_metric import (
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    PresenceScoreabilityContract,
)
from execute_tools.evaluation_spec import LatencyProtocol, MeasurementComponent
from execute_tools.measurement_results import (
    MeasurementNoise,
    MeasurementResult,
    MeasurementUnavailable,
    measurement_value,
    record_measurements,
)
from workflows.evaluation_composition import compose_evaluation, require_evaluation_runtime
from workflows.evaluation_selection import selection_binding

PRIMARY = MetricSpec(
    id="accuracy",
    direction="higher",
    aggregation="mean",
    scoreability=PresenceScoreabilityContract(),
)


def latency_component(**protocol):
    return {
        "kind": "measurement",
        "id": "latency",
        "measurement": "inference_latency_ms",
        "direction": "lower",
        "meaning": "Median forward latency.",
        "protocol": {"input_shape": [1, 4], **protocol},
    }


def composed():
    spec = {
        "components": [
            {"kind": "metric", "id": "quality", "metric": "accuracy", "meaning": "Accuracy"},
            latency_component(),
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
                        },
                        {
                            "component": "latency",
                            "weight": 1.0,
                            "lower": 0.0,
                            "upper": 10.0,
                            "out_of_range": "clip",
                        },
                    ]
                },
            },
        },
    }
    evaluation = compose_evaluation({"evaluation": spec}, ".", {PRIMARY.id: PRIMARY}, None)
    assert evaluation is not None
    return evaluation


def measured(value=None, failure=None):
    return MeasurementResult(
        component_id="latency",
        measurement="inference_latency_ms",
        unit="ms",
        value=value,
        noise=None if value is None else MeasurementNoise(repeats=5, iqr=0.1),
        failure=failure,
    )


def test_latency_protocol_is_required_and_exclusive_to_latency():
    """Dropping the applicability validator would accept an untimed latency declaration."""
    with pytest.raises(ValueError, match="requires a protocol"):
        MeasurementComponent.model_validate({**latency_component(), "protocol": None})
    with pytest.raises(ValueError, match="takes no protocol"):
        MeasurementComponent.model_validate({**latency_component(), "measurement": "model_bytes"})


def test_time_forward_reports_median_of_timed_repeats_excluding_warmup():
    """A mean, or timing warm-up forwards, changes the reported value."""
    ticks = iter([0.0, 100.0, 100.0, 100.001, 100.001, 100.003, 100.003, 100.010])
    calls = []
    value, noise = time_forward(
        lambda: calls.append(1),
        LatencyProtocol(input_shape=(1,), warmup=1, repeats=3),
        clock=lambda: next(ticks),
    )
    assert len(calls) == 4
    assert value == pytest.approx(2.0)  # samples 1, 2, 7 ms: median 2, mean 3.33
    assert noise.repeats == 3


def test_child_measures_the_checkpoint_and_records_failures(monkeypatch, tmp_path):
    """Builtin values come from the loaded model/checkpoint; a failure never raises."""
    checkpoint = tmp_path / "model.pth"
    model = torch.nn.Linear(4, 2)
    model.bias.requires_grad_(False)
    torch.save(model.state_dict(), checkpoint)
    monkeypatch.setattr(candidate_measurement._LoadedCandidate, "model", lambda self: model)
    request = MeasurementRequest(
        model_type="tiny",
        experiment_id="e",
        model_configuration={},
        loss_type="mse",
        checkpoint_path=str(checkpoint),
    )
    components = [
        MeasurementComponent.model_validate(
            {**latency_component(), "id": cid, "measurement": kind, "protocol": None}
        )
        for cid, kind in (
            ("trainable", "trainable_parameter_count"),
            ("total", "total_parameter_count"),
            ("bytes", "model_bytes"),
        )
    ]
    components.append(MeasurementComponent.model_validate(latency_component(warmup=1, repeats=3)))
    components.append(
        MeasurementComponent.model_validate(
            {**latency_component(), "id": "bad", "protocol": {"input_shape": [1, 5]}}
        )
    )
    results = {r.component_id: r for r in measure_components(components, request)}
    assert results["trainable"].value == 8.0
    assert results["total"].value == 10.0
    assert results["bytes"].value == float(checkpoint.stat().st_size)
    assert results["latency"].value is not None and results["latency"].noise.repeats == 3
    assert results["bad"].value is None and "RuntimeError" in results["bad"].failure
    assert results["bytes"].checkpoint_sha256 == results["latency"].checkpoint_sha256


def test_measurement_term_feeds_utility_and_failure_is_not_scoreable():
    """Measurement values enter the aggregate; a failed one refuses with its reason."""
    evaluation = composed()
    quality = MetricResult(metric_id="accuracy", direction="higher", scalar=1.0)
    outcome, evidence = aggregate_evaluation(
        evaluation, PRIMARY, quality, [], {"latency": measured(value=5.0)}
    )
    assert outcome.scalar == pytest.approx(0.75)
    refused, evidence = aggregate_evaluation(
        evaluation, PRIMARY, quality, [], {"latency": measured(failure="TimeoutError: slow")}
    )
    assert isinstance(refused, NotScoreableResult)
    assert "TimeoutError: slow" in evidence.failures[0].detail


def test_parent_rejects_a_measurement_value_that_disagrees_with_its_term():
    """The parent re-derives terms from transported measurement results, not child numbers."""
    evaluation = composed()
    quality = MetricResult(metric_id="accuracy", direction="higher", scalar=1.0)
    outcome, evidence = aggregate_evaluation(
        evaluation, PRIMARY, quality, [], {"latency": measured(value=5.0)}
    )
    composition = SimpleNamespace(metric=SimpleNamespace(spec=PRIMARY), evaluation=evaluation)
    carrier = SimpleNamespace(selection_binding=selection_binding(composition))
    payload = {
        "evaluation_result": evidence.model_dump(mode="json"),
        "denoising_score": outcome.scalar,
        "metric_result": outcome.model_dump(mode="json"),
        "measurement_results": [measured(value=5.0).model_dump(mode="json")],
    }
    assert validate_child_evaluation(payload, carrier) == evidence
    payload["measurement_results"] = [measured(value=6.0).model_dump(mode="json")]
    with pytest.raises(ValueError, match="raw value disagrees"):
        validate_child_evaluation(payload, carrier)


def test_measurement_formula_launches_and_record_accessor_fails_closed():
    """Capability, admission and the #1295 accessor agree on runtime measurement support."""
    require_evaluation_runtime(composed())
    record = {"measurement_results": [measured(failure="OOM").model_dump(mode="json")]}
    with pytest.raises(MeasurementUnavailable, match="failed: OOM"):
        measurement_value(record, "latency")
    with pytest.raises(MeasurementUnavailable, match="not recorded"):
        measurement_value({}, "latency")
    assert record_measurements({}) == {}
