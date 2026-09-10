"""Explicit test-owned data path for the two-family trainer witnesses.

Only the small fixture codec lives here. Training, validation transactions,
measurement and persistence remain the real framework implementation.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import h5py
import numpy as np
import torch
from pydantic import BaseModel, ConfigDict
from torch.utils.data import TensorDataset

from execute_tools.task_data_path import (
    EpochSamplingParams,
    EvalMaterializationParams,
    ValidationScopeError,
)

if TYPE_CHECKING:
    from tests.helpers.two_family_profile import TwoFamilyFixture


class SyntheticTrainingScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: Literal["training", "validation"]
    selection: dict[str, list[int]]
    segment_length: int
    row_length: int

    @property
    def rows(self) -> int:
        return sum(map(len, self.selection.values())) * (self.segment_length // self.row_length)


class TwoFamilyDataPath:
    task_data_path_id = "synthetic_two_family_training"

    def __init__(self, fixture: TwoFamilyFixture | None = None):
        self.fixture = fixture

    def scope(self, selection, *, family="training") -> SyntheticTrainingScope:
        assert self.fixture is not None, "Scope construction needs the explicit fixture"
        return SyntheticTrainingScope(
            family=family,
            selection={str(key): values for key, values in selection.items()},
            segment_length=self.fixture.seg_size * self.fixture.ml_segs_per_psd,
            row_length=self.fixture.seg_size,
        )

    def scope_kwargs(self, training_set, validation_set=None) -> dict:
        evaluation = (
            None if validation_set is None else self.scope(validation_set, family="validation")
        )
        return {
            "task_scope": self.scope(training_set),
            "task_eval_scope": evaluation,
            "validation_requested_rows": None if evaluation is None else evaluation.rows,
        }

    def build_training_scope(self, request):
        raise NotImplementedError("Tests provide explicit scopes")

    def build_eval_scope(self, request):
        raise NotImplementedError("Tests provide explicit scopes")

    def serialize_scope(self, scope: object) -> str:
        assert isinstance(scope, SyntheticTrainingScope)
        return scope.model_dump_json()

    def deserialize_scope(self, payload: str) -> SyntheticTrainingScope:
        return SyntheticTrainingScope.model_validate_json(payload)

    def training_dataset(self, scope: object, params: EpochSamplingParams):
        dataset = self._dataset(scope, params.data_dir)
        indices = list(range(len(dataset)))
        if params.train_portion is not None:
            indices = random.Random(params.epoch_seed).sample(
                indices, max(1, int(len(indices) * params.train_portion))
            )
        if params.max_samples is not None:
            indices = indices[: params.max_samples]
        return TensorDataset(*(tensor[indices] for tensor in dataset.tensors))

    def validation_dataset(self, scope: object, params: EvalMaterializationParams):
        return self._dataset(scope, params.data_dir)

    def _dataset(self, scope: object, data_dir: str) -> TensorDataset:
        assert isinstance(scope, SyntheticTrainingScope)
        inputs, targets = [], []
        for file_id, segments in scope.selection.items():
            path = Path(data_dir) / f"{scope.family}_{int(file_id):04d}.h5"
            with h5py.File(path, "r") as handle:
                for segment in segments:
                    start = segment * scope.segment_length
                    stop = start + scope.segment_length
                    for channel, rows in (("input", inputs), ("target", targets)):
                        values = np.asarray(
                            handle[f"timeseries/{channel}/timeseries"][start:stop],
                            dtype=np.int64,
                        )
                        if len(values) != scope.segment_length:
                            raise ValidationScopeError("synthetic fixture segment is incomplete")
                        rows.extend((values + 128).reshape(-1, scope.row_length))
        if not inputs:
            raise ValidationScopeError("synthetic fixture requested zero rows")
        return TensorDataset(torch.tensor(np.stack(inputs)), torch.tensor(np.stack(targets)))

    def write_deliverable(self, outputs, request):
        raise NotImplementedError("This trainer-only witness does not produce inference artifacts")

    def read_evaluation_payload(self, request):
        raise NotImplementedError("This trainer-only witness does not score artifacts")
