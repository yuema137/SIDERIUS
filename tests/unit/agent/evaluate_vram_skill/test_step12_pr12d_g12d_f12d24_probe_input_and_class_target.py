"""Contract-aware VRAM probe input and classification target tests."""

import torch

from agent.schemas.model_io_contract import ModelIOContract
from agent.skills.evaluate_vram_skill.batch_resolver import _build_probe_input
from agent.skills.evaluate_vram_skill.wrapper import (
    _class_index_target_tensor,
    _probe_input_tensor,
)

BATCH = 4
SEGMENTATION = 128


def _contract(
    input_shape: list[int], output_shape: list[tuple[int, str | None]]
) -> ModelIOContract:
    def axis(fixed: int | None, role: str | None = None) -> dict:
        return {
            "dimension": {
                "dynamic": False,
                "fixed": fixed,
                "symbolic": "B" if fixed is None else None,
            },
            "role": role,
        }

    return ModelIOContract.model_validate(
        {
            "input": {
                "axes": [axis(None, "batch"), *(axis(size) for size in input_shape)],
                "dtype": {"admissible": ["float32"]},
            },
            "output": {
                "axes": [axis(None, "batch"), *(axis(size, role) for size, role in output_shape)],
                "dtype": {"admissible": ["float32"]},
            },
        }
    )


IMAGE_CLASSIFICATION = _contract([3, 32, 32], [(5, "class")])
VIDEO_REGRESSION = _contract([3, 4, 16, 24], [(3, None), (2, None), (16, None), (24, None)])


def test_legacy_probe_input_is_preserved_without_a_contract() -> None:
    tensor = _probe_input_tensor(BATCH, SEGMENTATION, None)
    assert tensor.shape == (BATCH, SEGMENTATION)
    assert tensor.dtype == torch.long


def test_probe_input_uses_declared_shape_and_dtype() -> None:
    image = _probe_input_tensor(BATCH, SEGMENTATION, IMAGE_CLASSIFICATION)
    video = _build_probe_input(BATCH, SEGMENTATION, VIDEO_REGRESSION)
    assert image.shape == (BATCH, 3, 32, 32)
    assert video.shape == (BATCH, 3, 4, 16, 24)
    assert image.dtype == video.dtype == torch.float32


def test_classification_target_drops_the_declared_class_axis() -> None:
    target = _class_index_target_tensor(BATCH, SEGMENTATION, IMAGE_CLASSIFICATION)
    assert target.shape == (BATCH,)
    assert target.dtype == torch.long
