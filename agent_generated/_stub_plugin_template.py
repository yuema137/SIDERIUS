# agent_generated/_stub_plugin_template.py
#
# Hardcoded plugin source consumed by StubLLMBridge's `implementor.code`
# label. The bridge returns this file's contents verbatim regardless of
# the proposer's intent — the goal is schema-valid, GPU-friendly bytecode
# that passes ml_models/plugin_loader.py's contract on every iter.
#
# The leading underscore is load-bearing: ml_models/plugin_loader.py's
# directory scan skips files starting with "_". So even if a copy of this
# file ends up in agent_generated/models/, it stays dormant — production
# chains never accidentally instantiate the stub model.

import torch
import torch.nn as nn
from pydantic import BaseModel, Field


PLUGIN_MODEL_TYPE = "stub_arch"


class StubArchConfig(BaseModel):
    """Minimal config for the stub plugin — one tunable hidden_dim."""

    model_type: str = Field(default="stub_arch", description="Plugin model type key.")
    segmentation_size: int = Field(default=40000, ge=1)
    batch_size: int = Field(default=1, ge=1)
    hidden_dim: int = Field(default=8, ge=1, le=256)


PLUGIN_CONFIG_CLASS = StubArchConfig


class StubArch(nn.Module):
    """Tiny denoiser: nn.Embedding(256, h) → nn.Linear(h, 256)."""

    def __init__(self, config: StubArchConfig):
        super().__init__()
        self.embedding = nn.Embedding(256, config.hidden_dim)
        self.head = nn.Linear(config.hidden_dim, 256)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # forward contract: input [B, T] int → output [B, 256, T] float
        x = self.embedding(x.long())   # [B, T, hidden_dim]
        x = self.head(x)               # [B, T, 256]
        return x.transpose(1, 2)       # [B, 256, T]


PLUGIN_MODEL_CLASS = StubArch
PLUGIN_OUTPUT_TYPE = "classifier"
