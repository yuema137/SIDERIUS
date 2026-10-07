"""CPU arithmetic and optimizer witnesses for the native preflight provider."""

from __future__ import annotations

import pytest
import torch
from pydantic import ValidationError
from torch import nn

from agent.skills.evaluate_vram_skill.native_estimation import estimate_native_phase
from agent.skills.evaluate_vram_skill.overhead import (
    cuda_context_bytes,
    cudnn_backward_workspace_bytes,
)
from agent.skills.evaluate_vram_skill.registered_state import inventory_registered_state
from core.preflight_observations import PhaseEstimate, PhaseObservations, RegisteredStateInventory
from execute_tools.train_engine_sandbox import build_training_optimizer
from ml_models.models_format_sandbox import TrainConfig


def _observations(**changes) -> PhaseObservations:
    values = {
        "phase": "training",
        "batch_size": 2,
        "leaf_parameter_bytes": 9999,
        "leaf_output_bytes_sum": 120,
        "leaf_output_bytes_max": 40,
        "input_bytes": 20,
        "output_bytes": 30,
        "saved_tensor_bytes": 80,
        "model_state": RegisteredStateInventory(
            status="available",
            parameter_bytes=100,
            trainable_parameter_bytes=60,
            buffer_bytes=12,
            parameter_count=2,
            buffer_count=1,
        ),
        "loss_state": RegisteredStateInventory(
            status="available",
            parameter_bytes=16,
            trainable_parameter_bytes=8,
            buffer_bytes=4,
            parameter_count=2,
            buffer_count=1,
        ),
        "optimizer_type": "sgd",
        "training_config": {"optimizer": "adam"},
    }
    values.update(changes)
    return PhaseObservations.model_validate(values)


def test_native_uses_effective_optimizer_and_prices_loss_without_optimizer_moments():
    result = estimate_native_phase(_observations())
    assert result.breakdown["param_bytes"] == 100
    assert result.breakdown["training_overhead_bytes"] == 60
    assert result.breakdown["loss_gradient_bytes"] == 8
    expected = 100 + 12 + 16 + 4 + 80 + 20 + 30 + 60 + 8
    expected += cuda_context_bytes() + cudnn_backward_workspace_bytes()
    assert result.admission_bytes == result.diagnostic_bytes == expected
    assert result.estimator == "training_registered_state_v1"


def test_inference_keeps_distinct_admission_and_diagnostic_activation_proxies():
    observations = _observations(
        phase="inference", saved_tensor_bytes=None, loss_state=None, optimizer_type=None
    )
    result = estimate_native_phase(observations)
    assert result.admission_bytes == 100 + 12 + 120 + cuda_context_bytes()
    assert result.diagnostic_bytes == 100 + 12 + 20 + 40 + cuda_context_bytes()
    assert "training_overhead_bytes" not in result.breakdown


@pytest.mark.parametrize("optimizer_name,moments", [("sgd", 0), ("adam", 2), ("adamw", 2)])
def test_gradient_and_moment_pricing_matches_cpu_optimizer_tensor_allocations(
    optimizer_name, moments
):
    model = nn.Module()
    storage = torch.ones(4)
    model.first = nn.Parameter(storage)
    model.second = nn.Parameter(storage)
    model.frozen = nn.Parameter(torch.ones(3), requires_grad=False)
    optimizer = build_training_optimizer(model, TrainConfig(optimizer_type=optimizer_name, lr=0.01))
    (model.first.square().sum() + model.second.square().sum()).backward()
    optimizer.step()
    state = inventory_registered_state(model)
    result = estimate_native_phase(_observations(model_state=state, optimizer_type=optimizer_name))
    gradients = sum(
        p.grad.numel() * p.grad.element_size() for p in model.parameters() if p.grad is not None
    )
    moment_bytes = sum(
        value.numel() * value.element_size()
        for parameter_state in optimizer.state.values()
        for key, value in parameter_state.items()
        if key in {"exp_avg", "exp_avg_sq"}
    )
    assert gradients == 2 * 4 * 4
    assert moment_bytes == moments * gradients
    assert result.breakdown["training_overhead_bytes"] == gradients + moment_bytes


@pytest.mark.parametrize("owner", ["model_state", "loss_state"])
def test_native_rejects_unavailable_state_with_owner_reason(owner):
    observations = _observations(
        **{owner: RegisteredStateInventory(status="unavailable", reason="meta tensor")}
    )
    with pytest.raises(ValueError, match="registered state: meta tensor"):
        estimate_native_phase(observations)


@pytest.mark.parametrize("field", ["input_bytes", "leaf_parameter_bytes", "saved_tensor_bytes"])
@pytest.mark.parametrize("value", [-1, True, 3.5, "4"])
def test_observations_reject_nonbyte_values(field, value):
    with pytest.raises(ValidationError):
        _observations(**{field: value})


@pytest.mark.parametrize("field", ["saved_tensor_bytes", "loss_state", "optimizer_type"])
def test_training_requires_its_phase_observations(field):
    with pytest.raises(ValidationError, match="Training observations require"):
        _observations(**{field: None})


def test_estimate_requires_consistent_breakdown_and_no_execution_commands():
    with pytest.raises(ValidationError, match="Diagnostic breakdown"):
        PhaseEstimate(
            phase="inference",
            admission_bytes=3,
            diagnostic_bytes=4,
            estimator="test",
            breakdown={"a": 3},
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        PhaseEstimate.model_validate(
            {
                "phase": "inference",
                "admission_bytes": 3,
                "diagnostic_bytes": 3,
                "estimator": "test",
                "breakdown": {"a": 3},
                "accepted": True,
            }
        )


def test_unavailable_inventory_cannot_masquerade_as_zero_or_partial_evidence():
    with pytest.raises(ValidationError):
        RegisteredStateInventory(status="unavailable", reason="missing", parameter_bytes=0)
    with pytest.raises(ValidationError):
        RegisteredStateInventory(status="available")
