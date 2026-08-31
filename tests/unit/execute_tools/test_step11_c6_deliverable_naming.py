"""Generic coverage for task-declared deliverable naming."""

from __future__ import annotations

from pathlib import Path

import pytest

from execute_tools.deliverable_spec import (
    DeliverableNaming,
    active_deliverable_naming,
    bind_deliverable_naming,
    resolve_deliverable_naming,
)
from tests.helpers.composed_manifest import write_complete_manifest
from workflows.task_composition import (
    TaskCompositionError,
    compose_deliverable_naming_from_manifest,
)

DECLARED = DeliverableNaming(prefix="prediction", extension=".npz", index_width=3)


def _manifest(tmp_path: Path, declaration: object) -> Path:
    return write_complete_manifest(tmp_path, deliverable=declaration)


def test_declared_naming_controls_names_and_globs() -> None:
    with bind_deliverable_naming(DECLARED):
        naming = resolve_deliverable_naming()
        assert (
            naming.name(model_type="model", run_name="run", exp_id="exp", input_identity=7)
            == "prediction_model_run_exp_007.npz"
        )
        assert (
            naming.attempt_glob(model_type="model", run_name="run", exp_id="exp")
            == "prediction_model_run_exp_*.npz"
        )
    assert active_deliverable_naming() is None


def test_manifest_naming_composes_as_declared(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        {"prefix": "prediction", "extension": ".npz", "index_width": 3},
    )
    assert compose_deliverable_naming_from_manifest(str(manifest)) == DECLARED


@pytest.mark.parametrize(
    "declaration",
    [
        {"prefix": ""},
        {"extension": "npz"},
        {"index_width": 0},
        {"unknown": "value"},
    ],
)
def test_malformed_naming_is_refused(tmp_path: Path, declaration: object) -> None:
    manifest = _manifest(tmp_path, declaration)
    with pytest.raises(TaskCompositionError):
        compose_deliverable_naming_from_manifest(str(manifest))
