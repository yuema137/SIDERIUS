"""Original checkpoint cleanup is exact, durable, and independent of task code."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.sandbox_layout import training_checkpoint_path
from nodes.ml_hyperparameter_tune_agent.checkpoint_retention import (
    CheckpointRetentionError,
    finalize_attempt_checkpoint,
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
