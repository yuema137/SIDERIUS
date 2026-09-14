"""Masked mean-squared-error objective for the synthetic regression example."""

from __future__ import annotations

import torch
from pydantic import BaseModel, ConfigDict
from torch import nn

PLUGIN_LOSS_TYPE = "synthetic_masked_mse"
PLUGIN_CAPABILITY_CONTRACT = {
    "contract_kind": "custom_loss_applicability",
    "contract_version": 1,
    "canonical_payload": '{"applicability":{"mode":"explicit_pair","prediction":{"axes":[{"dimension":{"dynamic":false,"fixed":null,"symbolic":"B"},"role":"batch"},{"dimension":{"dynamic":false,"fixed":1,"symbolic":null},"role":null}],"dtype":{"admissible":["float32"]}},"target":{"axes":[{"dimension":{"dynamic":false,"fixed":null,"symbolic":"B"},"role":"batch"},{"dimension":{"dynamic":false,"fixed":2,"symbolic":null},"role":null}],"dtype":{"admissible":["float32"]}}},"prediction":{"axes":[{"dimension":{"dynamic":false,"fixed":null,"symbolic":"B"},"role":"batch"},{"dimension":{"dynamic":false,"fixed":1,"symbolic":null},"role":null}],"dtype":{"admissible":["float32"]}},"supervision_target":{"axes":[{"dimension":{"dynamic":false,"fixed":null,"symbolic":"B"},"role":"batch"},{"dimension":{"dynamic":false,"fixed":2,"symbolic":null},"role":null}],"dtype":{"admissible":["float32"]}}}',
    "sha256": "988ae88a5d88c4c495946937133394467cfe3df19c22629ac0cbe99748185b85",
}
PLUGIN_LOSS_TARGET_DTYPE = "float"
# The scalar is a mean over the objective's task-defined contributing units.
# Plugin comparability uses the framework's supported normalization vocabulary;
# mask semantics remain owned by ``forward`` below.
PLUGIN_LOSS_REDUCTION = "mean"


class MaskedMseConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MaskedMseLoss(nn.Module):
    """MSE over valid rows; target columns are ``[truth, validity_mask]``."""

    def __init__(self, config: MaskedMseConfig) -> None:
        super().__init__()

    def forward(self, output: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        if output.ndim != 2 or output.shape[1] != 1:
            raise ValueError(f"masked MSE needs output [B, 1], got {tuple(output.shape)}.")
        if target.ndim != 2 or target.shape != (output.shape[0], 2):
            raise ValueError(
                "masked MSE needs supervision [B, 2] carrying [truth, mask]; "
                f"got {tuple(target.shape)}."
            )
        mask = target[:, 1] > 0.5
        if not torch.any(mask):
            raise ValueError("masked MSE refuses a batch with no valid supervision.")
        error = output[:, 0] - target[:, 0].to(output.dtype)
        return torch.mean(torch.square(error[mask]))


PLUGIN_LOSS_CONFIG_CLASS = MaskedMseConfig
PLUGIN_LOSS_CLASS = MaskedMseLoss
