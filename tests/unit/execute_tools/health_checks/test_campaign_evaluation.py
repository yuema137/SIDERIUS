"""Campaign-specific regression tests for shared HealthGate persistence."""

from __future__ import annotations

from execute_tools.health_checks import evaluation, runner
from execute_tools.health_checks.config import load_health_gates_config
from execute_tools.health_checks.schemas import (
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
)

OBSERVE_CONFIG = "configs/health_checks_baseline_observe_mode.yaml"


def test_observe_yaml_runs_every_gate_every_round_and_always_continues():
    config = load_health_gates_config(OBSERVE_CONFIG)
    assert len(config.health_gates) == 6
    for round_index in range(1, 11):
        assert all(gate.matches_round(round_index) for gate in config.health_gates)
    assert all(
        gate.on_pass.action is GateAction.CONTINUE and gate.on_fail.action is GateAction.CONTINUE
        for gate in config.health_gates
    )


def test_alternate_config_path_is_forwarded(monkeypatch):
    seen: list[str | None] = []
    config = load_health_gates_config(OBSERVE_CONFIG)

    def fake_load(path=None):
        seen.append(path)
        return config

    monkeypatch.setattr(runner, "load_health_gates_config", fake_load)
    runner.get_gates_for_position(4, config_path=OBSERVE_CONFIG)
    assert seen == [OBSERVE_CONFIG]


def test_omitted_config_path_preserves_default_loader_call(monkeypatch):
    calls = 0
    config = load_health_gates_config(OBSERVE_CONFIG)

    def fake_load():
        nonlocal calls
        calls += 1
        return config

    monkeypatch.setattr(runner, "load_health_gates_config", fake_load)
    runner.get_gates_for_position(4)
    assert calls == 1


def test_failed_gate_persists_full_typed_observation(monkeypatch, tmp_path):
    output = tmp_path / "denoised.h5"
    output.write_bytes(b"output")
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"checkpoint")
    config = load_health_gates_config(OBSERVE_CONFIG)
    gate = config.health_gates[0]
    per_file = [
        {"file_index": index, "metric_value": value, "passed": passed, "io_error": None}
        for index, value, passed in ((3, 1, False), (10, 30, True), (17, 2, False))
    ]
    result = GateResult(
        gate_id=gate.id,
        round_index=1,
        passed=False,
        action=GateAction.CONTINUE,
        failure_reason="output_diversity: collapsed",
        check_results=[
            HealthCheckResult(
                check_name="output_diversity",
                passed=False,
                reason="output_diversity: collapsed",
                metrics={
                    "per_file": per_file,
                    "n_files_attempted": 3,
                    "n_files_io_failed": 0,
                    "peek_samples_requested": 100000,
                },
            )
        ],
    )
    monkeypatch.setattr(evaluation, "evaluate_gate", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        evaluation,
        "load_health_gates_config",
        lambda path=None: type(config)(health_gates=[gate]),
    )
    ctx = HealthCheckContext(
        model_name="wavenet",
        run_name="v17_pregate_baseline",
        round_index=1,
        checkpoint_path=str(checkpoint),
        denoised_filename_fn=lambda _index: str(output),
    )
    _, persisted, action = evaluation.evaluate_and_persist_health_gates(
        ctx,
        config_path=OBSERVE_CONFIG,
        production_config_path="configs/health_checks.yaml",
    )
    observation = persisted[0]
    assert action is GateAction.CONTINUE
    assert observation.execution_status == "failed"
    assert observation.resolved_action is GateAction.CONTINUE
    assert observation.threshold["value"] == 25
    assert set(observation.metrics["per_file"]) == {"3", "10", "17"}
    assert observation.aggregation["files_completed"] == [3, 10, 17]
    assert observation.metrics["aggregate_statistics"]["count"] == 3
