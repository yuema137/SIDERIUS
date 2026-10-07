"""Bind an explicitly transported task for standalone bounded probes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from execute_tools.task_data_path import TaskProbeDataSpec
    from workflows.task_composition import RunTaskComposition


@contextmanager
def bind_probe_task(reference: TaskProbeDataSpec | None) -> Iterator[RunTaskComposition]:
    """Verify the parent's declaration before model loading or data access."""
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    if reference is None:
        raise ValueError(
            "standalone probes require explicit task_probe_data; a data root is insufficient"
        )
    if (
        not Path(reference.manifest_path).is_absolute()
        or not Path(reference.sampling.data_dir).is_absolute()
    ):
        raise ValueError("standalone probe manifest_path and sampling.data_dir must be absolute")
    composition = compose_run_task_bindings(reference.manifest_path)
    if composition.semantic_fingerprint != reference.semantic_fingerprint:
        raise ValueError("standalone probe task composition fingerprint mismatch")
    if (
        composition.forward_contract.segmentation_applicability
        != reference.segmentation_applicability
    ):
        raise ValueError("standalone probe task segmentation applicability mismatch")
    with bind_run_task_composition(composition, physical_data_root=reference.sampling.data_dir):
        yield composition
