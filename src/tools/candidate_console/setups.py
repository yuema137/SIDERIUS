"""Experiment setups: one workflow project bound to one task, listed through one registry.

Two sources feed ``SetupRegistry``:

* legacy ``console.json`` ``editor_projects`` (+ ``runnable_editor_projects``), whose
  task is resolved from the saved source: its resolved manifest and data root must
  equal exactly one configured task's, else the setup has no matching task;
* console-created entries in ``<workspace>/settings/experiment_setups.json``
  (``siderius.console-experiment-setups/v1``, mode 0600), each bound to its
  ``task_id``. Paths are derived, never stored: ``projects/<setup_id>/workflow.py``
  and the 0700 recovery directory ``projects/<setup_id>/.recovery``.

``SetupStore`` is the only writer of the registry file: compare-and-swap on the
sha256 of the bytes it last read or wrote, then the global-settings private
publish (``settings_service._publish_private``). An ID present in both sources
fails startup. Creation is allowed only when console.json sets
``experiment_setups.browser_creatable``; it never overwrites or deletes, and a
failure after files were created names what was left in place.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from tools.candidate_operations.models import OperationFailure
from tools.workflow_authoring.models import Project
from tools.workflow_authoring.task_models import TaskReferenceFinding
from tools.workflow_authoring.templates import TemplateId, render_shape
from tools.workflow_preview.models import PreviewModel
from workflows.definition import ReusableTaskReferences, TaskBinding

from .files import open_directory, private_bytes
from .models import ConsoleConfig, TaskChoice
from .settings_file import SettingsInvalid
from .settings_models import ExperimentSetupsPolicy, Id, Label

SETUPS_SCHEMA = "siderius.console-experiment-setups/v1"
SETUPS_FILE = "experiment_setups.json"
PROJECTS = "projects"
SOURCE_NAME = "workflow.py"
RECOVERY_NAME = ".recovery"
NO_MATCHING_TASK = "no matching task"


class TemplateOrigin(PreviewModel):
    template_id: TemplateId


class SetupEntry(PreviewModel):
    setup_id: Id
    task_id: Id
    label: Label
    origin: TemplateOrigin | Literal["blank"]
    created_at: AwareDatetime


class SetupsFile(PreviewModel):
    schema_version: Literal["siderius.console-experiment-setups/v1"]
    setups: tuple[SetupEntry, ...] = ()

    @model_validator(mode="after")
    def unique(self) -> SetupsFile:
        if len({entry.setup_id for entry in self.setups}) != len(self.setups):
            raise ValueError("setup IDs must be unique")
        return self


class SetupCreate(PreviewModel):
    label: Label
    template_id: TemplateId | None = None


class SetupView(PreviewModel):
    setup_id: str
    label: str
    runnable: bool
    saved_version: str | None = Field(description="sha256 of the saved source; None if unreadable")
    refs_match_task: bool


class SetupRefused(Exception):
    def __init__(
        self, status: int, code: str, message: str, finding: TaskReferenceFinding | None = None
    ):
        super().__init__(message)
        self.status, self.code, self.message, self.finding = status, code, message, finding


@dataclass(frozen=True)
class Setup:
    project: Project
    label: str
    runnable: bool
    task_id: str | None  # registry entries: the bound task; legacy: resolved from refs


def registry_path(workspace: Path) -> Path:
    return workspace / "settings" / SETUPS_FILE


def setup_project(workspace: Path, setup_id: str) -> Project:
    root = workspace / PROJECTS / setup_id
    return Project(
        project_id=setup_id,
        project_root=root,
        source_file=root / SOURCE_NAME,
        recovery_directory=root / RECOVERY_NAME,
    )


def _read(path: Path) -> tuple[tuple[SetupEntry, ...], str | None]:
    try:
        payload = private_bytes(str(path))
    except FileNotFoundError:
        return (), None
    except (OSError, OperationFailure) as error:
        raise SettingsInvalid(
            f"settings/{SETUPS_FILE} must be a private regular file (mode 600)"
        ) from error
    try:
        document = SetupsFile.model_validate_json(payload)
    except ValidationError:
        raise SettingsInvalid(f"settings/{SETUPS_FILE} is not valid {SETUPS_SCHEMA} JSON") from None
    return document.setups, hashlib.sha256(payload).hexdigest()


class SetupStore:
    """Registry entries of one workspace; the only writer of ``experiment_setups.json``."""

    def __init__(
        self,
        workspace: Path | None = None,
        policy: ExperimentSetupsPolicy | None = None,
        entries: tuple[SetupEntry, ...] = (),
        sha256: str | None = None,
    ):
        self.workspace, self.policy = workspace, policy
        self._entries = {entry.setup_id: entry for entry in entries}
        self._sha256 = sha256
        self._lock = threading.RLock()  # create() reads entries() while holding it

    @classmethod
    def load(
        cls,
        config: ConsoleConfig,
        workspace: Path | None,
        policy: ExperimentSetupsPolicy | None = None,
    ) -> SetupStore:
        """Read the registry; an unknown task or an ID shared with editor_projects fails."""
        if workspace is None:
            return cls()
        entries, digest = _read(registry_path(workspace))
        store = cls(workspace, policy, entries, digest)
        tasks = {task.task_id for task in config.tasks}
        for entry in entries:
            if entry.task_id not in tasks:
                raise SettingsInvalid(
                    f"experiment setup {entry.setup_id!r} names unknown task {entry.task_id!r}"
                )
        SetupRegistry(config, store).setups()  # ID collisions fail here
        return store

    def entries(self) -> tuple[SetupEntry, ...]:
        with self._lock:
            return tuple(self._entries.values())

    @property
    def creatable(self) -> bool:
        return (
            self.workspace is not None
            and self.policy is not None
            and (self.policy.browser_creatable)
        )

    def create(self, config: ConsoleConfig, task_id: str, request: SetupCreate) -> SetupEntry:
        """Validate, render, create the folder write-once, then register by CAS."""
        request = SetupCreate.model_validate_json(request.model_dump_json())
        workspace = self.workspace
        if not self.creatable or workspace is None:
            raise SetupRefused(
                403,
                "read_only",
                "this console does not create experiment setups; set "
                "experiment_setups.browser_creatable in console.json and restart",
            )
        task = next((t for t in config.tasks if t.task_id == task_id), None)
        if task is None:
            raise SetupRefused(404, "not_found", "task is not configured")
        source = render_shape(
            request.template_id,
            ReusableTaskReferences(manifest=task.task_manifest, data_root=task.data_root),
            accepted_binding(task),
        ).encode()
        with self._lock:
            self._check_unchanged(workspace, created=None)
            registry = SetupRegistry(config, self)
            setup_id = _materialize(workspace, request.label, registry, source)
            created = f"{PROJECTS}/{setup_id}/"
            try:
                check_setup_project(setup_project(workspace, setup_id), config)
            except (OSError, ValueError) as error:
                raise SetupRefused(
                    409,
                    "invalid_setup",
                    f"the setup folder failed validation ({error}); {created} was left in place",
                ) from None
            entry = SetupEntry(
                setup_id=setup_id,
                task_id=task.task_id,
                label=request.label,
                origin="blank"
                if request.template_id is None
                else TemplateOrigin(template_id=request.template_id),
                created_at=datetime.now(UTC),
            )
            self._publish(workspace, entry, created)
            self._entries[setup_id] = entry
        return entry

    def _check_unchanged(self, workspace: Path, *, created: str | None) -> None:
        try:
            _, digest = _read(registry_path(workspace))
        except SettingsInvalid as error:
            digest, problem = "unreadable", str(error)
        else:
            problem = None
        if digest != self._sha256:
            left = "" if created is None else f"; {created} was left in place, unregistered"
            raise SetupRefused(
                409,
                "stale",
                (problem or f"settings/{SETUPS_FILE} changed since the console started")
                + f"; restart the console to read it{left}",
            )

    def _publish(self, workspace: Path, entry: SetupEntry, created: str) -> None:
        from .settings_service import _publish_private

        self._check_unchanged(workspace, created=created)
        document = SetupsFile(schema_version=SETUPS_SCHEMA, setups=(*self._entries.values(), entry))
        payload = (document.model_dump_json(indent=2) + "\n").encode()
        try:
            _publish_private(registry_path(workspace), payload)
        except (OSError, OperationFailure):
            raise SetupRefused(
                409,
                "unavailable",
                f"settings/{SETUPS_FILE} could not be written; {created} was left in place, "
                "unregistered",
            ) from None
        self._sha256 = hashlib.sha256(payload).hexdigest()


class SetupRegistry:
    """Legacy editor_projects of ``config`` plus the store's live entries."""

    def __init__(self, config: ConsoleConfig, store: SetupStore | None = None):
        self.config = config
        self.store = store if store is not None else SetupStore()

    @classmethod
    def legacy(cls, projects: tuple[Project, ...], runnable: tuple[str, ...]) -> SetupRegistry:
        """Bare projects of a code caller; they resolve no task (no configured tasks)."""
        config = ConsoleConfig.model_construct(
            editor_projects=projects, runnable_editor_projects=runnable
        )
        return cls(config)

    def setups(self) -> tuple[Setup, ...]:
        runnable = set(self.config.runnable_editor_projects)
        legacy = tuple(
            Setup(project, project.project_id, project.project_id in runnable, None)
            for project in self.config.editor_projects
        )
        workspace = self.store.workspace
        created = (
            ()
            if workspace is None
            else tuple(
                Setup(setup_project(workspace, e.setup_id), e.label, True, e.task_id)
                for e in self.store.entries()
            )
        )
        known = {setup.project.project_id for setup in legacy}
        clash = next((s.project.project_id for s in created if s.project.project_id in known), None)
        if clash is not None:
            raise SettingsInvalid(
                f"experiment setup ID {clash!r} is also a console.json editor project"
            )
        return (*legacy, *created)

    def projects(self) -> tuple[Project, ...]:
        return tuple(setup.project for setup in self.setups())

    def get(self, setup_id: str) -> Setup | None:
        return next((s for s in self.setups() if s.project.project_id == setup_id), None)

    def runnable(self, setup_id: str) -> Setup:
        setup = self.get(setup_id)
        if setup is None or not setup.runnable:
            raise OperationFailure("editor_policy", "project is not enabled for candidate runs")
        return setup

    def task_of(self, setup: Setup) -> str | None:
        """The bound task; for a legacy setup the one task its saved refs resolve to."""
        if setup.task_id is not None:
            return setup.task_id
        refs = source_refs(setup.project)
        matches = [
            t.task_id for t in self.config.tasks if refs is not None and refs == task_refs(t)
        ]
        return matches[0] if len(matches) == 1 else None

    def for_task(self, task_id: str) -> tuple[SetupView, ...]:
        task = next((t for t in self.config.tasks if t.task_id == task_id), None)
        if task is None:
            raise SetupRefused(404, "not_found", "task is not configured")
        views = []
        for setup in self.setups():
            if self.task_of(setup) != task_id:
                continue
            refs = source_refs(setup.project)
            views.append(
                SetupView(
                    setup_id=setup.project.project_id,
                    label=setup.label,
                    runnable=setup.runnable,
                    saved_version=saved_version(setup.project),
                    refs_match_task=refs is not None and refs == task_refs(task),
                )
            )
        return tuple(views)


