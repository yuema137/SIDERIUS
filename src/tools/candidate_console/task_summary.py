"""Read-only Task-panel summary: console facts plus sandboxed package facts.

Package facts come only from the composition child (``observe_composition``);
task code never runs in the console process. The console adds its own
``TaskChoice`` run policy and a bounded, no-follow walk of ``data_root``.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import JsonValue

from agent.schemas.output_types import OutputTypeName
from execute_tools.health_checks.roster_projection import HealthRosterProjection
from tools.setup_review.composition_check import observe_composition
from tools.setup_review.composition_models import (
    CompositionJob,
    CompositionObservation,
    DataScopeFacts,
    SampleCountFacts,
    TaskCheckSettings,
    TaskSummaryRequest,
)
from tools.setup_review.composition_transport import manifest_digest
from tools.workflow_preview.models import PreviewModel
from workflows.definition import TaskBinding
from workflows.llm_config import parse_llm_config_bytes

from .models import TaskChoice

DATA_WALK_ENTRY_CAP = 100_000
SummaryState = Literal["observing", "ready", "failed", "unavailable"]
UnavailableReason = Literal[
    "sandbox_missing", "data_root_missing", "manifest_missing", "llm_config_unreadable"
]
_HINTS: dict[UnavailableReason, str] = {
    "sandbox_missing": "Install bubblewrap (bwrap) and enable user namespaces, then Refresh.",
    "data_root_missing": "Create the task's data folder or fix data_root in console.json; "
    "restart the console, then Refresh.",
    "manifest_missing": "Restore the task manifest or fix task_manifest in console.json; "
    "restart the console, then Refresh.",
    "llm_config_unreadable": "Fix llm_config_file in console.json so it names a readable "
    "model profile; restart the console, then Refresh.",
}


class Unavailable(PreviewModel):
    reason: UnavailableReason
    hint: str


class SummaryFailure(PreviewModel):
    stage: str
    message: str


class DataVolume(PreviewModel):
    """Regular files under ``data_root`` without following links; partial when capped."""

    files: int
    bytes: int
    complete: bool
    entry_cap: int


class RunPolicy(PreviewModel):
    """Console-owned TaskChoice policy; environment NAMES only, never values."""

    preparation_timeout_seconds: float
    candidate_timeout_seconds: float
    candidate_network: bool
    candidate_devices: tuple[str, ...]
    candidate_environment_names: tuple[str, ...]
    allowed_output_types: tuple[OutputTypeName, ...] | None


class MetricView(PreviewModel):
    metric_id: str
    direction: str
    aggregation: str


class LockedParameter(PreviewModel):
    path: str
    rule: Literal["exact", "range", "allowed", "predicate"]
    value: JsonValue


class PluginView(PreviewModel):
    configured_ref: str
    symbol: str
    roles: tuple[str, ...]


class PackageIdentity(PreviewModel):
    semantic_fingerprint: str
    task_data_path_id: str
    task_revision: TaskBinding | None
    revision_matches: bool | None


class PackageView(PreviewModel):
    identity: PackageIdentity
    description: str | None
    model_io: dict[str, JsonValue] | None
    partition_count: int | None
    main_score: MetricView
    observational_metrics: tuple[MetricView, ...]
    locked_parameters: tuple[LockedParameter, ...]
    objective: dict[str, JsonValue] | None
    objective_source: Literal["task", "planner_chooses"]
    deliverable: dict[str, JsonValue] | None
    health: HealthRosterProjection
    plugins: tuple[PluginView, ...]
    model_types: tuple[str, ...]
    scopes: DataScopeFacts
    sample_counts: SampleCountFacts | None


class TaskSummaryView(PreviewModel):
    schema_version: Literal["siderius.console-task-summary/v1"] = "siderius.console-task-summary/v1"
    task_id: str
    label: str
    state: SummaryState
    data_root: str
    run_policy: RunPolicy
    data_volume: DataVolume | None = None
    package: PackageView | None = None
    failure: SummaryFailure | None = None
    unavailable: Unavailable | None = None


class TaskListItem(PreviewModel):
    task_id: str
    label: str


class TaskListView(PreviewModel):
    tasks: tuple[TaskListItem, ...]


def walk_data_root(root: Path, cap: int = DATA_WALK_ENTRY_CAP) -> DataVolume:
    """Count regular files and bytes; symlinks are counted as entries, never followed.

    An unreadable entry or subdirectory, like the cap, makes the result incomplete.
    """
    files = size = entries = 0
    complete = True
    pending = [str(root)]
    while pending:
        try:
            with os.scandir(pending.pop()) as listing:
                for entry in listing:
                    entries += 1
                    if entries > cap:
                        return DataVolume(files=files, bytes=size, complete=False, entry_cap=cap)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        size += entry.stat(follow_symlinks=False).st_size
                        files += 1
        except OSError:
            complete = False
    return DataVolume(files=files, bytes=size, complete=complete, entry_cap=cap)


def _metric(spec: dict[str, JsonValue]) -> MetricView:
    return MetricView(
        metric_id=str(spec["id"]),
        direction=str(spec["direction"]),
        aggregation=str(spec["aggregation"]),
    )


def _locked(rules: dict[str, JsonValue]) -> tuple[LockedParameter, ...]:
    """Owner-dumped ParameterRules: each path carries exactly one non-null rule kind."""
    table = rules.get("rules")
    locked = []
    for path, rule in (table if isinstance(table, dict) else {}).items():
        if not isinstance(rule, dict):
            continue
        for kind in ("exact", "range", "allowed", "predicate"):
            if rule.get(kind) is not None:
                locked.append(LockedParameter(path=path, rule=kind, value=rule[kind]))
                break
    return tuple(locked)


def project_package(task: TaskChoice, observed: CompositionObservation) -> PackageView:
    """Project a passed observation; roles come from exact file identity, never names."""
    facts, package = observed.result.task, observed.result.package
    assert facts is not None and package is not None
    roles_by_path: dict[str, list[str]] = {}
    for role, path in package.implementation_sources.items():
        roles_by_path.setdefault(path, []).append(role)
    for plugin in package.model_plugins:
        roles_by_path.setdefault(plugin.path, []).append("model_plugin")
    for key, path in facts.source_paths.items():
        roles_by_path.setdefault(path, []).append(key)
    config = facts.task_config
    contract = config.get("forward_contract")
    description = config.get("task_description")
    partitions = facts.dataset_profile.get("partition_count")
    revision = task.task_revision
    return PackageView(
        identity=PackageIdentity(
            semantic_fingerprint=facts.semantic_fingerprint,
            task_data_path_id=facts.task_data_path_id,
            task_revision=revision,
            revision_matches=None
            if revision is None
            else revision.semantic_fingerprint == facts.semantic_fingerprint
            and revision.task_data_path_id == facts.task_data_path_id,
        ),
        description=description if isinstance(description, str) else None,
        model_io=contract if isinstance(contract, dict) else None,
        partition_count=partitions if isinstance(partitions, int) else None,
        main_score=_metric(facts.primary_metric),
        observational_metrics=tuple(_metric(spec) for spec in facts.secondary_metrics),
        locked_parameters=_locked(facts.parameter_rules),
        objective=package.objective,
        objective_source="planner_chooses" if package.objective is None else "task",
        deliverable=package.deliverable,
        health=package.health,
        plugins=tuple(
            PluginView(
                configured_ref=str(plugin.identity.get("configured_ref", "")),
                symbol=str(plugin.identity.get("symbol", "")),
                roles=tuple(roles_by_path.get(plugin.path, ("unrecorded",))),
            )
            for plugin in facts.plugins
        ),
        model_types=tuple(plugin.model_type for plugin in package.model_plugins),
        scopes=package.scopes,
        sample_counts=package.sample_counts,
    )


Observer = Callable[[CompositionJob, TaskChoice], CompositionObservation]
Starter = Callable[[Callable[[], None]], None]


def observe(job: CompositionJob, task: TaskChoice) -> CompositionObservation:
    """The existing bounded child under the task's own preparation root."""
    scratch = str(Path(task.preparation_root) / str(uuid4()))
    return observe_composition(
        job.model_copy(update={"scratch": scratch}),
        tuple(Path(path) for path in task.task_read_only),
        data_root=Path(task.data_root),
    )


