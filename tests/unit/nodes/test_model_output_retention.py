"""The tuner retires only exact per-attempt outputs after their consumers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from execute_tools.task_data_path import EvaluationReadRequest, TaskOutputArtifactInventory
from nodes.ml_hyperparameter_tune_agent.output_retention import (
    OutputRetentionError,
    finalize_attempt_outputs,
)


class _TaskInventory:
    def enumerate_output_artifacts(
        self, request: EvaluationReadRequest
    ) -> TaskOutputArtifactInventory:
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
            relative_paths=("prediction.bin", "probabilities.bin"),
        )


class _LegacyNaming:
    def attempt_glob(self, *, model_type: str, run_name: str, exp_id: str) -> str:
        return f"output_{model_type}_{run_name}_{exp_id}_*.h5"


def _finalize(tmp_path: Path, task: object | None, *, retain: bool = False):
    return finalize_attempt_outputs(
        task_data_path=task,
        legacy_naming=None,
        deliverable_dir=str(tmp_path / "outputs"),
        workspace=str(tmp_path / "workspace"),
        run_name="run-a",
        exp_id="attempt-a",
        model_type="model-a",
        retain_model_outputs=retain,
    )


def test_task_declared_outputs_are_retired_but_checkpoint_and_other_attempt_survive(
    tmp_path: Path,
) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    for name in ("prediction.bin", "probabilities.bin", "checkpoint.pt", "other.bin"):
        (output / name).write_bytes(name.encode())

    receipt = _finalize(tmp_path, _TaskInventory())

    assert receipt.status == "completed"
    assert {item.relative_path for item in receipt.artifacts} == {
        "prediction.bin",
        "probabilities.bin",
    }
    assert {item.disposition for item in receipt.artifacts} == {"retired"}
    assert {path.name for path in output.iterdir()} == {"checkpoint.pt", "other.bin"}
    stored = json.loads(
        (tmp_path / "workspace" / "model_output_retention_receipts.jsonl").read_text()
    )
    assert stored["exp_id"] == "attempt-a"
    assert stored["status"] == "completed"


def test_explicit_retention_keeps_exact_task_outputs(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    for name in ("prediction.bin", "probabilities.bin"):
        (output / name).write_bytes(b"result")

    receipt = _finalize(tmp_path, _TaskInventory(), retain=True)

    assert {item.disposition for item in receipt.artifacts} == {"retained"}
    assert (output / "prediction.bin").exists()
    assert (output / "probabilities.bin").exists()


def test_missing_task_inventory_refuses_and_persists_receipt(tmp_path: Path) -> None:
    (tmp_path / "outputs").mkdir()

    with pytest.raises(OutputRetentionError, match="output_inventory_unavailable"):
        _finalize(tmp_path, object())

    receipt = json.loads(
        (tmp_path / "workspace" / "model_output_retention_receipts.jsonl").read_text()
    )
    assert receipt["status"] == "refused"


def test_receipt_persistence_failure_is_infrastructure_error(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    (output / "prediction.bin").write_bytes(b"prediction")
    (output / "probabilities.bin").write_bytes(b"probabilities")
    blocked_workspace = tmp_path / "not-a-directory"
    blocked_workspace.write_bytes(b"occupied")

    with pytest.raises(OutputRetentionError, match="receipt could not be persisted"):
        finalize_attempt_outputs(
            task_data_path=_TaskInventory(),
            legacy_naming=None,
            deliverable_dir=str(output),
            workspace=str(blocked_workspace),
            run_name="run-a",
            exp_id="attempt-a",
            model_type="model-a",
            retain_model_outputs=True,
        )


def test_legacy_compatibility_uses_attempt_not_experiment_glob(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    own = output / "output_model-a_run-a_attempt-a_001.h5"
    neighbor = output / "output_model-b_run-a_attempt-a_001.h5"
    own.write_bytes(b"own")
    neighbor.write_bytes(b"neighbor")

    receipt = finalize_attempt_outputs(
        task_data_path=None,
        legacy_naming=_LegacyNaming(),
        deliverable_dir=str(output),
        workspace=str(tmp_path / "workspace"),
        run_name="run-a",
        exp_id="attempt-a",
        model_type="model-a",
        retain_model_outputs=False,
    )

    assert receipt.status == "completed"
    assert not own.exists()
    assert neighbor.exists()


def test_legacy_glob_rejects_metacharacters_before_enumeration(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    neighbor = output / "output_model-b_run-a_attempt-a_001.h5"
    neighbor.write_bytes(b"neighbor")

    with pytest.raises(OutputRetentionError, match="invalid_output_inventory"):
        finalize_attempt_outputs(
            task_data_path=None,
            legacy_naming=_LegacyNaming(),
            deliverable_dir=str(output),
            workspace=str(tmp_path / "workspace"),
            run_name="run-a",
            exp_id="attempt-a",
            model_type="model*",
            retain_model_outputs=False,
        )

    assert neighbor.read_bytes() == b"neighbor"
