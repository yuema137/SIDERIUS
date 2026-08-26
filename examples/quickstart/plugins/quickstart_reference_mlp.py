"""Quickstart — reference model plugin (a 2-layer MLP, ~100 parameters).

Sanctioned plugin SOURCE under ``examples/quickstart/plugins/`` (governance
guard (b)); loaded dynamically through the model-plugin mechanism, never
imported by the framework. NO leading underscore, deliberately: unlike the
task/metric plugins, this file must be visible to the plugin DIRECTORY
scanners — today via ``SIDERIUS_PLUGIN_DIRS`` pointing at this directory,
post-12d via the manifest's ``model_plugins:`` section (D8a).

Contract (``agent_generated/models`` plugin convention): the module defines
``PLUGIN_MODEL_TYPE`` / ``PLUGIN_CONFIG_CLASS`` / ``PLUGIN_MODEL_CLASS``, and
DECLARES ``PLUGIN_OUTPUT_TYPE``. Forward: ``[B, 4] float32 -> [B, 2] float32``
logits — exactly the pack's declared forward contract.

**This file is the shape new packs copy** (the pack README §8 says so), which
is why two declarations below are explicit rather than left to a default.
Both defaults happen to be RIGHT for the quickstart and WRONG for most tasks,
so omitting them here taught a shape that detonates on the first copy:

* ``model_type`` on the config — the FRAMEWORK injects it into every plan
  before execution (``planning.py``), because every BUILT-IN config inherits
  the field from ``BaseConfig``. A plugin config is a plain ``BaseModel`` and
  inherits nothing, so omitting it means the injected key is silently dropped
  and the run fails a layer later, in the trainer, on ``model_cfg.model_type``
  (Lane E / F10).
* ``PLUGIN_OUTPUT_TYPE`` — optional, defaulting to ``"classifier"``. The
  quickstart IS a classifier, so the omission was invisible here; a
  regression pack copying this file inherited the default and was refused at
  admission, correctly, for declaring a class alphabet its task does not have
  (Lane E / F11b).


The model does not need to train WELL: the quickstart demonstrates workflow
mechanics, and the pack docs say so explicitly.
"""

from __future__ import annotations

import torch
from pydantic import BaseModel, Field
from torch import nn

PLUGIN_MODEL_TYPE = "quickstart_reference_mlp"

#: Declared, not defaulted — see the module docstring. ``[B, 2]`` logits over
#: a 2-class alphabet is a classifier; a pack predicting a continuous target
#: declares ``"regressor"`` here instead.
PLUGIN_OUTPUT_TYPE = "classifier"


class QuickstartReferenceMlpConfig(BaseModel):
    """Hyperparameters for the reference MLP (all defaults are CPU-trivial).

    ``extra`` is deliberately left at Pydantic's permissive default, matching
    ``BaseConfig`` and both other reference plugins. An ``extra="forbid"``
    here turns any planner-emitted field this config does not model into a
    hard plan rejection — and a rejected plan does not consume an attempt, so
    an unsatisfiable schema burns the whole round budget without training
    once (Lane E / F10).
    """

    #: The planner emits this in every plan (every built-in config inherits it
    #: from ``BaseConfig``). A plugin config inherits nothing, so it declares
    #: the field itself and defaults it to the plugin's own key.
    #:
    #: A LITERAL, not ``PLUGIN_MODEL_TYPE``, matching pets and davis. The
    #: constant-reference form would make drift impossible by construction and
    #: is the better engineering in isolation — but it would make the identity
    #: cross-check in
    #: ``tests/unit/examples/test_lane_e_f10_plugin_model_config_contract.py``
    #: vacuous for this pack alone, and #318's whole thesis is that the three
    #: exemplars agree. Moving ALL THREE to the constant-reference form is a
    #: legitimate future change; moving only this one is not.
    model_type: str = Field(default="quickstart_reference_mlp")

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
