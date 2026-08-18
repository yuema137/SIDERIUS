"""DAVIS reference predictor — the Track-C known-good baseline (D14-3 C6).

Roadmap §22.11a: "one simple reference plugin per contrast example
(known-good executable baseline, architecture chosen by the D14 design)".
Chosen architecture (child design §2.6): a small Conv3d stack over the
context whose output is a RESIDUAL added to the last context frame,
broadcast over the 4 future steps. The last-frame baseline is what makes an
untrained net produce near-copy predictions and therefore a meaningful,
finite MSE at gate budget — a baseline, NOT a candidate (no pretrained
weights, no augmentation, no search).

Loaded DYNAMICALLY through the plugin mechanism; production never imports
`examples.*`.

Forward boundary (the pack's declared `ModelIOContract`):
``[B, 3, 8, 128, 224] float32 → [B, 3, 4, 128, 224] float32``.
"""

import torch
import torch.nn as nn
from pydantic import BaseModel, Field

PLUGIN_MODEL_TYPE = "davis_reference_predictor"

CONTEXT_FRAMES = 8
FUTURE_FRAMES = 4


class DavisReferencePredictorConfig(BaseModel):
    model_type: str = Field(default="davis_reference_predictor")
    #: Engine-residue compatibility field (child design §2.6): the streaming
    #: engine reads `model_cfg.segmentation_size`; nothing on this path uses it.
    segmentation_size: int = Field(default=128, ge=1)
    batch_size: int = Field(default=4, ge=1)
    hidden_channels: int = Field(default=16, ge=4, le=64)


PLUGIN_CONFIG_CLASS = DavisReferencePredictorConfig


class DavisReferencePredictor(nn.Module):
    """Residual-over-last-frame future predictor.

    ``Conv3d(3→h)/ReLU → Conv3d(h→h)/ReLU → Conv3d(h→3·4)`` over the context,
    mean-pooled across the context time axis to yield a per-future-frame
    residual field, ADDED to the last context frame.
    """

    def __init__(self, config: "DavisReferencePredictorConfig"):
        super().__init__()
        h = config.hidden_channels
        self.body = nn.Sequential(
            nn.Conv3d(3, h, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv3d(h, h, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv3d(h, 3 * FUTURE_FRAMES, kernel_size=3, padding=1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, 3, 8, H, W] -> features [B, 12, 8, H, W] -> pool over context
        # time -> [B, 12, H, W] -> reshape to [B, 3, 4, H, W] residual.
        batch, _channels, _t, height, width = x.shape
        features = self.body(x).mean(dim=2)
        residual = features.reshape(batch, 3, FUTURE_FRAMES, height, width)
        last_frame = x[:, :, -1:, :, :]  # [B, 3, 1, H, W]
        return last_frame + residual


PLUGIN_MODEL_CLASS = DavisReferencePredictor
PLUGIN_OUTPUT_TYPE = "regressor"  # dense continuous future frames
