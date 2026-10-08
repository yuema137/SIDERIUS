"""Materialize one bounded batch through a composed task's public contract."""

from __future__ import annotations

from collections.abc import Iterator, Sized
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from torch.utils.data import DataLoader, Subset

from execute_tools.task_data_path import (
    EpochSamplingParams,
    EvalMaterializationParams,
    TaskDataPath,
    TaskProbeDataSpec,
    resolve_max_inference_batch_size,
    resolve_task_scope_capability,
)
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings


@dataclass(frozen=True)
class InferenceProbeBatches:
    """A bounded view, without eagerly copying the evaluation dataset."""

    loader: DataLoader
    dataset_samples: int
    selected_samples: int
    selected_batches: int


@contextmanager
def task_inference_probe_batches(
    reference: TaskProbeDataSpec, *, batch_size: int, max_batches: int
) -> Iterator[InferenceProbeBatches]:
    """Materialize real evaluation batches under the same task binding.

    The limit bounds how many examples the loader reads, not the dataset's
    total size. The dataset's own construction remains under the worker's
    host-memory and deadline limits. Tail batches are neither dropped nor
    padded, matching production task inference.
    """
    ref = TaskProbeDataSpec.model_validate(reference)
    if batch_size < 1 or max_batches < 1:
        raise ValueError("Inference probe batch size and batch limit must be positive")
    if ref.evaluation_scope_payload is None:
        raise ValueError("Inference measurement requires an explicit evaluation scope")
    composition = compose_run_task_bindings(ref.manifest_path)
    if composition.semantic_fingerprint != ref.semantic_fingerprint:
        raise ValueError("Inference measurement task composition fingerprint mismatch")
    with bind_run_task_composition(composition, physical_data_root=ref.sampling.data_dir):
        ceiling = resolve_max_inference_batch_size(composition.task_data_path)
        if ceiling != ref.max_inference_batch_size:
            raise ValueError("Inference measurement task batch ceiling changed after dispatch")
        if ceiling is not None and batch_size > ceiling:
            raise ValueError("Inference measurement exceeds the task batch ceiling")
        capability = resolve_task_scope_capability(composition.task_data_path)
        scope = capability.deserialize_scope(ref.evaluation_scope_payload)
        dataset = composition.task_data_path.validation_dataset(
            scope, EvalMaterializationParams(data_dir=ref.sampling.data_dir)
        )
        if not isinstance(dataset, Sized) or len(dataset) == 0:
            raise ValueError("Inference measurement needs a nonempty sized evaluation dataset")
        count = min(len(dataset), batch_size * max_batches)
        yield InferenceProbeBatches(
            loader=DataLoader(
                Subset(dataset, range(count)),
                batch_size=batch_size,
                shuffle=False,
                drop_last=False,
            ),
            dataset_samples=len(dataset),
            selected_samples=count,
            selected_batches=(count + batch_size - 1) // batch_size,
        )


@dataclass(frozen=True)
class TrainingProbeSource:
    """Authorized values valid only inside task_training_probe_source's context."""

    data_path: TaskDataPath
    scope: object
    sampling: EpochSamplingParams

    def first_batch(self, batch_size: int, *, drop_last: bool) -> tuple[Any, Any]:
        dataset = self.data_path.training_dataset(self.scope, self.sampling)
        return _first_training_batch(dataset, batch_size, drop_last=drop_last)


@contextmanager
def task_training_probe_source(
    reference: TaskProbeDataSpec | dict[str, Any],
) -> Iterator[TrainingProbeSource]:
    """Keep task authorization active throughout fitting and batch materialization."""
    ref = TaskProbeDataSpec.model_validate(reference)
    composition = compose_run_task_bindings(ref.manifest_path)
    if composition.semantic_fingerprint != ref.semantic_fingerprint:
        raise ValueError(
            "task probe composition fingerprint mismatch: "
            f"expected {ref.semantic_fingerprint}, resolved "
            f"{composition.semantic_fingerprint}"
        )
    with bind_run_task_composition(composition, physical_data_root=ref.sampling.data_dir):
        capability = resolve_task_scope_capability(composition.task_data_path)
        scope = capability.deserialize_scope(ref.training_scope_payload)
        yield TrainingProbeSource(composition.task_data_path, scope, ref.sampling)


def _first_training_batch(dataset: Any, batch_size: int, *, drop_last: bool) -> tuple[Any, Any]:
    try:
        return next(
            iter(DataLoader(dataset, batch_size=batch_size, shuffle=False, drop_last=drop_last))
        )
    except StopIteration as exc:
        if not drop_last:
            raise ValueError("the task-owned training scope contains no training samples") from exc
        raise ValueError(
            "the task-owned training scope cannot produce one full resource "
            f"probe batch of size {batch_size}"
        ) from exc


def load_task_probe_batch(
    reference: TaskProbeDataSpec | dict[str, Any], batch_size: int, *, drop_last: bool = True
) -> tuple[Any, Any]:
    """Return one real training batch under the resolved tail policy."""
    with task_training_probe_source(reference) as source:
        return source.first_batch(batch_size, drop_last=drop_last)


def load_task_inference_probe_input(reference: TaskProbeDataSpec | dict[str, Any]) -> Any:
    """Read one validation input before training; never use training as a substitute.

    Older callers without evaluation transport return an explicit absence.
    A present but invalid/empty scope fails before resource measurement.
    """
    ref = TaskProbeDataSpec.model_validate(reference)
    if ref.evaluation_scope_payload is None:
        return None
    composition = compose_run_task_bindings(ref.manifest_path)
    if composition.semantic_fingerprint != ref.semantic_fingerprint:
        raise ValueError("inference preflight task composition fingerprint mismatch")
    with bind_run_task_composition(composition, physical_data_root=ref.sampling.data_dir):
        capability = resolve_task_scope_capability(composition.task_data_path)
        scope = capability.deserialize_scope(ref.evaluation_scope_payload)
        dataset = composition.task_data_path.validation_dataset(
            scope, EvalMaterializationParams(data_dir=ref.sampling.data_dir)
        )
        try:
            batch = next(iter(DataLoader(dataset, batch_size=1, shuffle=False, drop_last=False)))
        except StopIteration as exc:
            raise ValueError("inference preflight evaluation scope contains no samples") from exc
        return batch[0] if isinstance(batch, (list, tuple)) else batch
