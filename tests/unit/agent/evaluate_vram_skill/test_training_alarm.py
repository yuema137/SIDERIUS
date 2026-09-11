"""Reachability regression for the production native training alarm."""

import time
from contextlib import nullcontext
from datetime import UTC, datetime

import pytest
import torch
from torch import nn

from agent.skills.evaluate_vram_skill import wrapper
from agent.skills.evaluate_vram_skill.probe_budgets import ProbeBudgets
from core.hardware_context import HardwareContext


class _SlowModel(nn.Module):
    def forward(self, x):
        time.sleep(4.0)
        return x


def _eligible_context() -> HardwareContext:
    """Synthetic eligible context exercises the wrapper's alarm branch."""
    return HardwareContext(
        device_name="synthetic-test-device",
        total_memory_bytes=8 * 1024**3,
        compute_capability=(9, 0),
        multiprocessor_count=1,
        torch_version=torch.__version__,
        hostname="synthetic-test-host",
        device_available=True,
        discovered_at=datetime.now(UTC),
    )


def test_native_training_alarm_is_reachable_through_wrapper(monkeypatch):
    """The actual wrapper must interrupt slow training at its native budget."""
    entered = False

    def probe(**kwargs):
        nonlocal entered
        entered = True
        time.sleep(4.0)
        raise AssertionError("native alarm was bypassed")

    monkeypatch.setattr(wrapper, "_build_model", lambda *args, **kwargs: _SlowModel())
    monkeypatch.setattr(wrapper, "get_criterion", lambda *args, **kwargs: nn.MSELoss())
    monkeypatch.setattr(wrapper, "probe_activation_footprint", probe)
    monkeypatch.setattr(
        wrapper,
        "_build_probe_tensors",
        lambda *args, **kwargs: (torch.zeros(1, 1), torch.zeros(1, 1)),
    )

    started = time.monotonic()
    result = wrapper.run_skill(
        None,
        model_type="synthetic",
        model_config={},
        train_config={"batch_size": 1},
        loss_config={"loss_type": "smooth_l1"},
        hardware_context=_eligible_context(),
        probe_budgets=ProbeBudgets(single_probe_seconds=1.0),
    )
    elapsed = time.monotonic() - started

    assert entered
    assert result["status"] == "timeout"
    assert result["timeout_record"]["operation"] == "training_probe"
    assert result["timeout_record"]["budget_seconds"] == 1.0
    assert elapsed < 3.5


def test_native_alarm_negative_control_fails_when_bypassed(monkeypatch):
    """A bypassed production seam must make the slow-probe witness fail."""
    monkeypatch.setattr(wrapper, "_build_model", lambda *args, **kwargs: _SlowModel())
    monkeypatch.setattr(wrapper, "get_criterion", lambda *args, **kwargs: nn.MSELoss())
    def bypassed_probe(**kwargs):
        raise AssertionError("alarm bypassed")

    monkeypatch.setattr(wrapper, "probe_activation_footprint", bypassed_probe)
    monkeypatch.setattr(
        wrapper,
        "_build_probe_tensors",
        lambda *args, **kwargs: (torch.zeros(1, 1), torch.zeros(1, 1)),
    )
    monkeypatch.setattr(wrapper, "_forward_pass_timeout", lambda *args, **kwargs: nullcontext())

    result = wrapper.run_skill(
            None,
            model_type="synthetic",
            model_config={},
            train_config={"batch_size": 1},
            loss_config={"loss_type": "smooth_l1"},
            hardware_context=_eligible_context(),
            probe_budgets=ProbeBudgets(single_probe_seconds=1.0),
        )
    assert result["status"] == "error"
    assert "alarm bypassed" in result["message"]
