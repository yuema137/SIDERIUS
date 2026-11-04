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
from execute_tools.evaluation_results import EvaluationTransportError
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


def test_constraint_on_a_measurement_launches_and_fails_closed():
    """#1295 x #1296: a measurement constraint admits and a failed measurement is infeasible."""
    from execute_tools.evaluation_aggregation import constrain_primary

    spec = {
        "components": [
            {"kind": "metric", "id": "quality", "metric": "accuracy", "meaning": "Accuracy"},
            latency_component(),
        ],
        "selection": {"kind": "primary"},
        "constraints": [{"component": "latency", "op": "<=", "threshold": 5.0}],
    }
    evaluation = compose_evaluation({"evaluation": spec}, ".", {PRIMARY.id: PRIMARY}, None)
    require_evaluation_runtime(evaluation)
    quality = MetricResult(metric_id="accuracy", direction="higher", scalar=0.9)
    ok, _ = constrain_primary(evaluation, PRIMARY, quality, [], {"latency": measured(value=4.0)})
    assert ok.scalar == 0.9
    for measurements in ({"latency": measured(failure="TimeoutError")}, {}):
        refused, evidence = constrain_primary(evaluation, PRIMARY, quality, [], measurements)
        assert isinstance(refused, NotScoreableResult)
        assert "has no finite value" in evidence.failures[0].detail
    refused, evidence = constrain_primary(
        evaluation, PRIMARY, quality, [], {"latency": measured(failure="TimeoutError: slow")}
    )
    assert "measurement failed: TimeoutError: slow" in evidence.failures[0].detail  # F5


def _builtin_checkpoint(tmp_path):
    """A real registered model's checkpoint plus the trainer completion sentinel."""
    from core.sandbox_layout import training_checkpoint_path
    from execute_tools.inference_model import construct_inference_model
    from ml_models.models_format_sandbox import get_config_class

    config = get_config_class("transformer")().model_dump(mode="json")
    model, _ = construct_inference_model(
        "transformer", config, model_io_contract=None, loss_type="mse"
    )
    path = training_checkpoint_path(tmp_path, "transformer", "e")
    torch.save(model.state_dict(), path)
    (tmp_path / "_OK_e").write_text("")
    request = MeasurementRequest(
        model_type="transformer",
        experiment_id="e",
        model_configuration=config,
        loss_type="mse",
        checkpoint_path=str(path),
    )
    return request, sum(p.numel() for p in model.parameters() if p.requires_grad)


def _count_components():
    return [
        MeasurementComponent.model_validate(
            {**latency_component(), "id": cid, "measurement": kind, "protocol": None}
        )
        for cid, kind in (("trainable", "trainable_parameter_count"), ("bytes", "model_bytes"))
    ]


def test_isolated_worker_measures_a_real_checkpoint_and_is_killed_at_its_deadline(
    monkeypatch, tmp_path
):
    """F3: measurement runs in a supervised worker process with a hard deadline."""
    from core.subprocess_env import subprocess_env

    request, trainable = _builtin_checkpoint(tmp_path)
    components = _count_components()
    worker = candidate_measurement.run_measurement_worker
    kwargs = {"env": subprocess_env(), "preexec_fn": None, "rss_limit_bytes": 8 * 1024**3}
    results = worker(request, components, directory=str(tmp_path / "ok"), **kwargs)
    assert [r.value for r in results] == [
        float(trainable),
        float((tmp_path / "model_transformer_e_agent.pth").stat().st_size),
    ]
    monkeypatch.setattr(candidate_measurement, "MEASUREMENT_LOAD_ALLOWANCE_SECONDS", 0.05)
    killed = worker(request, components, directory=str(tmp_path / "slow"), **kwargs)
    assert all(r.value is None and "deadline" in r.failure for r in killed)


