"""Explicit composition/data binding for CPU trainer subprocess witnesses."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from execute_tools.data_paths import bind_physical_data_root
from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.task_data_path import bind_task_data_path
from tests.helpers.composed_manifest import write_complete_manifest
from workflows.task_composition import (
    bind_task_manifest_path,
    compose_task_data_path_from_manifest,
)
from workflows.task_config import bind_task_config


@contextmanager
def bound_trainer_task(tmp_path: Path, fixture):
    """The same importable adapter reaches parent and real child via a manifest."""
    manifest = write_complete_manifest(
        tmp_path / "task",
        task_data_path={
            "file": str(Path(__file__).with_name("synthetic_training_data_path.py")),
            "symbol": "TwoFamilyDataPath",
            "id": "synthetic_two_family_training",
        },
        model_plugins=None,
    )
    adapter = compose_task_data_path_from_manifest(str(manifest))
    adapter.fixture = fixture
    with (
        bind_task_data_path(adapter),
        bind_task_manifest_path(str(manifest)),
        bind_physical_data_root(fixture.data_dir),
        bind_dataset_profile(fixture.profile),
        bind_task_config(
            {"task_description": "Synthetic trainer transport witness.", "forward_contract": {}}
        ),
    ):
        yield adapter


def attempt_scopes(adapter, training, evaluation=None):
    """Opaque executor carrier; identities and serialization belong to the adapter."""
    return SimpleNamespace(
        training=adapter.scope(training),
        evaluation=None if evaluation is None else adapter.scope(evaluation, family="validation"),
    )
