"""Setup failures cannot be repaired by paid generated-source changes."""

import pytest
import torch

from agent.schemas.custom_loss_validation import (
    CustomLossProbeSetupError,
    preflight_custom_loss_validation,
    validate_custom_loss_plugin,
    validate_custom_loss_plugin_or_raise_setup,
)


def test_preflight_preserves_cpu_rng_and_does_not_query_cuda(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Preflight must not initialize/query CUDA")

    monkeypatch.setattr(torch.cuda, "get_rng_state", forbidden)
    monkeypatch.setattr(torch.cuda, "device_count", forbidden)
    before = torch.random.get_rng_state().clone()
    preflight_custom_loss_validation()
    assert torch.equal(torch.random.get_rng_state(), before)


def test_public_string_api_and_internal_typed_setup_failure():
    def broken():
        raise ValueError("bad task pair")

    assert "bad task pair" in validate_custom_loss_plugin(
        "must not import", "loss", pair_provider=broken
    )
    with pytest.raises(CustomLossProbeSetupError, match="bad task pair"):
        validate_custom_loss_plugin_or_raise_setup("must not import", "loss", pair_provider=broken)


def test_per_attempt_probe_rng_and_provider_calls_remain_independent(monkeypatch):
    from agent.schemas import custom_loss_validation as module

    seen = []

    def provider():
        pair = torch.randn(2, 3), torch.randn(2, 3)
        seen.append(pair[0].clone())
        return pair

    monkeypatch.setattr(module, "_load_loss_factory", lambda *args: (None, "source repair needed"))
    with torch.random.fork_rng(devices=[]):
        initial = torch.random.get_rng_state().clone()
        preflight_custom_loss_validation(pair_provider=provider)
        assert torch.equal(initial, torch.random.get_rng_state())
        for _ in range(2):
            assert (
                validate_custom_loss_plugin_or_raise_setup("", "loss", pair_provider=provider)
                == "source repair needed"
            )
        assert len(seen) == 3 and torch.equal(seen[0], seen[1])
        assert not torch.equal(seen[1], seen[2])


def test_tensor_preparation_failure_is_setup_not_source_error():
    def integer_prediction():
        return torch.ones(2, dtype=torch.long), torch.zeros(2, dtype=torch.long)

    with pytest.raises(CustomLossProbeSetupError, match="tensors could not be prepared"):
        preflight_custom_loss_validation(pair_provider=integer_prediction)
