"""K.9 pseudo-mode test plugin — invented model_type for K.2.5-8 fallback regression.

Loaded only by tests/integration/workflows/test_k9_invented_model_dual_mode.py
(via SIDERIUS_PLUGIN_DIRS=tests/pseudo_data/plugins). NOT used in production.

Purpose: register a model_type that is NOT in
core/inference_defaults._INFERENCE_BATCH_SIZES, so every gate call exercises
the K.2.5-8 soft-fallback path (runtime fallback batch=25 + uncalibrated flag).

Architecture: a trivial nn.Linear stack with `hidden_dim` as the size lever.
Round 1 uses a large hidden_dim (~9.4M params) and busts a tight VRAM budget;
round 2 uses a small hidden_dim (~98k params) and fits. The model is never
trained for real in pseudo mode — RecordingSandbox returns a canned result
instead — so correctness is required only for the plugin contract
(forward shape [B, T] int -> [B, 256, T] float) and Pydantic validation.
"""

import torch
import torch.nn as nn
from pydantic import BaseModel, Field

PLUGIN_MODEL_TYPE = "pe_wavenet_delta"


class PeWavenetDeltaConfig(BaseModel):
    model_type: str = Field(default="pe_wavenet_delta")
    segmentation_size: int = Field(default=1000, ge=1)
    batch_size: int = Field(default=1, ge=1)
    hidden_dim: int = Field(default=128, ge=8, le=8192)


PLUGIN_CONFIG_CLASS = PeWavenetDeltaConfig


class PeWavenetDelta(nn.Module):
    def __init__(self, config: PeWavenetDeltaConfig):
        super().__init__()
        self.embedding = nn.Embedding(256, config.hidden_dim)
        self.l1 = nn.Linear(config.hidden_dim, config.hidden_dim)
        self.l2 = nn.Linear(config.hidden_dim, config.hidden_dim)
        self.head = nn.Linear(config.hidden_dim, 256)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.embedding(x.long())
        x = torch.relu(self.l1(x))
        x = torch.relu(self.l2(x))
        return self.head(x).transpose(1, 2).float()


PLUGIN_MODEL_CLASS = PeWavenetDelta
PLUGIN_OUTPUT_TYPE = "classifier"
