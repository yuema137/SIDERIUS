"""Child-only Task-panel facts read from the composition's own owners.

Imported only inside the sandboxed composition child: building scopes, reading
storage volume and counting samples execute task code.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.health_checks.roster_projection import project_health_roster
from execute_tools.task_data_path import (
    EpochSamplingParams,
    EvalMaterializationParams,
    build_full_declared_split,
    declares_scope_capability,
    resolve_storage_read_scope,
)
from tools.setup_review.composition_models import (
    FAILURE_MESSAGE_MAX_CHARS,
    DataScopeFacts,
    ModelPluginFact,
    SampleCountFacts,
    ScopeVolume,
    TaskPackageFacts,
    TaskSummaryRequest,
)

if TYPE_CHECKING:
    from workflows.task_composition import RunTaskComposition


#: The task's full declared split: every row of each leg, before any run-level
#: sampling (a run's formal/trial portions and seeds select a subset of this).
FULL_PORTION = 1.0
BASIS = (
    "full task split, before any run-level sampling: snapshot strategy, training "
    "and evaluation portion 1.0, no sampling seed and no planner-chosen task parameters"
)


def _volume(impl: object, data_root: str, scope: object) -> ScopeVolume | None:
    read = resolve_storage_read_scope(impl, data_root, scope)
    if read is None:
        return None
    return ScopeVolume(
        file_count=len(read.file_paths), expected_on_disk_bytes=read.expected_on_disk_bytes
    )


def _message(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:FAILURE_MESSAGE_MAX_CHARS]


def _counts(impl: Any, data_root: str, training: object, evaluation: object) -> SampleCountFacts:
    try:
        train = impl.training_dataset(
            training,
            EpochSamplingParams(data_dir=data_root, train_portion=FULL_PORTION),
        )
        valid = impl.validation_dataset(evaluation, EvalMaterializationParams(data_dir=data_root))
        if not (hasattr(train, "__len__") and hasattr(valid, "__len__")):
            return SampleCountFacts(
                state="not_countable", message="the task's datasets do not report a length"
            )
        return SampleCountFacts(state="counted", training=len(train), evaluation=len(valid))
    except Exception as error:
        return SampleCountFacts(state="failed", message=_message(error))


def _scope_facts(
    composition: RunTaskComposition, request: TaskSummaryRequest
) -> tuple[DataScopeFacts, SampleCountFacts | None]:
    impl = composition.task_data_path
    basis = BASIS
    if not declares_scope_capability(impl):
        absent = "this task does not build its own scopes"
        counts = SampleCountFacts(state="not_countable", message=absent)
        return DataScopeFacts(state="not_declared", basis=basis, message=absent), (
            counts if request.count_samples else None
        )
    try:
        # A task may read its bound dataset profile while building scopes.
        with bind_dataset_profile(composition.dataset_profile):
            training, evaluation = build_full_declared_split(composition.task_data_path)
    except Exception as error:
        failed = DataScopeFacts(state="failed", basis=basis, message=_message(error))
        counts = SampleCountFacts(state="failed", message=_message(error))
        return failed, counts if request.count_samples else None
    counts = (
        _counts(impl, request.data_root, training, evaluation) if request.count_samples else None
    )
    if not callable(getattr(impl, "storage_read_scope", None)):
        return DataScopeFacts(
            state="not_declared", basis=basis, message="not declared by this task"
        ), counts
    try:
        return DataScopeFacts(
            state="declared",
            basis=basis,
            training=_volume(impl, request.data_root, training),
            evaluation=_volume(impl, request.data_root, evaluation),
        ), counts
    except Exception as error:
        return DataScopeFacts(state="failed", basis=basis, message=_message(error)), counts


def _implementation_sources(composition: RunTaskComposition) -> dict[str, str]:
    """Source files of the resolved task data path and metric implementations."""
    resolved = {
        "task_data_path": composition.task_data_path,
        "primary_metric": composition.metric,
        **{
            f"secondary_metric[{index}]": metric
            for index, metric in enumerate(composition.secondary_metrics)
        },
    }
    sources = {}
    for role, implementation in resolved.items():
        try:
            path = inspect.getsourcefile(type(implementation))
        except TypeError:
            path = None
        if path is not None:
            sources[role] = path
    return sources


def project_package_facts(
    composition: RunTaskComposition, request: TaskSummaryRequest
) -> TaskPackageFacts:
    """Each fact comes from its owner's resolved object; nothing is inferred from names."""
    scopes, counts = _scope_facts(composition, request)
    plugins = composition.model_plugins
    return TaskPackageFacts(
        health=project_health_roster(composition.task_health_binding),
        objective=None
        if composition.objective is None
        else composition.objective.model_dump(mode="json"),
        deliverable=None
        if composition.deliverable_naming is None
        else composition.deliverable_naming.model_dump(mode="json"),
        model_plugins=()
        if plugins is None
        else tuple(
            ModelPluginFact(
                model_type=plugin.model_type,
                path=plugin.absolute_path,
                content_sha256=plugin.content_sha256,
            )
            for plugin in plugins.plugins
        ),
        implementation_sources=_implementation_sources(composition),
        scopes=scopes,
        sample_counts=counts,
    )
