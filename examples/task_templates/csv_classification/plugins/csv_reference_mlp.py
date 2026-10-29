"""Reference model: Linear(features -> hidden) -> ReLU -> Linear(hidden -> classes).

``task.yaml`` ``model_plugins.require`` names this model type, so every run
has one known model that fits the task's input and output. The research loop
proposes its own models; this one only has to run, not to score well.

Model plugin contract: the module defines ``PLUGIN_MODEL_TYPE``,
``PLUGIN_OUTPUT_TYPE``, ``PLUGIN_CONFIG_CLASS`` and ``PLUGIN_MODEL_CLASS``.
The forward pass maps ``[B, FEATURE_COUNT] float32`` to ``[B, CLASS_COUNT]``
logits, matching ``forward_contract.model_io`` in ``declared/task_config.yaml``.
"""

from __future__ import annotations

import torch
from pydantic import BaseModel, Field
from torch import nn

#: EDIT HERE: the number of feature columns (``feature_count`` in task.yaml).
FEATURE_COUNT = 4
#: EDIT HERE: the number of classes (the length of ``classes`` in task.yaml).
CLASS_COUNT = 3

PLUGIN_MODEL_TYPE = "csv_reference_mlp"
PLUGIN_OUTPUT_TYPE = "classifier"


class CsvReferenceMlpConfig(BaseModel):
    """Settings the planner may choose. ``extra`` stays permissive on purpose:
    planner-emitted fields this config does not model are ignored, not refused."""

    #: The planner sends ``model_type`` in every plan; a plugin config declares it.
    model_type: str = Field(default="csv_reference_mlp")
    #: Read by the training engine at start-up; a tabular input has no segments.
    segmentation_size: int = Field(default=FEATURE_COUNT, ge=1)
    batch_size: int = Field(default=32, ge=1)
    hidden_dim: int = Field(default=32, ge=2, le=1024)


PLUGIN_CONFIG_CLASS = CsvReferenceMlpConfig


class CsvReferenceMlp(nn.Module):
    def __init__(self, config: CsvReferenceMlpConfig):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(FEATURE_COUNT, config.hidden_dim),
            nn.ReLU(),
            nn.Linear(config.hidden_dim, CLASS_COUNT),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Raw logits: the cross-entropy loss and the deliverable codec (argmax) expect them."""
        return self.net(x)


PLUGIN_MODEL_CLASS = CsvReferenceMlp
