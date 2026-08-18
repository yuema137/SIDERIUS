"""Pets reference CNN — the Track-B known-good executable baseline (D14-2 C4).

Roadmap §22.11a: "one simple reference plugin per contrast example
(known-good executable baseline, architecture chosen by the D14 design)".
Chosen architecture (child design §2.4): a small deterministic conv stack —
a baseline, NOT a candidate (no pretrained weights, no augmentation, no
hyperparameter search; parent §4.2 non-goals).

Loaded DYNAMICALLY through the plugin mechanism (`SIDERIUS_PLUGIN_DIRS`
naming this directory); production code never imports `examples.*`
(governance guard (c), absolute).

Forward boundary (the pack's declared `ModelIOContract`):
``[B, 3, 144, 144] float32 → [B, 37] float32`` logits.
"""

import torch
import torch.nn as nn
from pydantic import BaseModel, Field

PLUGIN_MODEL_TYPE = "pets_reference_cnn"


class PetsReferenceCnnConfig(BaseModel):
    model_type: str = Field(default="pets_reference_cnn", description="Plugin model type key.")
    #: Engine-residue compatibility field (child design §2.4): the streaming
    #: engine reads `model_cfg.segmentation_size` at run start; nothing on
    #: the Pets path consumes it.
    segmentation_size: int = Field(default=144, ge=1)
    batch_size: int = Field(default=32, ge=1)
    hidden_channels: int = Field(default=16, ge=4, le=128)


PLUGIN_CONFIG_CLASS = PetsReferenceCnnConfig


class PetsReferenceCnn(nn.Module):
    """Conv3x3(3→h)/ReLU/MaxPool → Conv3x3(h→2h)/ReLU/MaxPool →
    Conv3x3(2h→4h)/ReLU/AdaptiveAvgPool(4x4) → Linear(64h→37).

    At the default h=16: ~62 k parameters — sized for a bounded gate run.
    """

    def __init__(self, config: "PetsReferenceCnnConfig"):
        super().__init__()
        h = config.hidden_channels
        self.features = nn.Sequential(
            nn.Conv2d(3, h, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(h, 2 * h, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(2 * h, 4 * h, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.head = nn.Linear(4 * h * 4 * 4, 37)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # [B, 3, 144, 144] float32 → [B, 37] float32 logits.
        feats = self.features(x)
        return self.head(torch.flatten(feats, 1))


PLUGIN_MODEL_CLASS = PetsReferenceCnn
PLUGIN_OUTPUT_TYPE = "classifier"  # [B, 37] → 37-class classification
