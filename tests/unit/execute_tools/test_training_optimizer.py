"""One optimizer switch, shared by the trainer and by what measures it.

V20 PR C2 / C2-2.

`build_training_optimizer` was extracted from two byte-identical blocks in
`run_experiment` and `run_experiment_streaming`. The reason it is shared
rather than copied is a memory fact, not a style preference: AdamW and Adam
each hold two full-size moment buffers per parameter and SGD without
momentum holds none, so a pre-phase measurement taken against the wrong
optimizer under-states the requirement by two parameter tensors -- the OOM
direction.

These assert the branch behaviour (which optimizer, and whether
`weight_decay` is carried), which is runtime routing rather than anything
the `Literal["adam", "adamw", "sgd"]` declaration already guarantees.
"""

from __future__ import annotations

import pytest
import torch
from torch import nn

from execute_tools.train_engine_sandbox import build_training_optimizer
from ml_models.models_format_sandbox import TrainConfig


@pytest.fixture
def model() -> nn.Module:
    return nn.Linear(3, 3)


@pytest.mark.parametrize(
    "optimizer_type,expected",
    [("adamw", torch.optim.AdamW), ("adam", torch.optim.Adam), ("sgd", torch.optim.SGD)],
)
def test_each_declared_optimizer_routes_to_its_class(model, optimizer_type, expected):
    cfg = TrainConfig(optimizer_type=optimizer_type, lr=1e-3)
    assert type(build_training_optimizer(model, cfg)) is expected


def test_only_adamw_carries_weight_decay(model):
    """The trainer passes `weight_decay` to AdamW and to neither of the
    others. Adam would silently accept it and decay differently; that
    divergence is invisible in a loss curve."""
    cfg = TrainConfig(optimizer_type="adamw", lr=1e-3, weight_decay=0.05)
    assert build_training_optimizer(model, cfg).param_groups[0]["weight_decay"] == 0.05

    adam = build_training_optimizer(model, TrainConfig(optimizer_type="adam", weight_decay=0.05))
    assert adam.param_groups[0]["weight_decay"] == 0.0, (
        "Adam must keep torch's default, exactly as the trainer left it"
    )


def test_the_optimizer_covers_the_model_it_was_given(model):
    """Guards the copy-paste failure the measurement worker also guards:
    an optimizer built over a different module trains nothing."""
    optimizer = build_training_optimizer(model, TrainConfig())
    covered = {id(p) for group in optimizer.param_groups for p in group["params"]}
    assert covered == {id(p) for p in model.parameters()}
