"""A round that trains nothing must not be reported as progress.

The defect (F13, found by a fresh-user onboarding witness against
v0.1.0-rc.1 on a 6-row out-of-tree task). `DataLoader(drop_last=True)`
yields `rows // batch_size` batches, so a training scope smaller than one
batch produces an EMPTY epoch. The engines then:

    Epoch 0: 0it            <- no forward, no backward, no optimizer step
    Avg Loss: nan           <- NaN fabricated for an absent measurement
    Model saved to: ...     <- untrained weights checkpointed
    _OK_<exp_id>            <- and the trainer's SUCCESS sentinel written

after which inference ran, scoring ran, and the round was reported as
`Round 1/1 Complete. Score: 11.96875`. Nothing refused: every term of the
arithmetic was already known -- `workload_resolvers` computes the same
`samples_per_epoch // batch_size` floor and names `drop_last` in its own
comments -- and a search of production for an empty-loader or zero-step
refusal returned nothing.

Reachability, which is the point: the fix is placed at the ONE line in
each engine that used to fabricate the NaN, so it cannot be bypassed by a
path that still reaches a loss history. `TrainingScopeError` propagates
out of the training subprocess, which the executor's subprocess-error
path already classifies as `error_training` -- the SAME typed mechanism
`ValidationScopeError` uses for its zero-requested-rows rule. No second
validity system is introduced, and the record fields that were already
honest (`train_objective [null]`, `scientific_authority.authoritative
false`) keep their meaning.

The refusal is generic: it reads the executed step count, not any task's row
geometry, and nothing here is tuned for a scientific dataset.
"""

from __future__ import annotations

import os

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader, Dataset

import execute_tools.train_engine_sandbox as tes
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    TrainingScopeError,
    bind_task_data_path,
)
from ml_models.models_format_sandbox import LossConfig, TrainConfig, get_config_class
from tests.helpers.two_family_profile import make_two_family_profile

SEG = 1024

#: One cheap builtin. The refusal is architecture-independent -- it reads a
#: step count -- so parametrising over the model zoo would buy nothing and
#: cost six CPU trainings.
MODEL_TYPE = "punet"
TINY = {"multi": 8, "depth": 2, "embedding_dim": 8, "kernel_size": 3}
PAIR_PROFILE = make_two_family_profile(num_files=6, psd_segment_length=2_048, segments_per_file=2)


def _cfg():
    return get_config_class(MODEL_TYPE)(segmentation_size=SEG, **TINY)


def _sandbox_dirs(tmp_path) -> dict[str, str]:
    dirs = {"models": str(tmp_path / "cached_models"), "results": str(tmp_path / "records")}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


def _train_cfg(batch_size: int) -> TrainConfig:
    return TrainConfig(
        lr=1e-4, epochs=1, batch_size=batch_size, optimizer_type="adam", device="cpu"
    )


class _Pairs(Dataset):
    """int16 pairs, the dtype the real loaders serve."""

    def __init__(self, n: int):
        self.n = n

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, idx: int):
        x = torch.full((SEG,), 100 + idx, dtype=torch.int16)
        return x, x.clone()


class _PairTaskDataPath:
    """Minimal in-memory task seam for streaming-engine reachability."""

    task_data_path_id = "zero_step_pair_fixture"

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset:
        assert isinstance(scope, list)
        return _Pairs(len(scope))

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset:
        assert isinstance(scope, list)
        return _Pairs(len(scope))

    def write_deliverable(self, outputs, request: DeliverableWriteRequest) -> None:
        raise AssertionError("zero-step training must not write a deliverable")

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        raise AssertionError("zero-step training must not read an evaluation payload")


# ---------------------------------------------------------------------------
# The refusal authority
# ---------------------------------------------------------------------------


