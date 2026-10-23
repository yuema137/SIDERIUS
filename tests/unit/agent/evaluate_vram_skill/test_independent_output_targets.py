"""Synthetic capacity probes must not invent independent target dimensions."""

import pytest
import torch

from agent.schemas.model_io_contract import ModelIOContract
from agent.skills.evaluate_vram_skill.wrapper import (
    _class_index_target_tensor,
    _contract_target_shape,
)
from agent.skills.model_io_probe_skill import ProbeConstructionError
from tests.helpers.step04a_fixtures import tidmad_model_io


def _output_count_contract(count):
    value = tidmad_model_io().model_dump(mode="json")
    value["output"]["axes"][-1] = {
        "dimension": {"symbolic": count} if isinstance(count, str) else {"fixed": count},
    }
    return ModelIOContract.model_validate(value)


@pytest.mark.parametrize("batch,size", [(1, 17), (2, 100), (4, 4096)])
def test_independent_target_size_is_not_replaced_with_segmentation(batch, size):
    declaration = _output_count_contract("K")
    with pytest.raises(ProbeConstructionError, match="task-owned target samples"):
        _contract_target_shape(declaration, "classifier", batch_size=batch, seg_size=size)
    with pytest.raises(ProbeConstructionError, match="task-owned target samples"):
        _class_index_target_tensor(batch, size, declaration)


@pytest.mark.parametrize("batch,size", [(1, 17), (2, 100), (4, 4096)])
def test_shared_and_fixed_targets_remain_concrete(batch, size):
    shared = tidmad_model_io()
    fixed = _output_count_contract(7)
    assert _contract_target_shape(shared, "classifier", batch_size=batch, seg_size=size) == (
        batch,
        256,
        size,
    )
    assert _contract_target_shape(fixed, "classifier", batch_size=batch, seg_size=size) == (
        batch,
        256,
        7,
    )
    shared_target = _class_index_target_tensor(batch, size, shared)
    fixed_target = _class_index_target_tensor(batch, size, fixed)
    assert shared_target.shape == (batch, size)
    assert fixed_target.shape == (batch, 7)
    assert shared_target.dtype == fixed_target.dtype == torch.int64
    assert shared_target.count_nonzero() == fixed_target.count_nonzero() == 0
