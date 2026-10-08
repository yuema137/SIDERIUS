"""A measurement must load the exact native weights it claims, with bounded IO."""

import hashlib
import io
import os
import time
import weakref
from pathlib import Path

import pytest
import torch

from core.runtime_control.inference_checkpoint_reference import InferenceCheckpointReference
from core.sandbox_layout import training_checkpoint_path
from core.stream_identity import stream_file_identity
from execute_tools.inference_checkpoint import (
    load_bound_inference_checkpoint,
    load_inference_checkpoint,
)
from ml_models.target_standardization import StandardizedTargetModel


def checkpoint(tmp_path, state=None):
    path = training_checkpoint_path(tmp_path, "synthetic", "exp-a")
    if state is None:
        state = {"weight": torch.tensor([[2.0, 3.0]]), "bias": torch.tensor([4.0])}
    torch.save(state, path)
    (tmp_path / "_OK_exp-a").touch()
    payload = path.read_bytes()
    return InferenceCheckpointReference(
        checkpoint_path=str(path),
        experiment_id="exp-a",
        checkpoint_sha256=hashlib.sha256(payload).hexdigest(),
        checkpoint_byte_size=len(payload),
    )


def load(reference, **kwargs):
    return load_bound_inference_checkpoint(
        torch.nn.Linear(2, 1), reference, deadline_at=time.monotonic() + 10, **kwargs
    )


@pytest.mark.parametrize("standardized", [False, True])
def test_bound_loader_equals_production_and_restores_output_units(tmp_path, standardized):
    source = torch.nn.Linear(2, 1)
    with torch.no_grad():
        source.weight.fill_(2)
        source.bias.fill_(3)
    if standardized:
        source = StandardizedTargetModel(source, mean=7, scale=5)
    reference = checkpoint(tmp_path, source.state_dict())
    measured, receipt = load(reference)
    production = load_inference_checkpoint(
        torch.nn.Linear(2, 1), reference.checkpoint_path, "exp-a"
    )
    inputs = torch.tensor([[1.0, 2.0]])
    expected = torch.tensor([[52.0 if standardized else 9.0]])
    assert torch.equal(measured(inputs), expected)
    assert torch.equal(measured(inputs), production(inputs))
    assert receipt == reference
    assert isinstance(measured, StandardizedTargetModel) == standardized
    assert all(p.device.type == "cpu" for p in measured.parameters())


def test_cpu_load_uses_verified_open_handle_and_releases_host_state(tmp_path, monkeypatch):
    reference = checkpoint(tmp_path)
    original = torch.load
    observed = []
    tensors = []

    def spy(source, **kwargs):
        assert not isinstance(source, (str, Path))
        assert source.tell() == 0
        assert kwargs == {"map_location": "cpu"}
        observed.append(os.fstat(source.fileno()).st_ino)
        state = original(source, **kwargs)
        tensors.extend(weakref.ref(value) for value in state.values())
        return state

    monkeypatch.setattr(torch, "load", spy)
    model, _ = load(reference)
    assert observed == [Path(reference.checkpoint_path).stat().st_ino]
    assert all(ref() is None for ref in tensors)
    assert torch.equal(model(torch.ones(1, 2)), torch.tensor([[9.0]]))


@pytest.mark.parametrize(
    "fault", ["sentinel", "experiment", "hash", "size", "truncate", "edit", "symlink", "fifo"]
)
def test_bad_reference_never_reaches_deserialization(tmp_path, monkeypatch, fault):
    reference = checkpoint(tmp_path)
    path = Path(reference.checkpoint_path)
    if fault == "sentinel":
        (tmp_path / "_OK_exp-a").unlink()
    elif fault == "experiment":
        reference = reference.model_copy(update={"experiment_id": "exp-b"})
    elif fault == "hash":
        reference = reference.model_copy(update={"checkpoint_sha256": "0" * 64})
    elif fault == "size":
        reference = reference.model_copy(update={"checkpoint_byte_size": 1})
    elif fault == "truncate":
        path.write_bytes(b"short")
    elif fault == "edit":
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 1
        path.write_bytes(payload)
    elif fault == "symlink":
        moved = tmp_path / "moved.pth"
        path.rename(moved)
        path.symlink_to(moved)
    elif fault == "fifo":
        path.unlink()
        os.mkfifo(path)
    monkeypatch.setattr(torch, "load", lambda *a, **k: pytest.fail("unverified bytes loaded"))
    with pytest.raises((ValueError, RuntimeError, OSError)):
        load(reference)


