"""A path alias may reuse registered code, but cannot weaken conflict checks."""

import shutil
from pathlib import Path

import pytest
import yaml

from execute_tools.task_data_path import registered_content_identity
from execute_tools.task_registration_scope import run_registration_scope
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings


@pytest.mark.parametrize("conflict", ["different_path", "different_content"])
def test_path_alias_reuses_registered_object_without_accepting_conflicts(
    tmp_path: Path, conflict: str
) -> None:
    """Alias refusal fails at the second load; overbroad admission fails at the third."""
    fixture = Path(__file__).resolve().parents[3] / "tests/fixtures/step10_p1/fourth_task"
    package = tmp_path / "task"
    shutil.copytree(fixture, package)
    manifest = package / "composition.yaml"
    declaration = yaml.safe_load(manifest.read_text())
    plugin = package / declaration["task_data_path"]["file"]

    with run_registration_scope():
        first = compose_run_task_bindings(str(manifest))
        pinned = registered_content_identity(first.task_data_path_id)
        declaration["task_data_path"]["file"] = str(plugin)
        alias_manifest = package / "absolute.yaml"
        alias_manifest.write_text(yaml.safe_dump(declaration))
        second = compose_run_task_bindings(str(alias_manifest))
        assert second.task_data_path is first.task_data_path
        assert registered_content_identity(first.task_data_path_id) == pinned

        if conflict == "different_path":
            other = package / "other.py"
            other.write_bytes(plugin.read_bytes())
            declaration["task_data_path"]["file"] = str(other)
        else:
            plugin.write_bytes(plugin.read_bytes() + b"\n# Changed after registration.\n")
        conflicting_manifest = package / "conflicting.yaml"
        conflicting_manifest.write_text(yaml.safe_dump(declaration))
        with pytest.raises(TaskCompositionError, match="registered with different content"):
            compose_run_task_bindings(str(conflicting_manifest))
        assert registered_content_identity(first.task_data_path_id) == pinned