def _start_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="task-summary", daemon=True).start()


@dataclass
class _Entry:
    state: SummaryState
    volume: DataVolume | None = None
    package: PackageView | None = None
    failure: SummaryFailure | None = None
    unavailable: Unavailable | None = None


class TaskSummaries:
    """In-memory cache keyed by (task_id, manifest sha256, scratch-free job digest)."""

    def __init__(
        self,
        tasks: tuple[TaskChoice, ...],
        observer: Observer | None = None,
        start: Starter | None = None,
        entry_cap: int = DATA_WALK_ENTRY_CAP,
    ) -> None:
        self._tasks = {task.task_id: task for task in tasks}
        self._observer = observer or observe
        self._start = start or _start_thread
        self._cap = entry_cap
        self._entries: dict[tuple[str, str, str], _Entry] = {}
        self._lock = threading.Lock()

    def list_view(self) -> TaskListView:
        return TaskListView(
            tasks=tuple(
                TaskListItem(task_id=task.task_id, label=task.label)
                for task in self._tasks.values()
            )
        )

    def _view(self, task: TaskChoice, entry: _Entry) -> TaskSummaryView:
        return TaskSummaryView(
            task_id=task.task_id,
            label=task.label,
            state=entry.state,
            data_root=task.data_root,
            run_policy=RunPolicy(
                preparation_timeout_seconds=task.preparation_timeout_seconds,
                candidate_timeout_seconds=task.candidate_timeout_seconds,
                candidate_network=task.candidate_network,
                candidate_devices=task.candidate_devices,
                candidate_environment_names=task.candidate_environment_names,
                allowed_output_types=task.allowed_output_types,
            ),
            data_volume=entry.volume,
            package=entry.package,
            failure=entry.failure,
            unavailable=entry.unavailable,
        )

    def _job(self, task: TaskChoice, count_samples: bool) -> CompositionJob | Unavailable:
        if not Path(task.data_root).is_dir():
            return Unavailable(reason="data_root_missing", hint=_HINTS["data_root_missing"])
        try:
            digest = manifest_digest(task.task_manifest)
        except (OSError, ValueError):
            return Unavailable(reason="manifest_missing", hint=_HINTS["manifest_missing"])
        try:
            config = parse_llm_config_bytes(Path(task.llm_config_file).read_bytes())
            strategy = config.get("tune").get("planner_strategy")
        except (OSError, ValueError):
            return Unavailable(reason="llm_config_unreadable", hint=_HINTS["llm_config_unreadable"])
        return CompositionJob(
            manifest=task.task_manifest,
            manifest_sha256=digest,
            planner_strategy=strategy,
            scratch="",
            settings=TaskCheckSettings(timeout_seconds=task.preparation_timeout_seconds),
            summary=TaskSummaryRequest(data_root=task.data_root, count_samples=count_samples),
        )

    def _run(self, key: tuple[str, str, str], job: CompositionJob, task: TaskChoice) -> None:
        entry = _Entry(state="failed")
        try:
            entry.volume = walk_data_root(Path(task.data_root), self._cap)
            observed = self._observer(job, task)
            failure = observed.result.failure
            if failure is None:
                entry.state, entry.package = "ready", project_package(task, observed)
            elif failure.stage == "sandbox" and failure.exception_type == "SandboxUnavailable":
                entry.state = "unavailable"
                entry.unavailable = Unavailable(
                    reason="sandbox_missing", hint=_HINTS["sandbox_missing"]
                )
            else:
                entry.failure = SummaryFailure(stage=failure.stage, message=failure.message)
        except Exception as error:
            entry.failure = SummaryFailure(
                stage="console", message=f"{type(error).__name__}: {error}"
            )
        with self._lock:
            self._entries[key] = entry

    def summary(
        self, task_id: str, *, refresh: bool = False, count_samples: bool = False
    ) -> TaskSummaryView | None:
        """``None`` for an unknown task; otherwise the cached or a newly started observation."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        job = self._job(task, count_samples)
        if isinstance(job, Unavailable):
            return self._view(task, _Entry(state="unavailable", unavailable=job))
        key = (task_id, job.manifest_sha256, job.digest)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or (refresh and entry.state != "observing"):
                # A changed manifest yields a new key; drop this task's stale entries.
                for old in [k for k in self._entries if k[0] == task_id and k[1] != key[1]]:
                    del self._entries[old]
                entry = self._entries[key] = _Entry(state="observing")
                start = True
            else:
                start = False
        if start:
            self._start(lambda: self._run(key, job, task))
        with self._lock:
            return self._view(task, self._entries[key])