def task_refs(task: TaskChoice) -> tuple[Path, Path]:
    return Path(task.task_manifest).resolve(), Path(task.data_root).resolve()


def source_refs(project: Project) -> tuple[Path, Path] | None:
    """Resolved (manifest, data_root) of the saved source; ``None`` when unreadable."""
    from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring
    from tools.workflow_preview.files import resolve_location

    try:
        document = WorkflowAuthoring(project).read().document
        if document is None:
            return None
        task = document.definition.task
        root = project.project_root
        return (
            resolve_location(root, task.manifest, "manifest"),
            resolve_location(root, task.data_root, "data_root"),
        )
    except (AuthoringError, OSError, ValueError):
        return None


def saved_version(project: Project) -> str | None:
    from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring

    try:
        return WorkflowAuthoring(project).read().sha256
    except (AuthoringError, OSError, ValueError):
        return None


def accepted_binding(task: TaskChoice) -> TaskBinding | None:
    """The task's accepted revision, only after the native owner re-observes it."""
    from tools.workflow_authoring.task_observation import identity_matches, observe_target

    from .editor import task_reference_targets

    if task.task_revision is None:
        return None
    target = task_reference_targets((task,))[0]
    try:
        observed = observe_target(target)
    except (OSError, ValueError):
        observed = None
    if observed is not None and identity_matches(observed, target):
        return task.task_revision
    code = (
        "inspection_failed"
        if observed is None or observed.result.outcome != "passed"
        else "identity_mismatch"
    )
    raise SetupRefused(
        409,
        code,
        "the task package no longer matches its accepted revision; nothing was created",
        TaskReferenceFinding(
            code=code,
            state="blocked",
            reference="task_binding",
            message="Native observation failed or differs from the configured pin",
        ),
    )


