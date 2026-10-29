"""Issue #983 S7b: model probes draw from the run seed's ``validation.probe`` stream.

Literal seeds are pinned (``siderius-seed/v1``), never recomputed by the test.
The probe child is exercised for real (``run_bounded_probe`` spawns
``validator_probe_worker``), so the environment transport is covered.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest
import torch

from agent.skills.validator_probe_worker import run_bounded_probe
from core.probe_seeds import (
    PROBE_SEED_ENV,
    probe_process_seeds,
    probe_seed_context,
    require_probe_seed,
)
from core.seeding import MissingRunSeed
from execute_tools.process_seeding import seeded_scope
from nodes.ml_code_validator_agent.ml_code_validator_agent import (
    _check_instantiation_and_gradient,
)

#: torch seeds of run seed 11, iteration 2, no node id, attempts 1 and 2.
ATTEMPT_TORCH_SEED = {1: 7970725655570677279, 2: 2141737277981433782}


def _context(attempt: int):
    return probe_seed_context(11, iteration=2, node_id=None, attempt=attempt)


def _recording_plugin(tmp_path: Path) -> tuple[Path, Path]:
    """A legacy-contract classifier that records the torch seed it was built under."""
    record = tmp_path / "initial_seed.txt"
    models = tmp_path / "models"
    models.mkdir()
    plugin = models / "seed_recording_model.py"
    plugin.write_text(
        f"""import torch
from pathlib import Path
from torch import nn
from pydantic import BaseModel
PLUGIN_MODEL_TYPE = "seed_recording_model"
PLUGIN_OUTPUT_TYPE = "classifier"
class Config(BaseModel):
    segmentation_size: int = 64
class Model(nn.Module):
    def __init__(self, config):
        super().__init__()
        Path({str(record)!r}).write_text(str(torch.initial_seed()))
        self.embed = nn.Embedding(256, 4)
        self.head = nn.Linear(4, 256)
    def forward(self, x):
        return self.head(self.embed(x)).transpose(1, 2)
PLUGIN_CONFIG_CLASS = Config
PLUGIN_MODEL_CLASS = Model
"""
    )
    return plugin, record


def test_probe_child_is_seeded_from_the_context_it_inherits(tmp_path):
    """Fails if the probe child is not seeded before the candidate is built, if
    the context does not reach it through the environment, or if a retried
    implementation (next attempt) repeats the previous draw."""
    plugin, record = _recording_plugin(tmp_path)
    for attempt in (1, 2):
        verdict = run_bounded_probe(str(plugin), None, seed_context=_context(attempt))
        assert all(verdict[:3]), verdict
        assert int(record.read_text()) == ATTEMPT_TORCH_SEED[attempt]


def test_in_process_probe_is_seeded_and_restores_the_callers_streams(tmp_path):
    """Fails if an in-process validator probe draws from the orchestrator's
    unseeded streams, or leaves them changed afterwards."""
    plugin, record = _recording_plugin(tmp_path)
    random.seed(5)
    np.random.seed(5)
    torch.manual_seed(5)
    expected = (random.random(), np.random.rand(), torch.rand(1))
    random.seed(5)
    np.random.seed(5)
    torch.manual_seed(5)
    verdict = _check_instantiation_and_gradient(str(plugin), None, probe_seed=_context(1))
    assert all(verdict[:3]), verdict
    assert int(record.read_text()) == ATTEMPT_TORCH_SEED[1]
    observed = (random.random(), np.random.rand(), torch.rand(1))
    assert observed[:2] == expected[:2] and torch.equal(observed[2], expected[2])


def test_seeded_scope_repeats_draws_for_the_same_probe_context():
    """Fails if the same probe context does not reproduce the same draws."""
    seeds = probe_process_seeds(_context(1))
    draws = []
    for _ in range(2):
        with seeded_scope(seeds):
            draws.append((random.random(), float(np.random.rand()), torch.rand(3)))
    assert draws[0][:2] == draws[1][:2] and torch.equal(draws[0][2], draws[1][2])


def test_probe_without_a_seed_context_is_refused():
    """Fails if a probe silently runs unseeded (or invents a seed) when no
    context is supplied or inherited: only an entry boundary may generate."""
    with pytest.raises(MissingRunSeed):
        require_probe_seed(None, {})
    with pytest.raises(MissingRunSeed):
        probe_seed_context(None, iteration=1, node_id=None, attempt=1)
    inherited = {PROBE_SEED_ENV: _context(2).model_dump_json()}
    assert require_probe_seed(None, inherited) == _context(2)


def test_standalone_cli_seed_honors_run_seed_and_prints_the_shared_line(capsys):
    """Fails if a standalone implementor/validator CLI ignores ``--run_seed`` or
    prints a seed line in a format other than the single ``[seed]`` formatter."""
    from core.probe_seeds import standalone_probe_seed

    explicit = standalone_probe_seed(4_503_599_627_370_497)
    assert explicit.run_seed == 4_503_599_627_370_497 and explicit.at.attempt is None
    assert capsys.readouterr().out == "[seed] run_seed=4503599627370497 source=operator\n"
    generated = standalone_probe_seed(None)
    assert capsys.readouterr().out == f"[seed] run_seed={generated.run_seed} source=generated\n"


def test_candidate_node_probes_at_its_iteration_node_and_attempt():
    """Fails if a candidate graph node's probe context drops its loop iteration
    or node id (two nodes or loop bodies would then share one draw), or uses
    a seed other than the receipt's admitted run seed."""
    from types import SimpleNamespace

    from tools.candidate_worker.phases import context_probe_seed

    context = SimpleNamespace(iteration=3, node_id="validate", attempt=1)
    seed = context_probe_seed(context, SimpleNamespace(run_seed=11))
    assert (seed.run_seed, seed.at.iteration, seed.at.node_id, seed.at.attempt) == (
        11,
        3,
        "validate",
        1,
    )
    with pytest.raises(MissingRunSeed):
        context_probe_seed(context, SimpleNamespace(run_seed=None))


def test_seeded_scope_never_touches_a_cuda_device(monkeypatch):
    """Fails if seeded_scope forks CUDA RNG state: that creates a CUDA context
    (about 0.5 GB) on every visible GPU inside the orchestrator or a worker,
    competing with parallel training. Probes run on CPU."""
    import execute_tools.process_seeding as seeding

    calls = []
    real = torch.random.fork_rng

    def recording(*args, **kwargs):
        calls.append(kwargs.get("devices", args[0] if args else None))
        return real(*args, **kwargs)

    monkeypatch.setattr(seeding.torch.random, "fork_rng", recording)
    with seeded_scope(probe_process_seeds(_context(1))):
        torch.rand(1)
    assert calls == [[]]