@pytest.mark.parametrize("fault", ["missing_key", "wrong_shape", "standardization_marker"])
def test_strict_loading_is_preserved(tmp_path, fault):
    state = {"weight": torch.ones(1, 2), "bias": torch.ones(1)}
    if fault == "missing_key":
        del state["bias"]
    elif fault == "wrong_shape":
        state["weight"] = torch.ones(1, 3)
    else:
        state["_siderius_target_standardization_version"] = torch.tensor(99)
    reference = checkpoint(tmp_path, state)
    with pytest.raises((ValueError, RuntimeError)):
        load(reference)


@pytest.mark.parametrize("replace_path", [False, True])
def test_changes_during_load_never_produce_success_receipt(tmp_path, monkeypatch, replace_path):
    reference = checkpoint(tmp_path)
    original = torch.load

    def mutate(source, **kwargs):
        state = original(source, **kwargs)
        path = Path(reference.checkpoint_path)
        if replace_path:
            path.rename(tmp_path / "old.pth")
            path.write_bytes(b"replacement")
        else:
            with path.open("r+b") as writer:
                writer.seek(-1, os.SEEK_END)
                writer.write(b"X")
        return state

    monkeypatch.setattr(torch, "load", mutate)
    with pytest.raises(ValueError, match=r"changed|bytes differ"):
        load(reference)


@pytest.mark.parametrize("expire_at", [0, 3, 7])
def test_existing_deadline_bounds_open_stream_and_load(tmp_path, monkeypatch, expire_at):
    reference = checkpoint(tmp_path)
    calls = []

    def clock():
        calls.append(None)
        return 2 if len(calls) > expire_at else 0

    with pytest.raises(TimeoutError, match="measurement deadline"):
        load_bound_inference_checkpoint(
            torch.nn.Linear(2, 1), reference, deadline_at=1, clock=clock
        )


def test_streaming_identity_never_requests_a_full_buffer_and_stops_at_declared_size():
    class CheckedStream(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024
            return super().read(size)

    payload = b"x" * (2 * 1024 * 1024 + 3)
    assert stream_file_identity(CheckedStream(payload)) == (
        hashlib.sha256(payload).hexdigest(),
        len(payload),
    )
    stream = CheckedStream(payload)
    with pytest.raises(ValueError, match="declared byte size"):
        stream_file_identity(stream, byte_limit=7)
    assert stream.tell() == 8


@pytest.mark.parametrize("declared_size", [None, 3, 4])
def test_historical_stream_verifier_keeps_optional_size_and_error(tmp_path, declared_size):
    from agent.schemas.data_analysis.common import CertifiedArtifactRef
    from execute_tools.trained_model_artifact import verify_certified_artifact_file

    (tmp_path / "artifact.pt").write_bytes(b"abc")
    ref = CertifiedArtifactRef(
        logical_ref="artifact.pt",
        sha256=hashlib.sha256(b"abc").hexdigest(),
        media_type="application/octet-stream",
        byte_size=declared_size,
    )
    if declared_size == 4:
        with pytest.raises(
            ValueError, match="certified trained-model artifact file differs from its ref"
        ):
            verify_certified_artifact_file(tmp_path, ref)
    else:
        assert verify_certified_artifact_file(tmp_path, ref) == tmp_path / "artifact.pt"


@pytest.mark.parametrize(
    "field,value",
    [
        ("checkpoint_path", "relative.pth"),
        ("checkpoint_byte_size", True),
        ("checkpoint_byte_size", -1),
        ("checkpoint_sha256", "not-a-digest"),
    ],
)
def test_reference_rejects_ambiguous_boundary_values(tmp_path, field, value):
    from pydantic import ValidationError

    reference = checkpoint(tmp_path)
    with pytest.raises(ValidationError):
        InferenceCheckpointReference.model_validate({**reference.model_dump(), field: value})


@pytest.mark.parametrize("deadline", [float("inf"), float("nan")])
def test_checkpoint_verification_requires_a_finite_existing_budget(tmp_path, deadline):
    with pytest.raises(ValueError, match="finite deadline"):
        load_bound_inference_checkpoint(
            torch.nn.Linear(2, 1), checkpoint(tmp_path), deadline_at=deadline
        )
