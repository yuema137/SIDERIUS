"""The example must certify only the requested attempt, even after a failed write."""

import pytest

from execute_tools.model_output_retention import apply_output_retention
from execute_tools.task_data_path import EvaluationReadRequest
from execute_tools.task_registration_scope import run_registration_scope
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

from .test_synthetic_masked_regression_pack import MANIFEST


@pytest.mark.parametrize("state", ["missing", "partial", "symlink"])
@pytest.mark.parametrize("retain", [True, False])
def test_inventory_preserves_other_attempts(tmp_path, state, retain):
    with run_registration_scope():
        composition = compose_run_task_bindings(str(MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
            task = composition.task_data_path
            request = EvaluationReadRequest(
                deliverable_dir=str(tmp_path), model_type="model", run_name="run", exp_id="current"
            )
            name = task.deliverable_name(model_type="model", run_name="run", exp_id="current")
            current = tmp_path / name
            other = tmp_path / task.deliverable_name(
                model_type="model", run_name="run", exp_id="other"
            )
            other.write_text("other attempt")
            if state == "partial":
                current.write_text('{"unfinished":')
            elif state == "symlink":
                current.symlink_to(tmp_path / "missing-target")
            inventory = task.enumerate_output_artifacts(request)
            assert inventory.relative_paths == (() if state == "missing" else (name,))
            assert (inventory.run_name, inventory.exp_id, inventory.model_type) == (
                "run",
                "current",
                "model",
            )
            receipt = apply_output_retention(
                task=task, request=request, retain_model_outputs=retain
            )
            assert receipt.status == ("refused" if state == "symlink" else "completed")
            assert other.read_text() == "other attempt"
            if state == "partial":
                assert current.exists() == retain
                assert receipt.artifacts[0].disposition == ("retained" if retain else "retired")
            elif state == "symlink":
                assert current.is_symlink()
