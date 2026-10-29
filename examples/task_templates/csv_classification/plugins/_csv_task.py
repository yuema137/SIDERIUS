"""Task data path for a tabular classification task stored as CSV files.

The manifest (``task.yaml``) binds this class through
``task_data_path: {file: plugins/_csv_task.py, symbol: CsvClassificationTaskDataPath}``
and passes its ``config:`` mapping to the constructor. Edit that mapping, not
this file, to describe your CSV columns and class labels.

Data layout. The run's data folder (``siderius_workspace/data/<task_id>/`` in
the console, ``--data_dir`` on the CLI) holds two CSV files with a header row:
a training file and a validation file. The validation file is the
evaluation split the research loop scores on. Keep your final test file
outside the data folder; nothing in this package reads it.

Where the data folder is visible. Scope builders (``build_training_scope`` /
``build_eval_scope``) receive a ``ScopeBuildRequest``, which carries no data
folder. A scope built here therefore records only *how* to select rows:
which file, which fraction and which seed. The rows themselves are resolved
when a stage that does receive the data folder reads the file:
``training_dataset`` / ``validation_dataset`` (``params.data_dir``),
``write_deliverable`` (``request.source_context.data_dir``) and the metric
(``data_dir``). All of them use :meth:`CsvClassificationTaskDataPath._select`,
so every stage sees the same rows in the same order.
"""

from __future__ import annotations

import csv
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from core.seeding import MissingRunSeed
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    HealthCoverageRequest,
    HealthCoverageResult,
    ScopeBuildRequest,
    StorageReadScope,
    TaskOutputArtifactInventory,
    ValidationScopeError,
)

if TYPE_CHECKING:
    from torch.utils.data import Dataset

#: EDIT HERE (optional): a short identifier for your task's data path. It is
#: recorded in run identity; two different tasks loaded in one process must
#: not share it.
TASK_DATA_PATH_ID = "csv_classification"

#: Partition indices, as declared in ``declared/dataset_profile.json``.
TRAINING_PARTITION = 0
VALIDATION_PARTITION = 1

SCOPE_KIND = "csv_classification_rows"