class TestRefusalAuthority:
    def test_zero_steps_is_refused(self):
        with pytest.raises(TrainingScopeError):
            tes.refuse_zero_optimizer_steps(0, epoch=0, batch_size=8, rows=6)

    def test_the_message_names_the_geometry_that_caused_it(self):
        """An operator must be able to act on it without reading the source."""
        with pytest.raises(TrainingScopeError) as exc:
            tes.refuse_zero_optimizer_steps(0, epoch=0, batch_size=8, rows=6)
        message = str(exc.value)
        assert "6 rows" in message and "batch_size 8" in message
        assert "drop_last" in message

    def test_a_dataset_with_no_declared_length_is_still_refused(self):
        """The guard must not become inapplicable where counting is hardest.

        An iterable-style dataset has no `__len__`. Making the refusal
        depend on reading one would silently disable it for exactly the
        datasets whose step count cannot be predicted in advance.
        """
        with pytest.raises(TrainingScopeError):
            tes.refuse_zero_optimizer_steps(0, epoch=0, batch_size=8, rows=None)

    def test_a_trained_epoch_is_not_refused(self):
        """The guard must not manufacture a failure it did not observe."""
        tes.refuse_zero_optimizer_steps(1, epoch=0, batch_size=8, rows=8)


# ---------------------------------------------------------------------------
# Reachability -- the production engines
# ---------------------------------------------------------------------------


class TestEpochEngineRefuses:
    def test_an_empty_loader_fails_the_attempt(self, tmp_path):
        """THE witness: 6 rows, batch_size 8, drop_last -> 0 batches."""
        loader = DataLoader(_Pairs(6), batch_size=8, drop_last=True)
        assert len(loader) == 0, "the witness did not produce an empty epoch"

        with pytest.raises(TrainingScopeError):
            tes.run_experiment(
                _cfg(),
                _train_cfg(batch_size=8),
                LossConfig(),
                loader,
                _sandbox_dirs(tmp_path),
                "zero_step_witness",
            )

    def test_no_checkpoint_and_no_success_sentinel_are_written(self, tmp_path):
        """The `_OK_` sentinel is what tells inference the model is usable.

        Writing it for a model that never took an optimizer step is how an
        untrained checkpoint reached inference, scoring and the round
        report in the first place.
        """
        dirs = _sandbox_dirs(tmp_path)
        with pytest.raises(TrainingScopeError):
            tes.run_experiment(
                _cfg(),
                _train_cfg(batch_size=8),
                LossConfig(),
                DataLoader(_Pairs(6), batch_size=8, drop_last=True),
                dirs,
                "zero_step_witness",
            )
        assert os.listdir(dirs["models"]) == [], (
            "an untrained model was checkpointed for a round that ran no optimizer step"
        )

    def test_a_scope_of_exactly_one_batch_still_trains(self, tmp_path):
        """The boundary, from the trainable side -- `rows == batch_size`."""
        dirs = _sandbox_dirs(tmp_path)
        out = tes.run_experiment(
            _cfg(),
            _train_cfg(batch_size=6),
            LossConfig(),
            DataLoader(_Pairs(6), batch_size=6, drop_last=True),
            dirs,
            "one_batch",
        )
        assert not np.isnan(out["final_loss"])
        assert "_OK_one_batch" in os.listdir(dirs["models"])


class TestStreamingEngineRefuses:
    """THE production training path, so its own reachability is required."""

    def test_a_batch_larger_than_the_scope_fails_the_attempt(self, tmp_path):
        with bind_task_data_path(_PairTaskDataPath()):
            with pytest.raises(TrainingScopeError):
                tes.run_experiment_streaming(
                    _cfg(),
                    # The scope materializes 6 rows; 8 cannot fill a batch.
                    _train_cfg(batch_size=8),
                    LossConfig(),
                    sample_set={},
                    task_scope=list(range(6)),
                    data_dir=str(tmp_path),
                    sandbox_dirs=_sandbox_dirs(tmp_path),
                    exp_id="streaming_zero_step",
                    train_base_seed=42,
                    profile=PAIR_PROFILE,
                )

    def test_a_scope_that_fills_a_batch_still_trains(self, tmp_path):
        """Parity guard: the refusal must not touch a trainable streaming run."""
        with bind_task_data_path(_PairTaskDataPath()):
            out = tes.run_experiment_streaming(
                _cfg(),
                _train_cfg(batch_size=6),
                LossConfig(),
                sample_set={},
                task_scope=list(range(6)),
                data_dir=str(tmp_path),
                sandbox_dirs=_sandbox_dirs(tmp_path),
                exp_id="streaming_ok",
                train_base_seed=42,
                profile=PAIR_PROFILE,
            )
        assert out is not None
        assert not np.isnan(out["final_loss"])
