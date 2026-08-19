"""Campaign-specific regression tests for shared HealthGate persistence."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from execute_tools.health_checks import evaluation, runner
from execute_tools.health_checks.config import load_health_gates_config
from execute_tools.health_checks.schemas import (
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
    PersistedHealthGateResult,
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


# ---------------------------------------------------------------------------
# Step 08a C3 — _execution_status is derived from typed verdicts, not prose
# ---------------------------------------------------------------------------


def _pre_08a_execution_status(passed: bool, reason: str, metrics: dict[str, object]) -> str:
    """The PRE-08a rule, transcribed as test-owned DATA.

    Quoted from ``evaluation.py::_execution_status`` as it stood at
    ``a37fd15d``::

        if any("exception_type" in check.metrics for check in result.check_results):
            return "error"
        attempted = metrics.get("n_files_attempted")
        io_failed = metrics.get("n_files_io_failed")
        reasons = " ".join(check.reason for check in result.check_results).lower()
        if (attempted and io_failed == attempted) or "not applicable" in reasons:
            return "not_run"
        return "passed" if result.passed else "failed"

    Transcribed rather than imported because the original no longer exists:
    the point of the differential is that the NEW derivation reproduces the
    OLD outputs, and importing the new code to generate the expectation
    would compare it against itself.
    """
    if "exception_type" in metrics:
        return "error"
    attempted = metrics.get("n_files_attempted")
    io_failed = metrics.get("n_files_io_failed")
    if (attempted and io_failed == attempted) or "not applicable" in reason.lower():
        return "not_run"
    return "passed" if passed else "failed"


def _manifest_cases() -> list[dict]:
    path = Path(__file__).resolve().parent / "goldens" / "verdict_parity_manifest_pre08a.json"
    return json.loads(path.read_text())["cases"]


def test_execution_status_is_byte_identical_to_the_pre_08a_rule():
    """Differential over the frozen C1 corpus — 27 real check outcomes.

    The defect this owns: the string sniff carried real semantics, and
    replacing it with a typed rule could silently change a persisted status
    for an input class nobody thought about. Every captured case must map to
    the same string it mapped to before.
    """
    divergences: list[str] = []
    for case in _manifest_cases():
        metrics = dict(case["metrics"])
        result = GateResult(
            gate_id="g",
            round_index=1,
            passed=case["passed"],
            action=GateAction.CONTINUE,
            check_results=[
                HealthCheckResult(
                    check_name=case["check_name"],
                    passed=case["passed"],
                    reason=case["reason"],
                    metrics=metrics,
                )
            ],
        )
        expected = _pre_08a_execution_status(case["passed"], case["reason"], metrics)
        actual = evaluation._execution_status(result, metrics)
        if actual != expected:
            divergences.append(f"{case['case_id']}: {expected} -> {actual}")
    assert not divergences, "execution_status changed for:\n  " + "\n  ".join(divergences)


def test_the_differential_corpus_covers_every_status():
    """Guards the guard: a corpus that only produced 'passed' would prove nothing."""
    statuses = {
        _pre_08a_execution_status(case["passed"], case["reason"], case["metrics"])
        for case in _manifest_cases()
    }
    assert statuses == {"passed", "failed", "not_run"}


def test_evaluation_module_no_longer_sniffs_reason_prose():
    """The string sniff is gone, not merely bypassed.

    A leftover branch would be a second, prose-driven authority that only
    disagrees with the typed one once a check is reworded.
    """
    tree = ast.parse(Path(evaluation.__file__).read_text())
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_execution_status"
    )
    # The docstring explains the removal and legitimately quotes the old
    # branch, so compare against the EXECUTABLE body only.
    statements = func.body[1:] if ast.get_docstring(func) else func.body
    code = "\n".join(ast.unparse(node) for node in statements)
    assert "not applicable" not in code
    assert ".reason" not in code


def test_check_verdicts_are_persisted_for_every_check_that_ran(monkeypatch):
    """The additive field carries the honest four-way statement."""
    config = load_health_gates_config(OBSERVE_CONFIG)
    gate = config.health_gates[0]
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
                metrics={"n_files_attempted": 3, "n_files_io_failed": 0},
            ),
            HealthCheckResult(
                check_name="amplitude_collapse",
                passed=True,
                reason="amplitude_collapse: not applicable — no files in context",
            ),
        ],
    )
    monkeypatch.setattr(evaluation, "evaluate_gate", lambda *a, **k: result)
    monkeypatch.setattr(
        evaluation, "load_health_gates_config", lambda path=None: type(config)(health_gates=[gate])
    )
    ctx = HealthCheckContext(model_name="m", run_name="r", round_index=1)

    _, persisted, _ = evaluation.evaluate_and_persist_health_gates(ctx, config_path=OBSERVE_CONFIG)

    assert persisted[0].check_verdicts == {
        "output_diversity": "failed",
        "amplitude_collapse": "inapplicable",
    }
    # The gate's own status is unchanged by the additive field.
    assert persisted[0].execution_status == "failed"


def test_legacy_persisted_record_without_verdicts_still_validates():
    """Records written before 08a must load unchanged — absence is not a verdict."""
    legacy = PersistedHealthGateResult(
        gate_name="output_diversity_blocking",
        execution_status="passed",
        check_passed=True,
        would_invalidate_under_production_policy=False,
        resolved_action=GateAction.CONTINUE,
    )
    assert legacy.check_verdicts is None
    assert "check_verdicts" in legacy.model_dump()
