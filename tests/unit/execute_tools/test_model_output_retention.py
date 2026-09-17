"""Output retirement must consume task-owned exact identities, never glob."""

from pathlib import Path

from execute_tools.model_output_retention import apply_output_retention
from execute_tools.task_data_path import EvaluationReadRequest, TaskOutputArtifactInventory


class InventoryTask:
    def __init__(self, paths: tuple[str, ...], *, exp_id: str = "attempt-1") -> None:
        self.paths = paths
        self.exp_id = exp_id

    def enumerate_output_artifacts(
        self, request: EvaluationReadRequest
    ) -> TaskOutputArtifactInventory:
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=self.exp_id,
            model_type=request.model_type,
            relative_paths=self.paths,
        )


def _request(root: Path) -> EvaluationReadRequest:
    return EvaluationReadRequest(
        deliverable_dir=str(root),
        exp_id="attempt-1",
        run_name="run",
        model_type="model",
    )


def test_default_retires_exact_outputs_but_preserves_neighbor_and_model(tmp_path: Path) -> None:
    output = tmp_path / "predictions-attempt-1.csv"
    sidecar = tmp_path / "sidecars" / "probabilities-attempt-1.npz"
    sidecar.parent.mkdir()
    output.write_bytes(b"prediction")
    sidecar.write_bytes(b"sidecar")
    neighbor = tmp_path / "predictions-attempt-2.csv"
    neighbor.write_bytes(b"other attempt")
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"model remains")

    receipt = apply_output_retention(
        task=InventoryTask((output.name, "sidecars/probabilities-attempt-1.npz")),
        request=_request(tmp_path),
        retain_model_outputs=False,
    )

    assert receipt.status == "completed"
    assert [item.disposition for item in receipt.artifacts] == ["retired", "retired"]
    assert [item.byte_size for item in receipt.artifacts] == [10, 7]
    assert not output.exists() and not sidecar.exists()
    assert neighbor.read_bytes() == b"other attempt"
    assert checkpoint.read_bytes() == b"model remains"


def test_explicit_retention_certifies_and_keeps_exact_outputs(tmp_path: Path) -> None:
    output = tmp_path / "prediction.npy"
    output.write_bytes(b"prediction")

    receipt = apply_output_retention(
        task=InventoryTask((output.name,)),
        request=_request(tmp_path),
        retain_model_outputs=True,
    )

    assert receipt.status == "completed"
    assert receipt.artifacts[0].disposition == "retained"
    assert receipt.artifacts[0].sha256 == (
        "70ad7b8f9a1c6c89a3cc93717b738ce9cf78395501b51d3707fc53cd63bb49d7"
    )
    assert output.read_bytes() == b"prediction"


def test_foreign_attempt_claim_refuses_before_deletion(tmp_path: Path) -> None:
    output = tmp_path / "prediction.csv"
    output.write_bytes(b"keep")

    receipt = apply_output_retention(
        task=InventoryTask((output.name,), exp_id="attempt-2"),
        request=_request(tmp_path),
        retain_model_outputs=False,
    )

    assert receipt.status == "refused"
    assert receipt.failure_code == "invalid_output_inventory"
    assert output.read_bytes() == b"keep"


def test_path_traversal_or_symlink_refuses_without_partial_deletion(tmp_path: Path) -> None:
    valid = tmp_path / "valid.csv"
    valid.write_bytes(b"keep")
    outside = tmp_path.parent / "outside.csv"
    outside.write_bytes(b"outside")
    (tmp_path / "link.csv").symlink_to(outside)

    for claimed in ("../outside.csv", "link.csv"):
        receipt = apply_output_retention(
            task=InventoryTask((valid.name, claimed)),
            request=_request(tmp_path),
            retain_model_outputs=False,
        )
        assert receipt.status == "refused"
        assert receipt.failure_code == "invalid_output_inventory"
        assert valid.read_bytes() == b"keep"
    assert outside.read_bytes() == b"outside"


def test_missing_inventory_refuses_instead_of_silently_retaining(tmp_path: Path) -> None:
    receipt = apply_output_retention(
        task=None,
        request=_request(tmp_path),
        retain_model_outputs=False,
    )
    assert receipt.status == "refused"
    assert receipt.failure_code == "output_inventory_unavailable"
