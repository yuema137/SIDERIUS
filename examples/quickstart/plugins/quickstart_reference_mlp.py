"""Quickstart — reference model plugin (a 2-layer MLP, ~100 parameters).

Sanctioned plugin SOURCE under ``examples/quickstart/plugins/`` (governance
guard (b)); loaded dynamically through the model-plugin mechanism, never
imported by the framework. NO leading underscore, deliberately: unlike the
task/metric plugins, this file must be visible to the plugin DIRECTORY
scanners — today via ``SIDERIUS_PLUGIN_DIRS`` pointing at this directory,
post-12d via the manifest's ``model_plugins:`` section (D8a).

Contract (``agent_generated/models`` plugin convention): the module defines
``PLUGIN_MODEL_TYPE`` / ``PLUGIN_CONFIG_CLASS`` / ``PLUGIN_MODEL_CLASS``.
Forward: ``[B, 4] float32 -> [B, 2] float32`` logits — exactly the pack's
declared forward contract.

The model does not need to train WELL: the quickstart demonstrates workflow
mechanics, and the pack docs say so explicitly.
"""

from __future__ import annotations

import torch
from pydantic import BaseModel, ConfigDict, Field
from torch import nn

PLUGIN_MODEL_TYPE = "quickstart_reference_mlp"


class QuickstartReferenceMlpConfig(BaseModel):
    """Hyperparameters for the reference MLP (all defaults are CPU-trivial)."""

    model_config = ConfigDict(extra="forbid")

    #: Engine-residue compatibility field (the streaming engine reads
    #: ``model_cfg.segmentation_size`` at run start; nothing on the
    #: quickstart path consumes it — the ``pets_reference_cnn`` precedent).
    segmentation_size: int = Field(default=4, ge=1)
    batch_size: int = Field(default=32, ge=1)
    hidden_dim: int = Field(default=16, ge=2, le=256)


PLUGIN_CONFIG_CLASS = QuickstartReferenceMlpConfig


class QuickstartReferenceMlp(nn.Module):
    """Linear(4→h) → ReLU → Linear(h→2). At h=16: 114 parameters."""

    def __init__(self, config: QuickstartReferenceMlpConfig):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(4, config.hidden_dim),
            nn.ReLU(inplace=True),
            nn.Linear(config.hidden_dim, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """``[B, 4] float32 -> [B, 2] float32`` logits (no softmax — the
        deliverable codec and the metric own that decision)."""
        return self.net(x)


PLUGIN_MODEL_CLASS = QuickstartReferenceMlp