def check_setup_project(project: Project, config: ConsoleConfig) -> None:
    """Authoring paths valid and recovery separate from run output roots (startup and create)."""
    from tools.workflow_authoring.service import WorkflowAuthoring

    WorkflowAuthoring(project)
    store = config.operation_store
    for output in (*store.preparation_roots, *store.candidate_roots):
        output_path = Path(output)
        recovery = project.recovery_directory
        if recovery.is_relative_to(output_path) or output_path.is_relative_to(recovery):
            raise ValueError("editor recovery must be separate from run output roots")


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:60].strip("-")
    return slug or "setup"


def _materialize(workspace: Path, label: str, registry: SetupRegistry, source: bytes) -> str:
    """Create ``projects/<id>/`` (0700), its recovery folder (0700) and the source (0600)."""
    from .settings_export import _write_once
    from .workspace import WorkspaceRefused, ensure_owned_directory

    taken = {setup.project.project_id for setup in registry.setups()}
    try:
        root = open_directory(workspace)
        try:
            projects = ensure_owned_directory(root, PROJECTS, PROJECTS)
        finally:
            os.close(root)
    except (OSError, WorkspaceRefused):
        raise SetupRefused(
            409, "unavailable", "projects/ is unavailable, linked or not yours; nothing was created"
        ) from None
    try:
        base = _slug(label)
        for index in range(1, 1000):
            setup_id = base if index == 1 else f"{base}-{index}"
            if setup_id in taken:
                continue
            try:
                os.mkdir(setup_id, 0o700, dir_fd=projects)
                break
            except FileExistsError:
                continue  # a folder left by an earlier attempt is never reused
        else:
            raise SetupRefused(409, "exists", "no free setup folder name; choose another label")
        created = f"{PROJECTS}/{setup_id}/"
        try:
            target = os.open(
                setup_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=projects
            )
            try:
                os.fchmod(target, 0o700)
                os.close(ensure_owned_directory(target, RECOVERY_NAME, created + RECOVERY_NAME))
                _write_once(target, SOURCE_NAME, source)
            finally:
                os.close(target)
        except (OSError, WorkspaceRefused):
            raise SetupRefused(
                409, "unavailable", f"the setup could not be written; {created} was left in place"
            ) from None
    finally:
        os.close(projects)
    return setup_id
