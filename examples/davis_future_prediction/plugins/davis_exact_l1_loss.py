"""DAVIS 2017 future-frame prediction — the frozen EXACT MAE / L1 objective.

Step 12 / PR-12d D4c, ruling **A3**. §22.9a freezes DAVIS's training objective
as exact mean absolute error. Three things were forbidden while closing it, and
each forbids a shortcut that would have been easier:

* **``smooth_l1(beta=0.1)`` is not a substitute.** It is quadratic below beta
  and linear above, so it is not L1 anywhere near convergence — which is
  exactly where a future-frame model spends its time. Accepting it would have
  meant the run optimised something the frozen spec does not name while the
  report said MAE.
* **Growing ``LossConfig.loss_type``'s closed ``Literal`` is not the fix.**
  A central enum of task objectives is the task catalog this whole step exists
  to avoid; the moment DAVIS's objective becomes a framework member, the next
  task's does too.
* **A new capability family is not needed.** This plugin travels the EXISTING
  ``custom`` route — the same one any proposer-generated loss uses.

**No leading underscore, unlike this pack's other private modules.** A loss is
resolved BY NAME through a directory SCAN (`_resolve_loss_dirs` →
`load_loss_plugin`), and that scan skips `_`-prefixed members — the convention
that keeps Health view providers out of it. An underscore here would have made
the objective unreachable while every declaration still looked correct.

The declarations below are what make that route honest rather than merely
available. Both were silently ignored before D4c:

``PLUGIN_LOSS_TARGET_DTYPE = "float"``
    DAVIS targets are continuous frames. Without this the training child's
    Tier-2 filesystem load left ``LOSS_TARGET_DTYPE_REGISTRY`` empty and the
    targets were cast to ``int64`` — an exact-MAE objective computing against
    truncated integers, with nothing saying so (**F-12d-2**).

``PLUGIN_LOSS_REDUCTION = "mean"``
    States the normalization, which is what
    ``comparability = custom_objective_undeclared`` was asking for. A
    mean-reduced objective's per-epoch values are comparable for the same
    reason the audited built-in kinds' are.
"""

from __future__ import annotations

import torch
import torch.nn as nn
from pydantic import BaseModel, ConfigDict

PLUGIN_LOSS_TYPE = "davis_exact_l1"
PLUGIN_LOSS_TARGET_DTYPE = "float"
PLUGIN_LOSS_REDUCTION = "mean"


class PluginLossConfig(BaseModel):
    """No hyperparameters, and that is the point.

    Exact L1 has nothing to tune. A ``beta``, a ``delta`` or a threshold here
    would be the smooth-L1 shortcut arriving through the back door — the
    objective would become approximately-L1 and configurable, which is exactly
    what A3 forbids.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class PluginLoss(nn.Module):
    """Mean absolute error over every element. Exactly L1, everywhere.

    ``torch.nn.L1Loss(reduction="mean")`` and nothing else: no beta, no
    Huber transition, no per-element weighting. The mean is over all elements
    of the batch (C × T × H × W), which is the same normalization the DAVIS
    `mae` METRIC uses — so the run is optimised on the quantity it is scored
    on, rather than on a proxy that happens to correlate.
    """

    def __init__(self, config: PluginLossConfig) -> None:
        super().__init__()
        self.criterion = nn.L1Loss(reduction="mean")

    def forward(self, output: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        if output.shape != target.shape:
            raise ValueError(
                f"davis_exact_l1 needs matching shapes; got output {tuple(output.shape)} "
                f"and target {tuple(target.shape)}. A broadcast here would silently "
                "average over the wrong axes and still return a plausible scalar."
            )
        return self.criterion(output, target.to(output.dtype))


PLUGIN_LOSS_CONFIG_CLASS = PluginLossConfig
PLUGIN_LOSS_CLASS = PluginLoss
