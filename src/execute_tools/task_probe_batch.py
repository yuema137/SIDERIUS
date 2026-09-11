"""Materialize one bounded batch through a composed task's public contract."""

from __future__ import annotations

from typing import Any

from torch.utils.data import DataLoader

from execute_tools.task_data_path import TaskProbeDataSpec, resolve_task_scope_capability
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings


def load_task_probe_batch(
    reference: TaskProbeDataSpec | dict[str, Any], batch_size: int
) -> tuple[Any, Any]:
    """Return one full task-semantic training batch, failing closed."""
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
        dataset = composition.task_data_path.training_dataset(scope, ref.sampling)
        try:
            return next(
                iter(
                    DataLoader(
                        dataset,
                        batch_size=batch_size,
                        shuffle=False,
                        drop_last=True,
                    )
                )
            )
        except StopIteration as exc:
            raise ValueError(
                "the task-owned training scope cannot produce one full resource "
                f"probe batch of size {batch_size}"
            ) from exc
