"""Original checkpoint cleanup is exact, durable, and independent of task code."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.sandbox_layout import training_checkpoint_path
from nodes.ml_hyperparameter_tune_agent.checkpoint_retention import (
    CheckpointRetentionError,
    CompletedTrainingAttempt,
    finalize_attempt_checkpoint,
    finalize_run_checkpoints,
)


def _finalize(
    workspace: Path,
    *,
    retain: bool = False,
    scored: bool = False,
):
    return finalize_attempt_checkpoint(
        workspace=str(workspace),
        models_dir=str(workspace / "cached_models"),
        run_name="run-a",
        exp_id="attempt-a",
        model_type="model-a",
        is_trial=True,
        retain_training_checkpoints=retain,
        scored=scored,
        certified_ref=None,
    )


def test_unscored_attempt_retires_only_its_original_with_durable_receipt(tmp_path: Path) -> None:
    models = tmp_path / "cached_models"
    models.mkdir()
    own = training_checkpoint_path(models, "model-a", "attempt-a")
    neighbor = training_checkpoint_path(models, "model-a", "attempt-b")
    own.write_bytes(b"failed inference model")
    neighbor.write_bytes(b"other model")

    receipt = _finalize(tmp_path)

    assert receipt.status == "retired"
    assert not own.exists()
    assert neighbor.read_bytes() == b"other model"
    statuses = [
        json.loads(line)["status"]
        for line in (tmp_path / "training_checkpoint_retention_receipts.jsonl")
        .read_text()
        .splitlines()
    ]
    assert statuses == ["retirement_planned", "retired"]


def test_scored_without_certification_keeps_original(tmp_path: Path) -> None:
    models = tmp_path / "cached_models"
    models.mkdir()
    source = training_checkpoint_path(models, "model-a", "attempt-a")
    source.write_bytes(b"scored but reflection failed")

    receipt = _finalize(tmp_path, scored=True)

    assert receipt.status == "retained"
    assert receipt.reason == "scored attempt has no certified model"
    assert source.is_file()


def test_explicit_retention_keeps_original(tmp_path: Path) -> None:
    models = tmp_path / "cached_models"
    models.mkdir()
    source = training_checkpoint_path(models, "model-a", "attempt-a")
    source.write_bytes(b"retain")

    assert _finalize(tmp_path, retain=True).status == "retained"
    assert source.read_bytes() == b"retain"


def test_symlink_checkpoint_refuses_without_touching_target(tmp_path: Path) -> None:
    models = tmp_path / "cached_models"
    models.mkdir()
    target = tmp_path / "other-checkpoint.pth"
    target.write_bytes(b"other")
    training_checkpoint_path(models, "model-a", "attempt-a").symlink_to(target)

    with pytest.raises(CheckpointRetentionError, match="non-symlink"):
        _finalize(tmp_path)

    assert target.read_bytes() == b"other"


def test_iteration_finalization_retires_failed_originals_after_records_are_written(
    tmp_path: Path,
) -> None:
    """A failed attempt remains inspectable until the completed run is persisted."""

    workspaces = [tmp_path / "iter_001", tmp_path / "iter_002"]
    attempts = []
    for workspace in workspaces:
        models = workspace / "cached_models"
        models.mkdir(parents=True)
        training_checkpoint_path(models, "model-a", "failed-a").write_bytes(b"partial")
        (workspace / "failure_record.json").write_text('{"status":"error_training"}')
        attempts.append(
            CompletedTrainingAttempt(
                workspace=str(workspace),
                run_name="run-a",
                exp_id="failed-a",
                model_type="model-a",
                is_trial=True,
                scored=False,
                certified_ref=None,
            )
        )

    assert all(
        training_checkpoint_path(
            Path(item.workspace) / "cached_models", item.model_type, item.exp_id
        ).is_file()
        for item in attempts
    )
    assert (
        finalize_run_checkpoints(
            [attempts[0]], retain_training_checkpoints=False, recorded_exp_ids={"failed-a"}
        )[0].status
        == "retired"
    )
    assert not training_checkpoint_path(
        Path(attempts[0].workspace) / "cached_models", attempts[0].model_type, attempts[0].exp_id
    ).exists()
    assert training_checkpoint_path(
        Path(attempts[1].workspace) / "cached_models", attempts[1].model_type, attempts[1].exp_id
    ).is_file()
    assert (workspaces[0] / "failure_record.json").read_text() == ('{"status":"error_training"}')


def test_missing_attempt_record_keeps_original_with_receipt(tmp_path: Path) -> None:
    models = tmp_path / "cached_models"
    models.mkdir()
    source = training_checkpoint_path(models, "model-a", "failed-a")
    source.write_bytes(b"partial")
    attempt = CompletedTrainingAttempt(
        workspace=str(tmp_path),
        run_name="run-a",
        exp_id="failed-a",
        model_type="model-a",
        is_trial=True,
        scored=False,
        certified_ref=None,
    )

    receipt = finalize_run_checkpoints(
        [attempt], retain_training_checkpoints=False, recorded_exp_ids=set()
    )[0]

    assert receipt.status == "retained"
    assert receipt.reason == "attempt record missing from run output"
    assert source.read_bytes() == b"partial"
