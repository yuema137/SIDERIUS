"""Tiny reference regressor for the synthetic masked-regression example."""

from __future__ import annotations

import torch
from pydantic import BaseModel, Field
from torch import nn

PLUGIN_MODEL_TYPE = "masked_reference_mlp"
PLUGIN_OUTPUT_TYPE = "regressor"


class MaskedReferenceMlpConfig(BaseModel):
    model_type: str = Field(default="masked_reference_mlp")
    segmentation_size: int = Field(default=3, ge=1)
    batch_size: int = Field(default=8, ge=1)
    hidden_dim: int = Field(default=8, ge=2, le=64)


class MaskedReferenceMlp(nn.Module):
    def __init__(self, config: MaskedReferenceMlpConfig) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(3, config.hidden_dim), nn.Tanh(), nn.Linear(config.hidden_dim, 1)
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.net(inputs)


PLUGIN_CONFIG_CLASS = MaskedReferenceMlpConfig
PLUGIN_MODEL_CLASS = MaskedReferenceMlp
