"""Projection of a composed attempt into the isolated VRAM probe worker."""

from __future__ import annotations

from typing import Any

from agent.skills.evaluate_vram_skill.isolated_probe import TaskProbeDataSpec
from execute_tools.task_data_path import (
    EpochSamplingParams,
    require_bound_task_data_path,
    resolve_max_inference_batch_size,
    resolve_task_scope_capability,
)
from workflows.task_composition import active_task_manifest_path


def build_task_probe_data(
    *,
    task_composition_ref: Any,
    task_scopes: Any,
    data_dir: str | None,
    epoch_seed: int | None,
    train_portion: float | None,
    max_samples: int | None,
) -> TaskProbeDataSpec | None:
    """Carry the run's resolved task scope to resource measurement.

    Un-composed and single-file attempts retain the legacy synthetic probe.
    A composed attempt with a task-owned training scope must carry every value
    needed for the isolated worker to materialize one batch through the same
    ``TaskDataPath.training_dataset`` contract used by formal training.
    """
    if task_composition_ref is None:
        return None
    training_scope = getattr(task_scopes, "training", None)
    if training_scope is None:
        return None
    if not data_dir:
        raise ValueError(
            "a composed training scope reached VRAM admission without a resolved data root"
        )
    manifest_path = active_task_manifest_path()
    if manifest_path is None:
        raise ValueError(
            "a composed training scope reached VRAM admission without its bound manifest path"
        )
    data_path = require_bound_task_data_path()
    capability = resolve_task_scope_capability(data_path)
    return TaskProbeDataSpec(
        manifest_path=manifest_path,
        semantic_fingerprint=task_composition_ref.semantic_fingerprint,
        training_scope_payload=capability.serialize_scope(training_scope),
        sampling=EpochSamplingParams(
            data_dir=data_dir,
            epoch_seed=epoch_seed,
            train_portion=train_portion,
            max_samples=max_samples,
        ),
        max_inference_batch_size=resolve_max_inference_batch_size(data_path),
    )
