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
        assert naming.unqualified_name(model_type="model", input_identity=7) == (
            "prediction_model_007.npz"
        )
        assert naming.experiment_glob(exp_id="exp") == "prediction_*_exp_*.npz"
        assert naming.any_glob() == "prediction_*.npz"
    assert active_deliverable_naming() is None


def test_inverse_parsing_follows_the_declared_prefix_suffix_and_width() -> None:
    """Preserve the Step05c inverse-name witness without a scientific default."""
    for index in (0, 7, 19, 999):
        qualified = DECLARED.name(
            model_type="model", run_name="run", exp_id="exp", input_identity=index
        )
        unqualified = DECLARED.unqualified_name(model_type="model", input_identity=index)
        assert DECLARED.input_identity_of(qualified) == index
        assert DECLARED.input_identity_of(unqualified) == index
    for foreign in (
        "other_model_run_exp_007.npz",
        "prediction_model_run_exp_007.csv",
        "prediction_model_run_exp_07.npz",
    ):
        assert DECLARED.input_identity_of(foreign) is None
    renamed = DeliverableNaming(prefix="answer", extension=".csv", index_width=2)
    assert renamed.name(model_type="m", run_name="r", exp_id="e", input_identity=7) == (
        "answer_m_r_e_07.csv"
    )
    assert renamed.unqualified_name(model_type="m", input_identity=7) == "answer_m_07.csv"
    assert renamed.attempt_glob(model_type="m", run_name="r", exp_id="e") == "answer_m_r_e_*.csv"
    assert renamed.experiment_glob(exp_id="e") == "answer_*_e_*.csv"
    assert renamed.any_glob() == "answer_*.csv"
    assert renamed.input_identity_of("answer_m_r_e_07.csv") == 7
    assert renamed.input_identity_of("prediction_model_run_exp_007.npz") is None


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
        {"prefix": "   "},
        {"prefix": " prediction "},
        {"prefix": "prediction_*"},
        {"prefix": "prediction_?"},
        {"extension": "npz"},
        {"index_width": 0},
        {"unknown": "value"},
    ],
)
def test_malformed_naming_is_refused(tmp_path: Path, declaration: object) -> None:
    manifest = _manifest(tmp_path, declaration)
    with pytest.raises(TaskCompositionError):
        compose_deliverable_naming_from_manifest(str(manifest))
