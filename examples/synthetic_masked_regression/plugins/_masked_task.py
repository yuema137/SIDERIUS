"""Executable data and deliverable behavior for synthetic masked regression."""

from __future__ import annotations

import csv
import json
import math
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict

from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    ScopeBuildRequest,
    ValidationScopeError,
    deserialize_rows_scope,
)

if TYPE_CHECKING:
    from torch.utils.data import Dataset

TASK_ID = "synthetic_masked_regression"
GENERATOR_SEED = 20260829
SHARD_COUNT = 3
ROWS_PER_SHARD = 24
FEATURE_DIM = 3
TRAIN_SHARDS = (0, 1)
EVAL_SHARD = 2
SCOPE_KIND = "synthetic_masked_regression_rows"


class MaskedScopeRow(BaseModel):
    """One row identity and its task-owned continuous supervision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample_id: str
    shard: int
    row: int
    target: float
    valid: bool


class MaskedScope(BaseModel):
    """Canonical row scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rows: tuple[MaskedScopeRow, ...]


def generate_shard(shard: int) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Generate one deterministic shard with a nontrivial validity mask."""
    if not 0 <= shard < SHARD_COUNT:
        raise ValueError(f"shard must be in [0, {SHARD_COUNT}); got {shard}.")
    rng = np.random.default_rng((GENERATOR_SEED, shard))
    features = rng.uniform(-1.0, 1.0, (ROWS_PER_SHARD, FEATURE_DIM)).astype(np.float32)
    targets = (1.5 * features[:, 0] - 0.75 * features[:, 1] + features[:, 2] ** 2).astype(
        np.float32
    )
    valid = (np.arange(ROWS_PER_SHARD) % 4 != 0).astype(np.float32)
    sample_ids = [f"m{shard}r{row:03d}" for row in range(ROWS_PER_SHARD)]
    return sample_ids, features, targets, valid


def shard_filename(shard: int) -> str:
    return f"shard_{shard:04d}.csv"


def write_data_dir(data_dir: str | Path) -> None:
    """Materialize all deterministic shards outside the checkout."""
    target_dir = Path(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    for shard in range(SHARD_COUNT):
        sample_ids, features, targets, valid = generate_shard(shard)
        path = target_dir / shard_filename(shard)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("sample_id", "x0", "x1", "x2", "target", "valid"))
            for sample_id, row, target, mask in zip(
                sample_ids, features, targets, valid, strict=True
            ):
                writer.writerow(
                    (
                        sample_id,
                        *(f"{float(value):.8f}" for value in row),
                        f"{target:.8f}",
                        int(mask),
                    )
                )


def _rows_for_shard(shard: int) -> list[MaskedScopeRow]:
    sample_ids, _features, targets, valid = generate_shard(shard)
    return [
        MaskedScopeRow(
            sample_id=sample_id,
            shard=shard,
            row=row,
            target=float(target),
            valid=bool(mask),
        )
        for row, (sample_id, target, mask) in enumerate(
            zip(sample_ids, targets, valid, strict=True)
        )
    ]


def _deliverable_name(*, model_type: str, run_name: str, exp_id: str) -> str:
    from execute_tools.deliverable_spec import resolve_deliverable_naming

    return resolve_deliverable_naming().name(
        model_type=model_type,
        run_name=run_name,
        exp_id=exp_id,
        input_identity=0,
    )


def deliverable_name(request: DeliverableWriteRequest | EvaluationReadRequest) -> str:
    """Module-level naming adapter used by generic inference reporting."""
    return _deliverable_name(
        model_type=request.model_type,
        run_name=request.run_name,
        exp_id=request.exp_id,
    )


class SyntheticMaskedTaskDataPath:
    """Task-owned scope, dataset, and JSON deliverable codec."""

    task_data_path_id: ClassVar[str] = TASK_ID

    def __init__(
        self, train_shards: Sequence[int] = TRAIN_SHARDS, eval_shard: int = EVAL_SHARD
    ) -> None:
        self._train_shards = tuple(int(shard) for shard in train_shards)
        self._eval_shard = int(eval_shard)

    @staticmethod
    def _require_scope(scope: object) -> MaskedScope:
        if not isinstance(scope, MaskedScope):
            raise ValueError(
                f"synthetic masked regression needs MaskedScope, got {type(scope).__name__}."
            )
        return scope

    @staticmethod
    def _read_shard(data_dir: str, shard: int) -> dict[str, tuple[list[float], float, float]]:
        path = Path(data_dir) / shard_filename(shard)
        if not path.is_file():
            raise ValidationScopeError(f"synthetic masked regression shard not found: {path}")
        rows: dict[str, tuple[list[float], float, float]] = {}
        with path.open(encoding="utf-8", newline="") as handle:
            for record in csv.DictReader(handle):
                rows[record["sample_id"]] = (
                    [float(record[f"x{index}"]) for index in range(FEATURE_DIM)],
                    float(record["target"]),
                    float(record["valid"]),
                )
        return rows

    def _materialize(self, scope: object, data_dir: str) -> tuple[np.ndarray, np.ndarray]:
        checked = self._require_scope(scope)
        if not checked.rows:
            raise ValidationScopeError("synthetic masked regression scope cannot be empty.")
        loaded: dict[int, dict[str, tuple[list[float], float, float]]] = {}
        features: list[list[float]] = []
        supervision: list[list[float]] = []
        for row in checked.rows:
            if row.shard not in loaded:
                loaded[row.shard] = self._read_shard(data_dir, row.shard)
            found = loaded[row.shard].get(row.sample_id)
            if found is None:
                raise ValidationScopeError(
                    f"scope row {row.sample_id!r} is missing from its shard."
                )
            row_features, target, valid = found
            if not np.isclose(target, row.target, atol=1e-7) or bool(valid) != row.valid:
                raise ValidationScopeError(
                    f"scope supervision for {row.sample_id!r} disagrees with disk."
                )
            features.append(row_features)
            supervision.append([target, valid])
        return np.asarray(features, dtype=np.float32), np.asarray(supervision, dtype=np.float32)

    @staticmethod
    def _dataset(features: np.ndarray, supervision: np.ndarray) -> Dataset[Any]:
        import torch
        from torch.utils.data import TensorDataset

        return TensorDataset(
            torch.from_numpy(features.copy()), torch.from_numpy(supervision.copy())
        )

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset[Any]:
        rows = list(self._require_scope(scope).rows)
        if params.train_portion is not None and params.train_portion < 1.0:
            keep = max(1, math.floor(len(rows) * params.train_portion))
            rng = np.random.default_rng(params.epoch_seed)
            chosen = sorted(rng.choice(len(rows), keep, replace=False).tolist())
            rows = [rows[index] for index in chosen]
        if params.max_samples is not None:
            rows = rows[: params.max_samples]
        return self._dataset(*self._materialize(MaskedScope(rows=tuple(rows)), params.data_dir))

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset[Any]:
        return self._dataset(*self._materialize(scope, params.data_dir))

    @staticmethod
    def deliverable_name(*, model_type: str, run_name: str, exp_id: str) -> str:
        return _deliverable_name(model_type=model_type, run_name=run_name, exp_id=exp_id)

    def write_deliverable(self, outputs: Any, request: DeliverableWriteRequest) -> None:
        scope = self._require_scope(request.task_scope)
        predictions = list(outputs)
        if len(predictions) != len(scope.rows):
            raise ValueError(f"received {len(predictions)} predictions for {len(scope.rows)} rows.")
        if request.source_context is None:
            raise ValueError(
                "synthetic masked regression requires prediction-aligned source context."
            )
        dataset = self.validation_dataset(
            scope, EvalMaterializationParams(data_dir=request.source_context.data_dir)
        )
        if len(dataset) != request.source_context.sample_count:
            raise ValueError("rematerialized source count disagrees with generic inference.")
        payload: dict[str, dict[str, float | bool]] = {}
        for row, prediction, (_features, supervision) in zip(
            scope.rows, predictions, dataset, strict=True
        ):
            value = float(prediction.reshape(-1)[0].item())
            payload[row.sample_id] = {
                "prediction": value,
                "target": float(supervision[0].item()),
                "valid": bool(supervision[1].item()),
            }
        os.makedirs(request.output_dir, exist_ok=True)
        path = Path(request.output_dir) / self.deliverable_name(
            model_type=request.model_type, run_name=request.run_name, exp_id=request.exp_id
        )
        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        path = Path(request.deliverable_dir) / self.deliverable_name(
            model_type=request.model_type, run_name=request.run_name, exp_id=request.exp_id
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def _draw(
        self, shards: Sequence[int], request: ScopeBuildRequest
    ) -> tuple[MaskedScopeRow, ...]:
        if request.subset_ref is not None:
            raise ValueError("synthetic masked regression has no subset vocabulary.")
        rows = [row for shard in shards for row in _rows_for_shard(shard)]
        keep = max(1, math.floor(len(rows) * request.portion))
        if keep < len(rows):
            rng = np.random.default_rng(request.seed)
            rows = [rows[index] for index in sorted(rng.choice(len(rows), keep, replace=False))]
        if request.max_samples is not None:
            rows = rows[: request.max_samples]
        return tuple(rows)

    def build_training_scope(self, request: ScopeBuildRequest) -> object:
        if request.selection_strategy == "target":
            if not request.target_partitions:
                raise ValueError("target selection requires target_partitions.")
            illegal = set(request.target_partitions) - set(self._train_shards)
            if illegal:
                raise ValueError(f"evaluation shards cannot enter training: {sorted(illegal)}")
            shards = request.target_partitions
        else:
            shards = self._train_shards
        return MaskedScope(rows=self._draw(shards, request))

    def build_eval_scope(self, request: ScopeBuildRequest) -> object:
        return MaskedScope(rows=self._draw((self._eval_shard,), request))

    def serialize_scope(self, scope: object) -> str:
        checked = self._require_scope(scope)
        return json.dumps(
            {"kind": SCOPE_KIND, "rows": [row.model_dump() for row in checked.rows]},
            sort_keys=True,
            separators=(",", ":"),
        )

    def deserialize_scope(self, payload: str) -> object:
        return deserialize_rows_scope(payload, SCOPE_KIND, MaskedScopeRow, MaskedScope)


def materialize_run_bundle(out_dir: str | Path) -> dict[str, str]:
    data_dir = Path(out_dir).resolve() / "data"
    write_data_dir(data_dir)
    return {"data_dir": str(data_dir)}
