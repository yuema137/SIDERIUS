"""Composed attempts must prove coverage of the masked Health view before execution."""

import pytest

from execute_tools.task_data_path import ScopeBuildRequest, TaskHealthCoverageError
from execute_tools.task_registration_scope import run_registration_scope
from nodes.ml_hyperparameter_tune_agent.health_coverage import validate_attempt_health_coverage
from workflows.task_composition import compose_run_task_bindings

from .test_modular_masked_regression import isolated_task_registrations
from .test_synthetic_masked_regression_pack import MANIFEST, PACK


@pytest.mark.parametrize("manifest", [MANIFEST, PACK / "modular/composition.yaml"])
@pytest.mark.parametrize("round_kind", ["trial", "formal"])
def test_attempt_health_coverage(manifest, round_kind, isolated_task_registrations):
    """Missing capability rejects usable scopes; unconditional success accepts missing evidence.

    The existing variant-isolation fixture keeps inherited plain registrations
    from poisoning modular composition, then restores both registry maps.
    Both manifests must accept full and sampled evaluation scopes, including a
    pair of valid rows. A single valid row cannot meet the positive dispersion floor.
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

        two_valid = scope.model_copy(update={"rows": (scope.rows[1], scope.rows[2])})
        sampled = task.build_eval_scope(request.model_copy(update={"portion": 0.5}))
        for covered_scope in (scope, sampled, two_valid):
            for files in (None, (2,)):
                result = validate(covered_scope, files)
                assert result is not None and result.applicable and result.covered

        for rows in ((), (scope.rows[1],), tuple(row for row in scope.rows if not row.valid)):
            with pytest.raises(TaskHealthCoverageError, match="requires at least 2 valid rows"):
                validate(scope.model_copy(update={"rows": rows}))
        for selection in ({"portion": 0.08}, {"max_samples": 1}):
            with pytest.raises(TaskHealthCoverageError, match="requires at least 2 valid rows"):
                validate(task.build_eval_scope(request.model_copy(update=selection)))
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
