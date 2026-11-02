"""Legacy direct-call initialization must not depend on ambient process RNGs."""

from __future__ import annotations

import random
from pathlib import Path
from typing import cast

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader, TensorDataset

import execute_tools.train_engine_sandbox as engine
from core.seeding import MissingRunSeed
from core.training_seeds import SeedContext, TrainingSeedPlan
from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig


def _config() -> WaveNetConfig:
    return WaveNetConfig(
        segmentation_size=1000,
        input_channels=4,
        residual_channels=8,
        gate_channels=8,
        skip_channels=8,
        kernel_size=2,
        num_blocks=1,
    )


def _run(tmp_path: Path, seed: int | None) -> dict:
    inputs = torch.arange(4000).reshape(4, 1000) % 256
    return engine.run_experiment(
        _config(),
        TrainConfig(epochs=1, batch_size=2, device="cpu"),
        LossConfig(),
        DataLoader(TensorDataset(inputs, inputs), batch_size=2),
        {"models": str(tmp_path)},
        "legacy",
        # Deliberate untyped-caller input for the runtime refusal witness.
        seed_plan=cast(TrainingSeedPlan, None)
        if seed is None
        else TrainingSeedPlan(SeedContext(run_seed=seed)),
    )


@pytest.mark.parametrize("plugin_rngs", [False, True], ids=["builtin", "plugin-global-rngs"])
def test_direct_call_seeds_before_model_construction(tmp_path, monkeypatch, plugin_rngs):
    """Removing seeding changes weights/losses after disturbing ambient RNGs.

    A plugin may use Python and NumPy to initialize parameters as well as
    torch; a torch-only repair must fail the plugin case.
    """
    original = engine.MODEL_REGISTRY["wavenet"]
    states: list[dict[str, torch.Tensor]] = []

    class RecordingModel(original):
        def __init__(self, config):
            super().__init__(config)
            if plugin_rngs:
                with torch.no_grad():
                    next(self.parameters()).add_(random.random() + float(np.random.random()))
            states.append({key: value.clone() for key, value in self.state_dict().items()})

    monkeypatch.setitem(engine.MODEL_REGISTRY, "wavenet", RecordingModel)
    histories = []
    for ambient_seed in (91, 182):
        random.seed(ambient_seed)
        np.random.seed(ambient_seed)
        torch.manual_seed(ambient_seed)
        histories.append(_run(tmp_path, 42)["loss_history"])
    assert all(torch.equal(states[0][key], states[1][key]) for key in states[0])
    assert histories[0] == histories[1]
    _run(tmp_path, 43)
    assert any(not torch.equal(states[0][key], states[2][key]) for key in states[0])


def test_missing_plan_refuses_before_construction(tmp_path, monkeypatch):
    """An explicit None must not reach model construction or publish a checkpoint."""

    def unexpected_model(_config):
        pytest.fail("model construction preceded the seed precondition")

    monkeypatch.setitem(engine.MODEL_REGISTRY, "wavenet", unexpected_model)
    with pytest.raises(MissingRunSeed):
        _run(tmp_path, None)
    assert list(tmp_path.iterdir()) == []


def test_cli_preserves_seeded_dataset_then_model_rng_sequence(
    tmp_path, monkeypatch, synthetic_dataset_profile
):
    """CLI already seeds: a second seed at construction rewinds NumPy's stream.

    The single-file dataset draws a NumPy offset before the plugin constructor;
    this witness checks the second draw reaches the model, preserving that route.
    """
    import sys

    context = SeedContext(run_seed=42)
    plan = TrainingSeedPlan(context)
    argv = ["trainer", "--data_dir", str(tmp_path), "--sandbox_dir", str(tmp_path / "sb")]
    for flag, config in (
        ("model_cfg", _config()),
        ("train_cfg", TrainConfig(epochs=1, device="cpu")),
        ("loss_cfg", LossConfig()),
        ("seed_context_json", context),
    ):
        path = tmp_path / f"{flag}.json"
        path.write_text(config.model_dump_json())
        argv.extend([f"--{flag}", str(path)])
    monkeypatch.setattr(sys, "argv", argv)
    observed = []

    class ConstructionReached(Exception):
        pass

    def dataset(*args, **kwargs):
        observed.append(int(np.random.randint(0, 20)))
        return TensorDataset(torch.zeros(2, 1000), torch.zeros(2, 1000))

    def model(_config):
        observed.append(int(np.random.randint(0, 20)))
        raise ConstructionReached

    monkeypatch.setattr(engine, "TIDMADDataset", dataset)
    monkeypatch.setitem(engine.MODEL_REGISTRY, "wavenet", model)
    with pytest.raises(ConstructionReached):
        engine.main()
    expected = np.random.RandomState(plan.init_numpy32).randint(0, 20, size=2).tolist()
    assert expected[0] != expected[1], "the witness must distinguish a rewind"
    assert observed == expected


def test_direct_initialization_is_independent_of_pythonhashseed(tmp_path):
    """A label-hash seed fallback changes plugin initialization across children."""
    import json
    import os
    import subprocess
    import sys

    script = """
import json
import random
import sys
from pathlib import Path
import numpy as np
import torch
from tests.unit.execute_tools.test_legacy_trainer_seeding import _run, engine

def construct(config):
    print(json.dumps([random.random(), float(np.random.random()), torch.rand(4).tolist()]))
    raise SystemExit(0)

engine.MODEL_REGISTRY["wavenet"] = construct
_run(Path(sys.argv[1]), 42)
"""
    outputs = []
    for hash_seed in ("1", "987"):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            env={**os.environ, "PYTHONHASHSEED": hash_seed, "CUDA_VISIBLE_DEVICES": ""},
            cwd=Path(__file__).resolve().parents[3],
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(json.loads(result.stdout.strip().splitlines()[-1]))
    assert outputs[0] == outputs[1]
