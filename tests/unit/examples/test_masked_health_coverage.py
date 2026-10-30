"""Composed attempts must prove coverage of the masked Health view before execution."""

import pytest

from execute_tools.task_data_path import ScopeBuildRequest, TaskHealthCoverageError
from execute_tools.task_registration_scope import run_registration_scope
from nodes.ml_hyperparameter_tune_agent.health_coverage import validate_attempt_health_coverage
from workflows.task_composition import compose_run_task_bindings

from .test_synthetic_masked_regression_pack import MANIFEST, PACK


@pytest.mark.parametrize("manifest", [MANIFEST, PACK / "modular/composition.yaml"])
@pytest.mark.parametrize("round_kind", ["trial", "formal"])
def test_attempt_health_coverage(manifest, round_kind):
    """Missing capability rejects usable scopes; unconditional success accepts missing evidence.

    Both manifests must accept full and sampled evaluation scopes, including a
    single valid row (coverage does not promise a passing dispersion verdict).
    Training rows, empty/masked-only views and unsupported partition demand
    must fail closed through the same production boundary.
    """
    with run_registration_scope():
        composition = compose_run_task_bindings(str(manifest))
        task = composition.task_data_path
        request = ScopeBuildRequest(
            round_kind=round_kind, selection_strategy="snapshot", portion=1.0, seed=17
        )
        scope = task.build_eval_scope(request)

        def validate(evaluation_scope, files=None):
            return validate_attempt_health_coverage(
                data_path=task,
                evaluation_scope=evaluation_scope,
                round_kind=round_kind,
                health_binding=composition.task_health_binding,
                health_gate_files=files,
                composed=True,
                health_enabled=True,
            )

        single_valid = scope.model_copy(update={"rows": (scope.rows[1],)})
        sampled = task.build_eval_scope(request.model_copy(update={"portion": 0.5}))
        for covered_scope in (scope, sampled, single_valid):
            for files in (None, (2,)):
                result = validate(covered_scope, files)
                assert result is not None and result.applicable and result.covered

        for rows in ((), tuple(row for row in scope.rows if not row.valid)):
            with pytest.raises(TaskHealthCoverageError, match="no valid predictions"):
                validate(scope.model_copy(update={"rows": rows}))
        training = task.build_training_scope(request)
        for uncovered_scope in (
            training,
            scope.model_copy(update={"rows": (*scope.rows, training.rows[1])}),
        ):
            with pytest.raises(TaskHealthCoverageError, match="evaluation shard 2 only"):
                validate(uncovered_scope)
        for files in ((), (0,), (0, 2)):
            with pytest.raises(TaskHealthCoverageError, match="health_gate_files"):
                validate(scope, files)
