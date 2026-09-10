"""Generic Health persistence witnesses formerly mixed with campaign defaults.

Retains the pre-08a persisted-status differential and typed multi-check
persistence, plus the 2026-08-26 rule that aggregation records what RAN,
not what configuration suggested. No scientific campaign config is loaded.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from execute_tools.health_checks import evaluation
from execute_tools.health_checks.config import HealthChecksConfig
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
)


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


def test_execution_status_preserves_the_pre_08a_differential():
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


def _persist(monkeypatch, checks, *, aggregation=None):
    """Inject only check outcomes; execute real typed persistence."""
    config = HealthChecksConfig.model_validate(
        {
            "health_gates": [
                {
                    "id": "synthetic_gate",
                    "gate_role": "blocking",
                    "after_round": "every",
                    "checks": [
                        {
                            "name": checks[0].check_name,
                            "config": {} if aggregation is None else {"aggregation": aggregation},
                        }
                    ],
                    "on_pass": {"action": "continue"},
                    "on_fail": {"action": "continue"},
                }
            ]
        }
    )
    result = GateResult(
        gate_id="synthetic_gate",
        round_index=1,
        passed=all(check.passed for check in checks),
        action=GateAction.CONTINUE,
        check_results=checks,
    )
    monkeypatch.setattr(evaluation, "evaluate_gate", lambda *args, **kwargs: result)
    monkeypatch.setattr(evaluation, "load_health_gates_config", lambda path=None: config)
    _, persisted, _ = evaluation.evaluate_and_persist_health_gates(
        HealthCheckContext(model_name="model", run_name="run", round_index=1),
        config_path="synthetic-policy.yaml",
    )
    return persisted[0]


def test_every_executed_check_verdict_survives_persistence(monkeypatch):
    checks = [
        HealthCheckResult(
            check_name=name,
            passed=passed,
            verdict=verdict,
            reason="fixture",
            metrics={"exception_type": "SyntheticError"} if verdict is CheckVerdict.ERROR else {},
        )
        for name, passed, verdict in [
            ("first", False, CheckVerdict.FAILED),
            ("second", True, CheckVerdict.INAPPLICABLE),
            ("third", False, CheckVerdict.ERROR),
            ("fourth", True, CheckVerdict.PASSED),
        ]
    ]
    persisted = _persist(monkeypatch, checks)
    assert persisted.check_verdicts == {
        "first": "failed",
        "second": "inapplicable",
        "third": "error",
        "fourth": "passed",
    }
    assert persisted.execution_status == "error"


def test_aggregation_uses_applied_rule_not_configured_rule(monkeypatch):
    check = HealthCheckResult(
        check_name="synthetic_check",
        passed=False,
        reason="fixture",
        metrics={
            "aggregation": "all_pass",
            "per_file": [
                {"file_index": 2, "metric_value": 9, "passed": True, "io_error": None},
                {"file_index": 5, "metric_value": 1, "passed": False, "io_error": None},
            ],
            "n_files_attempted": 2,
            "n_files_io_failed": 0,
        },
    )
    observation = _persist(monkeypatch, [check], aggregation="any_pass")
    assert observation.aggregation["aggregation_rule"] == "all_pass"
    assert observation.aggregation["files_passed"] == [2]
    assert observation.aggregation["files_failed"] == [5]


@pytest.mark.parametrize("configured", [None, "all_pass"])
def test_no_applied_aggregation_never_fabricates_a_rule(monkeypatch, configured):
    check = HealthCheckResult(check_name="synthetic_check", passed=True, reason="fixture")
    observation = _persist(monkeypatch, [check], aggregation=configured)
    assert "aggregation_rule" not in observation.aggregation
    assert observation.aggregation["aggregate_passed"] is True
