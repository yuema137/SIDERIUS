"""Regression: epoch-loss sampling must not shrink final inference/scoring.

Exercises task-owned selection and the production scope artifact ABI. A swapped
scope, lost seed, mismatched row declaration or overwritten artifact fails here.
"""

import json
import random
from pathlib import Path

import pytest

from execute_tools.scope_artifact import task_scope_argv, validation_rows_argv
from execute_tools.task_data_path import bind_task_data_path
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import acquire_attempt_scopes


class SampleTask:
    task_data_path_id = "snapshot_test"

    def build_training_scope(self, request):
        return ["training"]

    def build_eval_scope(self, request):
        assert request.selection_strategy == "snapshot"
        assert request.subset_ref == "4,5,6,7,8,9"
        return sorted(random.Random(request.seed).sample(range(100), round(100 * request.portion)))

    def serialize_scope(self, scope):
        return json.dumps(scope)

    def deserialize_scope(self, payload):
        return json.loads(payload)

    def validation_dataset(self, scope, params):
        return scope

    def training_dataset(self, scope, params):
        raise AssertionError("scope construction must not train")

    def write_deliverable(self, outputs, request):
        raise AssertionError("scope construction must not write predictions")

    def read_evaluation_payload(self, request):
        raise AssertionError("scope construction must not score")


def acquire(**overrides):
    from execute_tools.dataset_config import DataScope

    kwargs = dict(
        composed=True,
        mode="formal",
        trial_strategy="snapshot",
        trial_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=1.0,
        train_sampling_seed=11,
        eval_sampling_seed=22,
        target_files=None,
        subset=DataScope.from_cli("4-9"),
        validation_max_samples=None,
        task_parameters={},
        training_validation_portion=0.1,
    )
    return acquire_attempt_scopes(**(kwargs | overrides))


def _scope(argv):
    return Path(argv[argv.index("--task_eval_scope_ref") + 1])


@pytest.mark.parametrize("mode", ["trial", "formal"])
def test_snapshot_is_seeded_and_final_scope_remains_full(tmp_path, mode):
    with bind_task_data_path(SampleTask()):
        scopes = acquire(mode=mode)
        repeated = acquire(mode=mode)
        assert scopes.training_validation == repeated.training_validation
        assert len(scopes.training_validation) == 10
        assert scopes.training_validation != acquire(eval_sampling_seed=23).training_validation
        assert scopes.evaluation == list(range(100))
        training = task_scope_argv(str(tmp_path), "attempt", scopes, for_training=True)
        before = _scope(training).read_bytes()
        final = task_scope_argv(str(tmp_path), "attempt", scopes)
        assert _scope(training) != _scope(final)
        assert _scope(training).read_bytes() == before
        assert len(json.loads(_scope(training).read_bytes())) == 10
        assert len(json.loads(_scope(final).read_bytes())) == 100
        assert validation_rows_argv(scopes, str(tmp_path), regime_a_eval_declared=False) == [
            "--validation_requested_rows",
            "10",
        ]


def test_omission_preserves_old_artifact_and_full_loss_scope(tmp_path):
    with bind_task_data_path(SampleTask()):
        scopes = acquire(training_validation_portion=None)
        assert scopes.training_validation is None
        assert task_scope_argv(str(tmp_path), "a", scopes, for_training=True) == task_scope_argv(
            str(tmp_path), "a", scopes
        )
        assert validation_rows_argv(scopes, str(tmp_path), regime_a_eval_declared=False) == [
            "--validation_requested_rows",
            "100",
        ]


@pytest.mark.parametrize(
    "overrides", [{"composed": False}, {"mode": "single_file"}, {"eval_sampling_seed": None}]
)
def test_unsupported_override_refuses_instead_of_silent_full_validation(overrides):
    with bind_task_data_path(SampleTask()), pytest.raises(ValueError):
        acquire(**overrides)


def test_resume_cannot_change_epoch_validation_policy(tmp_path):
    """A restarted workspace must not silently combine incompatible loss histories."""
    from core.run_invariants import RunInvariants, RunInvariantsViolation, ensure_run_invariants

    original = RunInvariants(
        resolved_data_scope=[0],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="test",
        runtime_policy_identity="test",
    )
    ensure_run_invariants(str(tmp_path), original)
    assert ensure_run_invariants(str(tmp_path), original) == "validated"
    with pytest.raises(RunInvariantsViolation, match="training_validation_portion"):
        ensure_run_invariants(
            str(tmp_path), original.model_copy(update={"training_validation_portion": 0.1})
        )
