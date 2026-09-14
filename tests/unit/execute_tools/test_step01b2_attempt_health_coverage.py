"""01B2 — task-owned Health coverage is typed, opaque and fail-closed."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.task_data_path import (
    HealthCoverageResult,
    TaskHealthCoverageError,
)
from nodes.ml_hyperparameter_tune_agent.health_coverage import (
    validate_attempt_health_coverage,
)


class _OpaqueScope:
    """A scope whose contents must never be inspected by infra."""

    def __getattribute__(self, name: str):  # pragma: no cover - any access is a defect
        raise AssertionError(f"framework inspected opaque scope attribute {name!r}")

    def __getitem__(self, key):  # pragma: no cover - any access is a defect
        raise AssertionError(f"framework inspected opaque scope key {key!r}")


class _DataPath:
    task_data_path_id = "coverage-test-task"

    def training_dataset(self, scope, params):  # pragma: no cover
        raise AssertionError("coverage must run before dataset construction")

    def validation_dataset(self, scope, params):  # pragma: no cover
        raise AssertionError("coverage must run before dataset construction")

    def write_deliverable(self, outputs, request):  # pragma: no cover
        raise AssertionError("not part of coverage")

    def read_evaluation_payload(self, request):  # pragma: no cover
        raise AssertionError("not part of coverage")

    def validate_health_coverage(self, request):
        assert request.round_kind == "formal"
        assert request.health_binding == "task-health.yaml"
        return HealthCoverageResult(
            applicable=True,
            covered=True,
            reason="the task evaluation scope covers its Health demand",
        )


class _NotApplicable(_DataPath):
    def validate_health_coverage(self, request):
        return {"applicable": False, "covered": False, "reason": "no output-dependent demand"}


class _Uncovered(_DataPath):
    def validate_health_coverage(self, request):
        return {"applicable": True, "covered": False, "reason": "scope omits required outputs"}


class _Missing(_DataPath):
    validate_health_coverage = None


class _Malformed(_DataPath):
    def validate_health_coverage(self, request):
        return {"applicable": "yes", "covered": True, "reason": "not a typed result"}


class _Exploding(_DataPath):
    def validate_health_coverage(self, request):
        raise RuntimeError("task coverage backend unavailable")


class _TransportDataPath(_DataPath):
    """A tiny task with the canonical scope transport capability."""

    def build_training_scope(self, request):
        return {"partition": "train", "ids": [1, 2]}

    def build_eval_scope(self, request):
        return {"partition": "eval", "ids": [7, 8]}

    def serialize_scope(self, scope):
        return json.dumps(scope, sort_keys=True)

    def deserialize_scope(self, payload):
        return json.loads(payload)

    def validate_health_coverage(self, request):
        assert request.evaluation_scope == {"partition": "eval", "ids": [7, 8]}
        return {"applicable": True, "covered": True, "reason": "round-trip scope is covered"}


class _GateFilesDataPath(_DataPath):
    def validate_health_coverage(self, request):
        assert request.health_gate_files == (4, 7, 9)
        return {
            "applicable": True,
            "covered": True,
            "reason": "resolved monitored files are covered",
        }


def test_covered_opaque_scope_passes_without_framework_inspection():
    result = validate_attempt_health_coverage(
        data_path=_DataPath(),
        evaluation_scope=_OpaqueScope(),
        round_kind="formal",
        health_binding="task-health.yaml",
        composed=True,
        health_enabled=True,
    )
    assert result.applicable is True
    assert result.covered is True


def test_explicit_non_applicable_result_is_valid():
    result = validate_attempt_health_coverage(
        data_path=_NotApplicable(),
        evaluation_scope=object(),
        round_kind="trial",
        health_binding="none",
        composed=True,
        health_enabled=True,
    )
    assert result.applicable is False
    assert result.covered is False


def test_run_resolved_health_gate_files_reach_task_coverage_unchanged():
    """Task coverage sees the run override, not a YAML/default value."""
    result = validate_attempt_health_coverage(
        data_path=_GateFilesDataPath(),
        evaluation_scope=object(),
        round_kind="formal",
        health_binding="task-health.yaml",
        health_gate_files=[4, 7, 9],
        composed=True,
        health_enabled=True,
    )
    assert result is not None and result.covered is True


def test_health_gate_files_absence_is_transported_as_none():
    class NoOverride(_DataPath):
        def validate_health_coverage(self, request):
            assert request.health_gate_files is None
            return {"applicable": False, "covered": False, "reason": "no override"}

    result = validate_attempt_health_coverage(
        data_path=NoOverride(),
        evaluation_scope=object(),
        round_kind="trial",
        health_binding="task-health.yaml",
        composed=True,
        health_enabled=True,
    )
    assert result is not None and result.applicable is False


def test_uncovered_scope_refuses_before_execution():
    with pytest.raises(TaskHealthCoverageError, match="uncovered Health demand"):
        validate_attempt_health_coverage(
            data_path=_Uncovered(),
            evaluation_scope=object(),
            round_kind="trial",
            health_binding="task-health.yaml",
            composed=True,
            health_enabled=True,
        )


def test_missing_capability_refuses_by_task_identity():
    with pytest.raises(TaskHealthCoverageError, match="coverage-test-task"):
        validate_attempt_health_coverage(
            data_path=_Missing(),
            evaluation_scope=object(),
            round_kind="formal",
            health_binding="task-health.yaml",
            composed=True,
            health_enabled=True,
        )


def test_explicit_health_absence_passes_without_resolving_capability():
    """Named absence is a valid declaration, not a missing capability."""
    result = validate_attempt_health_coverage(
        data_path=_Missing(),
        evaluation_scope=object(),
        round_kind="formal",
        health_binding=HealthBindingState.EXPLICIT_NONE,
        composed=True,
        health_enabled=True,
    )
    assert result == HealthCoverageResult(
        applicable=False,
        covered=False,
        reason="task explicitly declares no Health coverage demand",
    )


def test_malformed_result_refuses_closed():
    with pytest.raises(TaskHealthCoverageError, match="malformed Health coverage"):
        validate_attempt_health_coverage(
            data_path=_Malformed(),
            evaluation_scope=object(),
            round_kind="formal",
            health_binding="task-health.yaml",
            composed=True,
            health_enabled=True,
        )


def test_provider_exception_refuses_closed_with_task_identity():
    with pytest.raises(TaskHealthCoverageError, match="coverage-test-task"):
        validate_attempt_health_coverage(
            data_path=_Exploding(),
            evaluation_scope=object(),
            round_kind="formal",
            health_binding="task-health.yaml",
            composed=True,
            health_enabled=True,
        )


def test_contradictory_result_is_not_a_valid_carrier():
    with pytest.raises(ValidationError, match="cannot be covered"):
        HealthCoverageResult(
            applicable=False,
            covered=True,
            reason="contradictory",
        )


def test_exact_eval_scope_stays_coverage_equivalent_through_canonical_transport(tmp_path):
    """Coverage must validate the scope sent to the child, not a second scope."""
    from execute_tools.scope_artifact import load_transported_scope, write_scope_artifact
    from execute_tools.task_data_path import bind_task_data_path

    task = _TransportDataPath()
    original = task.build_eval_scope(None)
    payload = task.serialize_scope(original)
    artifact = Path(tmp_path) / "task_eval_scope.json"
    digest = write_scope_artifact(str(artifact), payload)
    with bind_task_data_path(task):
        transported = load_transported_scope(str(artifact), digest, leg="evaluation")
        result = validate_attempt_health_coverage(
            data_path=task,
            evaluation_scope=transported,
            round_kind="formal",
            health_binding="task-health.yaml",
            composed=True,
            health_enabled=True,
        )
    assert task.serialize_scope(transported) == payload
    assert result is not None and result.covered is True


def test_prepare_attempt_reachability_guard_keeps_coverage_before_persistence():
    """Removing the production helper call must fail this structural witness."""
    source = inspect.getsource(
        __import__(
            "nodes.ml_hyperparameter_tune_agent.planning", fromlist=["prepare_attempt"]
        ).prepare_attempt
    )
    assert source.count("validate_attempt_health_coverage(") == 1


def test_prepare_attempt_refuses_uncovered_scope_before_any_execution_effect(tmp_path):
    """The named refusal precedes config persistence and all execution effects."""
    from nodes.ml_hyperparameter_tune_agent.contracts import AttemptOrdering
    from nodes.ml_hyperparameter_tune_agent.planning import prepare_attempt
    from tests.unit.nodes.ml_hyperparameter_tune_agent.test_c12p_b11_composed_seg_size_authoring import (
        _bindings,
        _composed_input,
    )

    class UncoveredTask(_DataPath):
        def __init__(self):
            self.calls = []

        def build_training_scope(self, request):
            self.calls.append("build_training_scope")
            return {"leg": "training"}

        def build_eval_scope(self, request):
            self.calls.append("build_eval_scope")
            return {"leg": "evaluation"}

        def serialize_scope(self, scope):
            return json.dumps(scope, sort_keys=True)

        def deserialize_scope(self, payload):
            return json.loads(payload)

        def validate_health_coverage(self, request):
            self.calls.append("validate_health_coverage")
            assert request.health_gate_files == (4, 7, 9)
            return {
                "applicable": True,
                "covered": False,
                "reason": "the evaluation scope omits Health outputs",
            }

        def training_dataset(self, scope, params):  # pragma: no cover
            self.calls.append("training_dataset")
            raise AssertionError("training dataset was constructed before coverage")

        def validation_dataset(self, scope, params):  # pragma: no cover
            self.calls.append("validation_dataset")
            raise AssertionError("validation dataset was constructed before coverage")

    task = UncoveredTask()
    agent_input = _composed_input().model_copy(update={"health_gate_files": [4, 7, 9]})
    bindings = _bindings(agent_input, tmp_path, task)
    from execute_tools.task_data_path import bind_task_data_path

    with bind_task_data_path(task):
        with pytest.raises(TaskHealthCoverageError, match="uncovered Health demand"):
            prepare_attempt(
                bindings,
                attempt_ordering=AttemptOrdering(),
                iteration=1,
                attempt_in_round=1,
                total_attempts=1,
                attempts_this_round=1,
                is_formal_round=False,
                formal_trial_winner=None,
            )
    assert task.calls == ["build_training_scope", "build_eval_scope", "validate_health_coverage"]
    assert list(Path(tmp_path).iterdir()) == []


@pytest.mark.parametrize(
    ("composed", "health_enabled", "round_kind"),
    [(False, True, "formal"), (True, False, "formal"), (True, True, "single_file")],
)
def test_non_qualifying_paths_do_not_resolve_optional_capability(
    composed: bool, health_enabled: bool, round_kind: str
):
    assert (
        validate_attempt_health_coverage(
            data_path=None,  # type: ignore[arg-type]
            evaluation_scope=object(),
            round_kind=round_kind,
            health_binding=None,
            composed=composed,
            health_enabled=health_enabled,
        )
        is None
    )
