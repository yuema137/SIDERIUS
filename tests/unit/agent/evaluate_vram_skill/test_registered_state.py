"""CPU witnesses for projected registered state rather than forward-call counts."""

from __future__ import annotations

import pytest
import torch
from torch import nn

from agent.skills.evaluate_vram_skill.registered_state import inventory_registered_state


def test_inventory_includes_parent_unused_frozen_and_nonpersistent_state():
    model = nn.Module()
    model.parent = nn.Parameter(torch.zeros(3))
    model.frozen = nn.Parameter(torch.zeros(5), requires_grad=False)
    model.unused = nn.Linear(2, 4, bias=False)
    model.register_buffer("ordinary", torch.zeros(7))
    model.register_buffer("temporary", torch.zeros(11), persistent=False)
    result = inventory_registered_state(model)
    assert result.status == "available"
    assert result.parameter_bytes == (3 + 5 + 8) * 4
    assert result.trainable_parameter_bytes == (3 + 8) * 4
    assert result.buffer_bytes == (7 + 11) * 4
    assert result.parameter_count == 3
    assert result.buffer_count == 2


def test_repeated_module_and_parameter_aliases_count_once():
    layer = nn.Linear(8, 8, bias=False)
    model = nn.Sequential(layer, layer, layer)
    model.register_parameter("also_weight", layer.weight)
    result = inventory_registered_state(model)
    assert result.parameter_bytes == 8 * 8 * 4
    assert result.parameter_count == 1
    distinct = inventory_registered_state(
        nn.Sequential(*(nn.Linear(8, 8, bias=False) for _ in range(3)))
    )
    assert distinct.parameter_bytes == 3 * 8 * 8 * 4


def test_distinct_parameters_sharing_storage_own_distinct_gradients():
    model = nn.Module()
    source = torch.zeros(6)
    model.first = nn.Parameter(source)
    model.second = nn.Parameter(source)
    assert model.first.untyped_storage().data_ptr() == model.second.untyped_storage().data_ptr()
    result = inventory_registered_state(model)
    assert result.parameter_bytes == 2 * 6 * 4
    assert result.trainable_parameter_bytes == 2 * 6 * 4
    (model.first.sum() + model.second.sum()).backward()
    assert model.first.grad is not None and model.second.grad is not None
    assert (
        model.first.grad.untyped_storage().data_ptr()
        != model.second.grad.untyped_storage().data_ptr()
    )
    # Allocating dtype conversion is a CPU witness for loss of host aliasing.
    model.to(dtype=torch.float64)
    assert model.first.untyped_storage().data_ptr() != model.second.untyped_storage().data_ptr()
    assert inventory_registered_state(model).parameter_bytes == 2 * 6 * 8


def test_buffer_slots_count_per_unique_module_and_separate_on_conversion():
    child = nn.Module()
    shared = torch.zeros(5)
    child.register_buffer("first", shared)
    child.register_buffer("second", shared, persistent=False)
    model = nn.ModuleList([child, child])
    before = inventory_registered_state(model)
    assert before.buffer_bytes == 2 * 5 * 4
    assert before.buffer_count == 2
    model.to(dtype=torch.float64)
    assert child.first.data_ptr() != child.second.data_ptr()
    assert inventory_registered_state(model).buffer_bytes == 2 * 5 * 8


def test_empty_and_zero_sized_registrations_are_available():
    model = nn.Module()
    model.register_parameter("absent", None)
    model.register_buffer("absent_buffer", None)
    model.zero = nn.Parameter(torch.empty(0))
    model.register_buffer("zero_buffer", torch.empty(0))
    state = inventory_registered_state(model)
    assert state.status == "available"
    assert state.parameter_bytes == state.buffer_bytes == state.trainable_parameter_bytes == 0
    assert state.parameter_count == state.buffer_count == 1


@pytest.mark.parametrize("kind", ["lazy", "meta", "sparse", "quantized"])
def test_unsupported_state_is_explicitly_unavailable_without_partial_totals(kind):
    model = nn.Module()
    model.valid = nn.Parameter(torch.ones(4))
    if kind == "lazy":
        model.child = nn.LazyLinear(4)
    elif kind == "meta":
        model.register_buffer("invalid", torch.empty(3, device="meta"))
    elif kind == "sparse":
        model.register_buffer("invalid", torch.eye(3).to_sparse())
    else:
        model.register_buffer(
            "invalid", torch.quantize_per_tensor(torch.ones(3), 0.1, 0, torch.qint8)
        )
    state = inventory_registered_state(model)
    assert state.status == "unavailable"
    assert state.reason
    assert state.parameter_bytes is None
    assert state.trainable_parameter_bytes is None
    assert state.buffer_bytes is None
    assert state.parameter_count is None
    assert state.buffer_count is None


@pytest.mark.parametrize("size", [1, 3, 31, 257])
def test_inventory_scales_with_state_size(size):
    model = nn.Module()
    model.weight = nn.Parameter(torch.empty(size, dtype=torch.float64))
    model.register_buffer("state", torch.empty(size, dtype=torch.int32))
    result = inventory_registered_state(model)
    assert result.parameter_bytes == result.trainable_parameter_bytes == size * 8
    assert result.buffer_bytes == size * 4