def test_scoring_child_never_runs_candidate_code_for_measurements(monkeypatch, tmp_path):
    """F3: hostile model code cannot patch aggregation; the child only reads results."""
    import json
    from contextlib import nullcontext

    from execute_tools import denoising_score_single as scoring
    from execute_tools import evaluation_aggregation

    def hostile(*args, **kwargs):  # what a model plugin could do if it ran here
        monkeypatch.setattr(evaluation_aggregation, "term_evaluation", lambda *a, **k: 1 / 0)
        raise AssertionError("candidate model code ran in the scoring child")

    monkeypatch.setattr("execute_tools.inference_model.construct_inference_model", hostile)
    monkeypatch.setattr(candidate_measurement, "measure_components", hostile)
    evaluation = composed()
    composition = SimpleNamespace(metric=SimpleNamespace(spec=PRIMARY), evaluation=evaluation)
    measurements = tmp_path / "measurement_results.json"
    measurements.write_text(json.dumps([measured(value=5.0).model_dump(mode="json")]))
    output = tmp_path / "score.json"
    output.write_text("{}")

    class DataPath:
        task_data_path_id = "evaluation_fixture"

        def read_evaluation_payload(self, request):
            return {}

    class Metric:
        def evaluate(self, deliverables, **kwargs):
            return MetricResult(metric_id="accuracy", direction="higher", scalar=1.0)

    monkeypatch.setattr(scoring, "_resolve_child_data_path", lambda _: DataPath())
    monkeypatch.setattr(scoring, "_evaluate_task_owned_secondaries", lambda *a: {})
    monkeypatch.setattr(
        "execute_tools.scope_artifact.load_transported_scope", lambda *a, **kw: object()
    )
    monkeypatch.setattr(
        "execute_tools.deliverable_spec.declared_naming_binding", lambda _: nullcontext()
    )
    monkeypatch.setattr(
        "execute_tools.task_data_path.task_declared_deliverable_name", lambda *a: "p.bin"
    )
    args = SimpleNamespace(
        task_eval_scope_ref="s",
        task_eval_scope_digest="d",
        data_dir=str(tmp_path),
        raw_data_dir=str(tmp_path),
        exp_id="e",
        run_name="run",
        denoising_model="model",
        output_json=str(output),
        measurement_results_json=str(measurements),
    )
    scoring._emit_task_owned_score(args, object(), Metric(), composition=composition)
    payload = json.loads(output.read_text())
    assert payload["denoising_score"] == pytest.approx(0.75)
    assert payload["measurement_results"][0]["value"] == 5.0


def test_parent_rejects_a_measurement_roster_or_kind_mismatch():
    """F4: transported results must be exactly the declared components and kinds."""
    evaluation = composed()
    quality = MetricResult(metric_id="accuracy", direction="higher", scalar=1.0)
    outcome, evidence = aggregate_evaluation(
        evaluation, PRIMARY, quality, [], {"latency": measured(value=5.0)}
    )
    composition = SimpleNamespace(metric=SimpleNamespace(spec=PRIMARY), evaluation=evaluation)
    carrier = SimpleNamespace(selection_binding=selection_binding(composition))
    wrong_kind = measured(value=5.0).model_copy(
        update={"measurement": "model_bytes", "unit": "bytes"}
    )
    extra = measured(value=5.0).model_copy(update={"component_id": "undeclared"})
    for roster in (
        [],
        [wrong_kind],
        [measured(value=5.0), measured(value=5.0)],
        [measured(value=5.0), extra],
    ):
        payload = {
            "evaluation_result": evidence.model_dump(mode="json"),
            "denoising_score": outcome.scalar,
            "metric_result": outcome.model_dump(mode="json"),
            "measurement_results": [m.model_dump(mode="json") for m in roster],
        }
        with pytest.raises(EvaluationTransportError, match="measurement"):
            validate_child_evaluation(payload, carrier)