class CsvRowSelection(BaseModel):
    """A scope: which CSV file to read and how to sample its rows.

    ``seed`` is always concrete, so every later stage resolves the identical
    row subset. A sampled scope (``portion < 1`` or a ``max_samples``
    ceiling) takes the framework's ``request.seed``; the builder refuses a
    sampled request without one rather than inventing a seed. An unsampled
    scope reads every row and stores ``seed=0``, which no stage uses.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["csv_classification_rows"] = SCOPE_KIND
    file: str = Field(min_length=1)
    portion: float = Field(gt=0.0, le=1.0)
    seed: int
    max_samples: int | None = Field(default=None, ge=1)


@dataclass(frozen=True)
class CsvTable:
    """One parsed CSV file: sample IDs, features and class indices, row-aligned."""

    sample_ids: tuple[str, ...]
    features: np.ndarray  # float32 [rows, feature_count]
    labels: np.ndarray  # int64 [rows]


class CsvClassificationTaskDataPath:
    """Reads labelled CSV rows and writes ``{sample_id: predicted_class}`` JSON.

    Constructor arguments come from ``task.yaml`` ``task_data_path.config``.
    Every argument is validated here, so a wrong column name or class list
    fails when the package is composed or the first file is read, with a
    message naming the value to fix.
    """

    task_data_path_id: ClassVar[str] = TASK_DATA_PATH_ID

    def __init__(
        self,
        *,
        train_file: str,
        validation_file: str,
        label_column: str,
        classes: Sequence[Any],
        feature_count: int,
        id_column: str | None = None,
        feature_columns: Sequence[str] | None = None,
    ) -> None:
        for name, value in (("train_file", train_file), ("validation_file", validation_file)):
            if not value or os.path.isabs(value) or os.path.normpath(value).startswith(".."):
                raise ValueError(
                    f"{name} must be a file name inside the data folder; got {value!r}"
                )
        if train_file == validation_file:
            raise ValueError("train_file and validation_file must be different files")
        self._train_file = train_file
        self._validation_file = validation_file
        self._label_column = label_column
        self._id_column = id_column
        # Labels are compared as text, so `classes: [0, 1]` matches a CSV `0`.
        self._classes = tuple(str(value) for value in classes)
        if len(self._classes) < 2 or len(set(self._classes)) != len(self._classes):
            raise ValueError(f"classes must list at least two distinct labels; got {classes!r}")
        self._class_index = {label: index for index, label in enumerate(self._classes)}
        if feature_count < 1:
            raise ValueError(f"feature_count must be positive; got {feature_count}")
        self._feature_count = int(feature_count)
        self._feature_columns = None if feature_columns is None else tuple(feature_columns)
        if self._feature_columns is not None and len(self._feature_columns) != feature_count:
            raise ValueError(
                f"feature_columns names {len(self._feature_columns)} columns but "
                f"feature_count is {feature_count}"
            )

    @property
    def class_count(self) -> int:
        return len(self._classes)

    # -- reading the CSV files -------------------------------------------------

    def read_table(self, data_dir: str, file: str) -> CsvTable:
        """Parse one CSV file, refusing missing values, unknown labels and duplicates."""
        path = os.path.join(data_dir, file)
        if not os.path.isfile(path):
            raise ValidationScopeError(f"CSV file not found in the data folder: {path}")
        with open(path, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            columns = self._feature_columns_for(header, path)
            ids: list[str] = []
            features: list[list[float]] = []
            labels: list[int] = []
            for line, record in enumerate(reader, start=2):
                label = (record.get(self._label_column) or "").strip()
                if label not in self._class_index:
                    raise ValueError(
                        f"{path} line {line}: label {label!r} is not one of classes "
                        f"{list(self._classes)}"
                    )
                try:
                    values = [float(record[column]) for column in columns]
                except (TypeError, ValueError) as error:
                    raise ValueError(f"{path} line {line}: non-numeric feature ({error})") from None
                if not all(math.isfinite(value) for value in values):
                    raise ValueError(f"{path} line {line}: a feature is NaN or infinite")
                sample_id = (
                    f"row{line - 2:06d}"
                    if self._id_column is None
                    else (record.get(self._id_column) or "").strip()
                )
                if not sample_id:
                    raise ValueError(f"{path} line {line}: empty {self._id_column!r}")
                ids.append(sample_id)
                features.append(values)
                labels.append(self._class_index[label])
        if not ids:
            raise ValueError(f"{path} has a header but no rows")
        if len(set(ids)) != len(ids):
            raise ValueError(f"{path} repeats a value in the ID column {self._id_column!r}")
        return CsvTable(
            sample_ids=tuple(ids),
            features=np.asarray(features, dtype=np.float32),
            labels=np.asarray(labels, dtype=np.int64),
        )

    def _feature_columns_for(self, header: tuple[str, ...], path: str) -> tuple[str, ...]:
        required = [self._label_column] + ([self._id_column] if self._id_column else [])
        missing = [column for column in required if column not in header]
        if missing:
            raise ValueError(f"{path} has no column(s) {missing}; its header is {list(header)}")
        if self._feature_columns is not None:
            absent = [column for column in self._feature_columns if column not in header]
            if absent:
                raise ValueError(f"{path} has no feature column(s) {absent}")
            return self._feature_columns
        columns = tuple(column for column in header if column not in required)
        if len(columns) != self._feature_count:
            raise ValueError(
                f"{path} has {len(columns)} feature columns {list(columns)}, but "
                f"feature_count is {self._feature_count}"
            )
        return columns

    @staticmethod
    def _subsample(
        count: int, portion: float | None, max_samples: int | None, seed: int | None
    ) -> list[int]:
        """Indices ``0..count-1`` kept by a portion and a ceiling, in file order.

        The kept rows are a seeded random subset, never the first rows of the
        file, so a ceiling on a label-sorted CSV still sees every class.
        """
        keep = count
        if portion is not None and portion < 1.0:
            keep = max(1, math.floor(count * portion))
        if max_samples is not None:
            keep = min(keep, max_samples)
        if keep >= count:
            return list(range(count))
        if seed is None:
            raise MissingRunSeed("subsampling CSV rows needs a seed; none was supplied")
        drawn = np.random.default_rng(seed).permutation(count)[:keep]
        return sorted(int(index) for index in drawn)

    def _select(self, row_count: int, scope: CsvRowSelection) -> list[int]:
        """Row positions a scope selects; the single sampling rule every stage uses."""
        return self._subsample(row_count, scope.portion, scope.max_samples, scope.seed)

    def _rows(self, scope: object, data_dir: str) -> tuple[CsvTable, list[int]]:
        selection = self._require_scope(scope)
        table = self.read_table(data_dir, selection.file)
        return table, self._select(len(table.sample_ids), selection)

    def labels_by_sample_id(self, scope: object, data_dir: str) -> dict[str, int]:
        """Ground-truth class index per selected sample; the metric's truth source."""
        table, positions = self._rows(scope, data_dir)
        return {table.sample_ids[p]: int(table.labels[p]) for p in positions}

    # -- datasets ----------------------------------------------------------------

    @staticmethod
    def _dataset(features: np.ndarray, labels: np.ndarray) -> Dataset[Any]:
        import torch
        from torch.utils.data import TensorDataset

        return TensorDataset(torch.from_numpy(features.copy()), torch.from_numpy(labels.copy()))

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset[Any]:
        table, positions = self._rows(scope, params.data_dir)
        kept = self._subsample(
            len(positions), params.train_portion, params.max_samples, params.epoch_seed
        )
        positions = [positions[index] for index in kept]
        return self._dataset(table.features[positions], table.labels[positions])

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset[Any]:
        table, positions = self._rows(scope, params.data_dir)
        return self._dataset(table.features[positions], table.labels[positions])

    # -- deliverable: {sample_id: predicted class index} as one JSON file --------

    @staticmethod
    def deliverable_name(*, model_type: str, run_name: str, exp_id: str) -> str:
        """The file name from the manifest's ``deliverable:`` section."""
        return _deliverable_name(model_type=model_type, run_name=run_name, exp_id=exp_id)

    def write_deliverable(self, outputs: Any, request: DeliverableWriteRequest) -> None:
        """Pair each output with its sample ID and write the predicted classes.

        Generic inference passes one output per validation row, in
        ``validation_dataset`` order, plus the scope and the data folder in
        ``request.source_context``. A ready ``{sample_id: class}`` mapping is
        also accepted.
        """
        if isinstance(outputs, Mapping):
            predictions = {str(key): self._class_of(value) for key, value in outputs.items()}
        else:
            if request.task_scope is None or request.source_context is None:
                raise ValueError(
                    "positional outputs need request.task_scope and request.source_context"
                )
            table, positions = self._rows(request.task_scope, request.source_context.data_dir)
            sequence = list(outputs)
            if len(sequence) != len(positions) or len(positions) != (
                request.source_context.sample_count
            ):
                raise ValueError(
                    f"{len(sequence)} outputs for {len(positions)} validation rows "
                    f"(inference reported {request.source_context.sample_count}); refusing to pair"
                )
            predictions = {
                table.sample_ids[p]: self._class_of(output)
                for p, output in zip(positions, sequence, strict=True)
            }
        os.makedirs(request.output_dir, exist_ok=True)
        name = self.deliverable_name(
            model_type=request.model_type, run_name=request.run_name, exp_id=request.exp_id
        )
        with open(os.path.join(request.output_dir, name), "w", encoding="utf-8") as handle:
            json.dump(predictions, handle, sort_keys=True, indent=2)

    def _class_of(self, prediction: object) -> int:
        """A class index from model logits (argmax) or an already chosen index."""
        import torch

        if isinstance(prediction, torch.Tensor) and prediction.ndim >= 1:
            index = int(torch.argmax(prediction).item())
        elif isinstance(prediction, (int, np.integer)) and not isinstance(prediction, bool):
            index = int(prediction)
        else:
            raise ValueError(f"cannot read a class index from {type(prediction).__name__}")
        if not 0 <= index < self.class_count:
            raise ValueError(f"predicted class {index} is outside [0, {self.class_count})")
        return index

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        """Decode the deliverable back into ``{sample_id: class index}``."""
        name = self.deliverable_name(
            model_type=request.model_type, run_name=request.run_name, exp_id=request.exp_id
        )
        path = os.path.join(request.deliverable_dir, name)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"prediction file not found: {path}")
        with open(path, encoding="utf-8") as handle:
            decoded = json.load(handle)
        if not isinstance(decoded, dict):
            raise ValueError(f"{path} must hold a JSON object")
        return {str(key): int(value) for key, value in decoded.items()}

    def enumerate_output_artifacts(
        self, request: EvaluationReadRequest
    ) -> TaskOutputArtifactInventory:
        name = self.deliverable_name(
            model_type=request.model_type, run_name=request.run_name, exp_id=request.exp_id
        )
        path = Path(request.deliverable_dir) / name
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
            relative_paths=(name,) if path.exists() or path.is_symlink() else (),
        )

    # -- scopes ------------------------------------------------------------------

    def _require_scope(self, scope: object) -> CsvRowSelection:
        if not isinstance(scope, CsvRowSelection):
            raise ValueError(f"expected a CsvRowSelection scope, got {type(scope).__name__}")
        return scope

    def _selection(self, file: str, request: ScopeBuildRequest) -> CsvRowSelection:
        if request.subset_ref is not None:
            raise ValueError(f"{TASK_DATA_PATH_ID} has no data subsets; got {request.subset_ref!r}")
        seed = request.seed
        if seed is None:
            if request.portion < 1.0 or request.max_samples is not None:
                raise MissingRunSeed(
                    "a sampled CSV scope (portion < 1 or max_samples) requires request.seed"
                )
            seed = 0  # every row is read; the seed is never used
        return CsvRowSelection(
            file=file, portion=request.portion, seed=seed, max_samples=request.max_samples
        )

    def build_training_scope(self, request: ScopeBuildRequest) -> object:
        if request.selection_strategy == "target" and tuple(request.target_partitions) != (
            TRAINING_PARTITION,
        ):
            raise ValueError(
                f"the only training partition is {TRAINING_PARTITION}; "
                f"got target partitions {list(request.target_partitions)}"
            )
        return self._selection(self._train_file, request)

    def build_eval_scope(self, request: ScopeBuildRequest) -> object:
        return self._selection(self._validation_file, request)

    def serialize_scope(self, scope: object) -> str:
        return json.dumps(
            self._require_scope(scope).model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )

    def deserialize_scope(self, payload: str) -> object:
        return CsvRowSelection.model_validate_json(payload)

    # -- optional capabilities the console and Health use --------------------------

    def storage_read_scope(self, data_dir: str, scope: object) -> StorageReadScope:
        """The one CSV file a scope reads, for the Task tab's data volume."""
        path = os.path.abspath(os.path.join(data_dir, self._require_scope(scope).file))
        return StorageReadScope(file_paths=(path,), expected_on_disk_bytes=os.path.getsize(path))

    def validate_health_coverage(self, request: HealthCoverageRequest) -> HealthCoverageResult:
        """Health reads the predictions for the validation file; confirm the scope is it."""
        scope = self._require_scope(request.evaluation_scope)
        override = request.health_gate_files
        if override is not None and tuple(override) != (VALIDATION_PARTITION,):
            reason = (
                f"Health reads only partition {VALIDATION_PARTITION} (the validation "
                f"file); a health_gate_files override of {list(override)} is not supported"
            )
            covered = False
        elif scope.file != self._validation_file:
            reason = f"evaluation scope reads {scope.file}, not {self._validation_file}"
            covered = False
        else:
            reason = f"Health checks read the predictions for {scope.file}"
            covered = True
        return HealthCoverageResult(applicable=True, covered=covered, reason=reason)


def _deliverable_name(*, model_type: str, run_name: str, exp_id: str) -> str:
    from execute_tools.deliverable_spec import resolve_deliverable_naming

    return resolve_deliverable_naming().name(
        model_type=model_type, run_name=run_name, exp_id=exp_id, input_identity=0
    )


def deliverable_name(request: DeliverableWriteRequest | EvaluationReadRequest) -> str:
    """Module-level form of the deliverable name, used by inference reporting."""
    return _deliverable_name(
        model_type=request.model_type, run_name=request.run_name, exp_id=request.exp_id
    )
