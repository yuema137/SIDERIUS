"""Real CPU forwards expose state that call-count accounting misprices."""

import pytest
import torch
from torch import nn

from agent.skills.evaluate_vram_skill.batch_resolver import (
    BatchSearchRefused,
    resolve_inference_decision,
)
from agent.skills.evaluate_vram_skill.estimation_inputs import observe_phase
from agent.skills.evaluate_vram_skill.overhead import cuda_context_bytes
from agent.skills.evaluate_vram_skill.structural_probe import probe_activation_footprint
from core.preflight_estimation import estimate_phase


@pytest.mark.parametrize("declared_extent", [518_005, 760_150, 5_469_229])
def test_large_declared_shape_reaches_real_cpu_probe_without_universal_limit(declared_extent):
    """#689: metadata size alone must not veto a bounded supplied probe.

    A small real tensor keeps this offline test cheap. This proves routing and
    memory refusal, not feasibility of the corresponding full scientific graph.
    """
    model = RepeatedLayer(4, 1)
    kwargs = dict(
        segmentation_size=declared_extent,
        candidate_batches=(1,),
        supplied_probe=torch.zeros(1, 4),
    )
    decision = resolve_inference_decision(model, cap_bytes=2 * 1024**3, **kwargs)
    assert decision.batch_size == 1
    assert decision.intensity_product is None
    assert decision.intensity_limit is None
    assert decision.vram_estimate_bytes == 96 + cuda_context_bytes()
    with pytest.raises(BatchSearchRefused) as exc:
        resolve_inference_decision(model, cap_bytes=1, **kwargs)
    assert exc.value.decision.binding_caps == ("vram",)


def test_explicit_rule_refuses_large_declared_shape_before_cpu_probe(historical_workload_rule):
    """The historical route retains exactly the old shape rejection evidence."""
    with pytest.raises(BatchSearchRefused) as exc:
        resolve_inference_decision(
            RepeatedLayer(4, 1),
            segmentation_size=5_469_229,
            cap_bytes=2 * 1024**3,
            candidate_batches=(1,),
            supplied_probe=torch.zeros(1, 4),
        )
    assert exc.value.decision.binding_caps == ("compute_intensity",)
    assert exc.value.decision.intensity_product == 5_469_229
    assert exc.value.decision.intensity_limit == 800_000
    assert exc.value.decision.vram_estimate_bytes is None


class RepeatedLayer(nn.Module):
    def __init__(self, width, calls):
        super().__init__()
        self.layer = nn.Linear(width, width, bias=False)
        self.calls = calls
        self.register_buffer("unused_state", torch.zeros(width), persistent=False)

    def forward(self, value):
        for _ in range(self.calls):
            value = self.layer(value)
        return value


@pytest.mark.parametrize("width,calls", [(4, 1), (4, 8), (32, 8), (128, 2)])
@pytest.mark.parametrize("cap_offset,expected_batch", [(-1, 1), (0, 3), (1, 3)])
def test_real_reused_layer_search_respects_registered_state_and_cap_boundary(
    width, calls, cap_offset, expected_batch
):
    model = RepeatedLayer(width, calls)
    state_bytes = (width * width + width) * 4
    cap = state_bytes + calls * 3 * width * 4 + cuda_context_bytes() + cap_offset
    decision = resolve_inference_decision(
        model,
        segmentation_size=None,
        cap_bytes=cap,
        candidate_batches=(7, 3, 1),
        supplied_probe=torch.zeros(1, width),
    )
    assert decision.batch_size == expected_batch
    assert decision.vram_estimate_bytes == (
        state_bytes + calls * expected_batch * width * 4 + cuda_context_bytes()
    )
    assert decision.estimator == "inference_registered_state_v1"


def test_training_keeps_raw_optimizer_declaration_but_prices_production_optimizer():
    model = RepeatedLayer(4, 8)
    loss = nn.MSELoss()
    probe = probe_activation_footprint(
        model=model,
        loss_module=loss,
        input_sample=torch.zeros(3, 4),
        target_sample=torch.zeros(3, 4),
        mode="training",
    )
    raw = {"optimizer": "adam", "optimizer_type": "sgd"}
    observed = observe_phase(
        probe, model=model, loss_module=loss, batch_size=3, training_config=raw
    )
    assert observed.leaf_parameter_bytes > observed.model_state.parameter_bytes
    assert observed.training_config == raw
    assert observed.optimizer_type == "sgd"
    estimate = estimate_phase(observed)
    assert estimate.breakdown["param_bytes"] == 64
    assert estimate.breakdown["buffer_bytes"] == 16
    assert estimate.breakdown["training_overhead_bytes"] == 64