def test_hostile_plugin_isolated_from_scoring_and_hung_forward_is_killed(monkeypatch, tmp_path):
    """Real plugin import/forward patches cannot cross the measurement process boundary."""
    import json
    import os
    import subprocess
    import sys
    import time

    from core.runtime_control.observed_subprocess import observe_process_lifecycle
    from core.sandbox_executor import TidmadSandbox
    from core.subprocess_env import subprocess_env

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    marker = tmp_path / "forward_pid"
    (plugin_dir / "hostile.py").write_text("""
import os
import time
from pathlib import Path
from pydantic import BaseModel
from torch import nn
from execute_tools import evaluation_aggregation, denoising_score_single

def poison(*args, **kwargs):
    raise AssertionError("candidate patched scoring")

evaluation_aggregation.term_evaluation = poison
class Config(BaseModel):
    hang: bool = False
class Model(nn.Linear):
    def __init__(self, config):
        super().__init__(4, 2)
        self.hang = config.hang
    def forward(self, value):
        denoising_score_single._emit_outcome = poison
        Path(os.environ["FORWARD_MARKER"]).write_text(str(os.getpid()))
        if self.hang:
            time.sleep(60)
        return super().forward(value)
PLUGIN_MODEL_TYPE = "hostile"
PLUGIN_CONFIG_CLASS = Config
PLUGIN_MODEL_CLASS = Model
PLUGIN_OUTPUT_TYPE = "regressor"
""")
    checkpoint = tmp_path / "model_hostile_e_agent.pth"
    torch.save(torch.nn.Linear(4, 2).state_dict(), checkpoint)
    (tmp_path / "_OK_e").write_text("")
    request = MeasurementRequest(
        model_type="hostile",
        experiment_id="e",
        model_configuration={},
        loss_type="mse",
        checkpoint_path=str(checkpoint),
    )
    components = [MeasurementComponent.model_validate(latency_component(warmup=1, repeats=3))]
    env = subprocess_env(plugin_dir=str(plugin_dir), cuda_visible_devices="")
    env["FORWARD_MARKER"] = str(marker)
    kwargs = {"env": env, "preexec_fn": None, "rss_limit_bytes": 8 * 1024**3}
    results = candidate_measurement.run_measurement_worker(
        request, components, directory=str(tmp_path), **kwargs
    )
    assert results[0].failure is None
    assert int(marker.read_text()) != os.getpid()
    argv = TidmadSandbox._measurement_results_argv(results, str(tmp_path))
    evaluation = composed()
    import shutil
    from pathlib import Path

    import yaml

    task = tmp_path / "task"
    fixture = Path(__file__).resolve().parents[2] / "fixtures/step10_p1/fourth_task"
    shutil.copytree(fixture, task)
    spec_path = task / "composition.yaml"
    manifest = yaml.safe_load(spec_path.read_text())
    (task / "primary.json").write_text(PRIMARY.model_dump_json())
    manifest["metric"] = {
        "declaration": "primary.json",
        "implementation": {"module": "execute_tools.evaluation_metric", "symbol": "AccuracyMetric"},
    }
    manifest["evaluation"] = evaluation.spec.model_dump(mode="json")
    manifest["model_plugins"] = {"dir": "../plugins", "require": ["hostile"]}
    spec_path.write_text(yaml.safe_dump(manifest))
    output = tmp_path / "score.json"
    output.write_text("{}")
    script = """
import json, sys
from types import SimpleNamespace
from execute_tools.denoising_score_single import _measure_declared_components, _emit_outcome
from execute_tools.evaluation_child import aggregate_child_outcome
from execute_tools.evaluation_metric import MetricResult, MetricSpec, PresenceScoreabilityContract
from workflows.task_composition import compose_scoring_child_bindings
from execute_tools.denoising_score_single import _compose_child_secondary_metrics
metric, composition = compose_scoring_child_bindings(sys.argv[1])
assert _compose_child_secondary_metrics(SimpleNamespace(task_manifest=sys.argv[1])) == ()
args = SimpleNamespace(measurement_results_json=sys.argv[2], output_json=sys.argv[3])
secondaries = _measure_declared_components(args, composition)
outcome, secondaries = aggregate_child_outcome(composition,
    MetricResult(metric_id="accuracy", direction="higher", scalar=1.0), secondaries)
_emit_outcome(args, outcome, secondaries=secondaries)
assert "ml_models.models_sandbox" not in sys.modules
assert not any(name.startswith("siderius_plugin_") for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(spec_path), argv[1], str(output)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(output.read_text())
    expected = (1.0 + max(0.0, 1.0 - results[0].value / 10.0)) / 2
    assert payload["denoising_score"] == pytest.approx(expected)

    # Reach an actual blocked forward, rather than timing out interpreter startup.
    marker.unlink()
    monkeypatch.setattr(candidate_measurement, "MEASUREMENT_LOAD_ALLOWANCE_SECONDS", 5.0)
    components = [
        MeasurementComponent.model_validate(
            latency_component(warmup=1, repeats=1, timeout_seconds=0.1)
        )
    ]
    lifecycles = []
    started = time.monotonic()
    with observe_process_lifecycle(lifecycles.append):
        failures = candidate_measurement.run_measurement_worker(
            request.model_copy(update={"model_configuration": {"hang": True}}),
            components,
            directory=str(tmp_path),
            **kwargs,
        )
    assert marker.exists(), "deadline must interrupt model forward, not startup"
    assert time.monotonic() - started < 20
    assert lifecycles[-1].child_reaped
    assert lifecycles[-1].group_cleanup.final.status == "absent"
    assert "deadline" in failures[0].failure
    # Failure evidence must be readable by scoring even when the worker wrote nothing.
    failed_argv = TidmadSandbox._measurement_results_argv(failures, str(tmp_path))
    assert (
        candidate_measurement.read_measurement_results(
            failed_argv[1], {"latency": "inference_latency_ms"}
        )
        == failures
    )


def test_worker_crash_and_rss_failure_become_typed_results(tmp_path):
    from core.subprocess_env import subprocess_env

    request = MeasurementRequest(
        model_type="unused",
        experiment_id="e",
        model_configuration={},
        loss_type="mse",
        checkpoint_path=str(tmp_path / "missing.pth"),
    )
    env = subprocess_env()
    # Failure before worker entry (invalid interpreter option) must also be typed.
    env["PYTHONHASHSEED"] = "invalid"
    results = candidate_measurement.run_measurement_worker(
        request,
        _count_components(),
        directory=str(tmp_path),
        env=env,
        preexec_fn=None,
        rss_limit_bytes=8 * 1024**3,
    )
    assert all("worker failed" in result.failure for result in results)
    results = candidate_measurement.run_measurement_worker(
        request,
        _count_components(),
        directory=str(tmp_path),
        env=subprocess_env(),
        preexec_fn=None,
        rss_limit_bytes=1,
    )
    assert all("host_rss_exceeded" in result.failure for result in results)


def test_no_measurements_skip_worker_and_keep_transport_empty(monkeypatch):
    from core.sandbox_executor import TidmadSandbox

    monkeypatch.setattr(candidate_measurement, "active_measurement_components", lambda: ())

    def forbidden(*args, **kwargs):
        pytest.fail("non-declaring task started a measurement worker")

    monkeypatch.setattr(candidate_measurement, "run_measurement_worker", forbidden)
    sandbox = object.__new__(TidmadSandbox)
    assert sandbox._run_candidate_measurements("e", "unused", {}, {}) is None
    assert sandbox._measurement_results_argv(None, "unused") == []


def test_executor_measurements_use_scoring_ceiling_and_attempt_device(monkeypatch, tmp_path):
    """Per-role mappings must not silently give measurement the inference cap."""
    from core.sandbox_executor import TidmadSandbox

    monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "training=8,inference=6,scoring=4")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-attempt-binding")
    monkeypatch.setattr(candidate_measurement, "active_measurement_components", _count_components)
    captured = {}

    def worker(request, components, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(candidate_measurement, "run_measurement_worker", worker)
    monkeypatch.setattr(TidmadSandbox, "_write_model_io_config", lambda *args: None)
    sandbox = object.__new__(TidmadSandbox)
    sandbox.dirs = {"models": str(tmp_path), "configs": str(tmp_path)}
    sandbox.plugin_dir = str(tmp_path / "plugins")
    sandbox.loss_dir = str(tmp_path / "losses")
    sandbox._run_candidate_measurements("e", "tiny", {}, {"loss_type": "smooth_l1"})
    assert captured["rss_limit_bytes"] == 4 * 1024**3
    assert captured["preexec_fn"] is not None
    assert captured["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-attempt-binding"
    assert captured["env"]["SIDERIUS_PLUGIN_DIRS"].split(":")[0] == sandbox.plugin_dir
