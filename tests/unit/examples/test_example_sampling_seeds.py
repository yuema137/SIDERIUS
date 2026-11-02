"""Example data sampling must refuse missing seeds and replay explicit ones (#1169)."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from core.seeding import MissingRunSeed, SeedCoordinates, derive_seed
from core.training_seeds import SeedContext, TrainingSeedPlan
from execute_tools.task_data_path import EpochSamplingParams, ScopeBuildRequest
from tests.unit.examples.test_quickstart_pack import PACK, _load_pack_module
from tests.unit.examples.test_synthetic_masked_regression_pack import _load


@pytest.fixture(params=["quickstart", "masked"])
def example(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Any, str]:
    if request.param == "quickstart":
        module = _load_pack_module()
        bundle = module.materialize_run_bundle(PACK, tmp_path / "bundle")
        return module.QuickstartTaskDataPath(), bundle["data_dir"]
    module = _load("masked_seed_test", "plugins/_masked_task.py")
    bundle = module.materialize_run_bundle(tmp_path / "bundle")
    return module.SyntheticMaskedTaskDataPath(), bundle["data_dir"]


def _request(portion: float = 1.0, seed: int | None = None) -> ScopeBuildRequest:
    return ScopeBuildRequest(
        round_kind="formal", selection_strategy="snapshot", portion=portion, seed=seed
    )


@pytest.mark.parametrize("builder", ["build_training_scope", "build_eval_scope"])
def test_scope_sampling_requires_seed(example: tuple[Any, str], builder: str) -> None:
    """Reverting either scope guard accepts None instead of raising here."""
    impl, _ = example
    build = getattr(impl, builder)
    with pytest.raises(MissingRunSeed, match=r"request\.seed"):
        build(_request(0.5))
    seeds = [derive_seed(n, "tuner.train_sampling", SeedCoordinates()) for n in (0, 1)]
    scopes = [build(_request(0.5, seed)) for seed in seeds]
    assert scopes[0] == build(_request(0.5, seeds[0]))
    assert scopes[0] != scopes[1]
    assert build(_request(0.5, 0)).rows  # Zero is a supplied seed, not absence.
    assert build(_request()).rows  # No stochastic selection needs no seed.


def test_epoch_sampling_requires_seed(example: tuple[Any, str]) -> None:
    """Reverting either epoch guard accepts None; ignoring the seed breaks replay."""
    impl, data_dir = example
    scope = impl.build_training_scope(_request())
    params = EpochSamplingParams(data_dir=data_dir, train_portion=0.5)
    with pytest.raises(MissingRunSeed, match="epoch_seed"):
        impl.training_dataset(scope, params)
    seeds = [TrainingSeedPlan(SeedContext(run_seed=n)).epoch(0).subsample for n in (0, 1)]
    first = impl.training_dataset(scope, params.model_copy(update={"epoch_seed": seeds[0]}))
    repeat = impl.training_dataset(scope, params.model_copy(update={"epoch_seed": seeds[0]}))
    different = impl.training_dataset(scope, params.model_copy(update={"epoch_seed": seeds[1]}))
    assert np.array_equal(first.tensors[0].numpy(), repeat.tensors[0].numpy())
    assert not np.array_equal(first.tensors[0].numpy(), different.tensors[0].numpy())
    assert len(impl.training_dataset(scope, params.model_copy(update={"epoch_seed": 0}))) > 0
    full = impl.training_dataset(scope, EpochSamplingParams(data_dir=data_dir, max_samples=3))
    assert len(full) == 3  # Deterministic prefix ceilings do not draw randomness.
