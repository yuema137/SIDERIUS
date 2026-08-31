# Synthetic loss-plugin template used by framework contract tests.
#
# Hardcoded loss-plugin source used by the L1 unit tests to verify
# ``_loss_loader.py`` can load a valid loss plugin.
#
# The leading underscore is load-bearing: ``agent_generated/_loss_loader.py``'s
# directory scan skips files starting with ``_``. So even if a copy of this
# file ends up in ``agent_generated/losses/``, it stays dormant — production
# chains never accidentally instantiate the stub loss.
#
# Forward contract (mirrors the L1 spec in
# ``docs/design/enable_loss_inventory.md`` § Loss plugin interface):
#   inputs:  torch.Tensor [B, num_classes, T] float32  (model logits)
#   targets: torch.Tensor [B, T]              int64    (ground-truth class indices)
#   returns: torch.Tensor scalar                       (requires_grad=True)

import torch
import torch.nn as nn
import torch.nn.functional as F
from pydantic import BaseModel, Field

PLUGIN_LOSS_TYPE = "stub_ce"

# I13 — declares the dtype this loss expects for ``targets`` at training
# time. ``"long"`` (int64) is the classifier contract; ``"float"`` is the
# regressor contract. Consumers (evaluate_time_skill, train_engine_sandbox)
# read this via ``ml_models.loss_plugin_loader.get_loss_target_dtype`` and
# cast targets accordingly. Defaults to ``"long"`` when missing so existing
# pre-I13 plugins keep working. See docs/design/enable_loss_inventory.md § I13.
PLUGIN_LOSS_TARGET_DTYPE = "long"


class StubCEConfig(BaseModel):
    """Minimal config for the stub loss — one tunable smoothing parameter."""

    label_smoothing: float = Field(default=0.0, ge=0.0, le=0.5)


PLUGIN_LOSS_CONFIG_CLASS = StubCEConfig


class StubCE(nn.Module):
    """Tiny cross-entropy loss with optional label smoothing.

    Computes ``F.cross_entropy(inputs, targets, label_smoothing=cfg.label_smoothing)``.
    Carries gradient through ``inputs`` for backward verification in the
    L1 ``test_loss_loader`` dummy-tensor test.
    """

    def __init__(self, config: StubCEConfig):
        super().__init__()
        self.label_smoothing = config.label_smoothing

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        # inputs: [B, num_classes, T] → cross_entropy expects [B, C, *]
        # targets: [B, T] int64 — class indices directly accepted
        return F.cross_entropy(inputs, targets, label_smoothing=self.label_smoothing)


PLUGIN_LOSS_CLASS = StubCE
