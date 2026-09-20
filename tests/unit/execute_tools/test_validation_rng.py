"""RNG wire round trips and pre-mutation validation of incoming state."""

import random

import numpy as np
import pytest
import torch

from execute_tools.validation_rng import (
    ValidationRngState,
    capture_validation_rng,
    restore_validation_rng,
)


@pytest.fixture(autouse=True)
def preserve_rng():
    original = capture_validation_rng()
    try:
        yield
    finally:
        restore_validation_rng(original)


def draw():
    return random.gauss(0, 1), float(np.random.normal()), torch.rand(3).tolist()


def test_json_handoff_preserves_cached_gaussians_and_exact_next_draws():
    random.seed(19)
    np.random.seed(23)
    torch.manual_seed(29)
    draw()  # Populate both cached Gaussian branches before serialization.
    saved = capture_validation_rng()
    expected = [draw() for _ in range(3)]
    restored = ValidationRngState.model_validate_json(saved.model_dump_json())
    assert restored == saved
    restore_validation_rng(restored)
    assert [draw() for _ in range(3)] == expected


def test_invalid_torch_state_does_not_partially_restore_python_or_numpy():
    saved = capture_validation_rng()
    draw()
    current = capture_validation_rng()
    invalid = ValidationRngState.model_validate(
        {**saved.model_dump(), "torch_cpu": b"not-a-generator-state"}
    )
    with pytest.raises(RuntimeError):
        restore_validation_rng(invalid)
    assert capture_validation_rng() == current


def test_duplicate_cuda_indices_refused_without_touching_cuda():
    saved = capture_validation_rng()
    with pytest.raises(ValueError, match="duplicate CUDA"):
        ValidationRngState.model_validate(
            {
                **saved.model_dump(),
                "torch_cuda": [{"device": 0, "state": b"x"}] * 2,
            }
        )
    assert capture_validation_rng() == saved


def test_unavailable_cuda_does_not_partially_restore_cpu_generators(monkeypatch):
    saved = capture_validation_rng()
    draw()
    current = capture_validation_rng()
    generator = torch.Generator

    def refuse_cuda(*, device):
        if str(device).startswith("cuda"):
            raise RuntimeError("requested CUDA device unavailable")
        return generator(device=device)

    monkeypatch.setattr(torch, "Generator", refuse_cuda)
    snapshot = ValidationRngState.model_validate(
        {**saved.model_dump(), "torch_cuda": [{"device": 0, "state": b"x"}]}
    )
    with pytest.raises(RuntimeError, match="CUDA device unavailable"):
        restore_validation_rng(snapshot)
    assert capture_validation_rng() == current


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA qualification needs a GPU")
def test_cuda_wire_roundtrip_restores_selected_device_exactly():
    saved = capture_validation_rng(cuda_devices=(0,))
    try:
        expected = torch.rand(4, device="cuda:0")
        restore_validation_rng(ValidationRngState.model_validate_json(saved.model_dump_json()))
        assert torch.equal(torch.rand(4, device="cuda:0"), expected)
    finally:
        restore_validation_rng(saved)
