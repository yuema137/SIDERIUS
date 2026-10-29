"""``add-task``: register one task package in console.json without hand-editing it.

The command appends one ``tasks[]`` entry and writes nothing else:

- the five ``TaskChoice`` fields that have no default, written explicitly:
  ``preparation_timeout_seconds``, ``candidate_timeout_seconds`` and
  ``candidate_network`` from :data:`STARTER_VALUES` unless overridden;
  ``candidate_devices`` from ``--device`` (otherwise an interactive question
  about the host's ``/dev/nvidia*`` nodes, or none when stdin is not a TTY);
  ``candidate_environment_names`` from the credential requirement owner
  (``candidate_worker.preflight.credential_requirements``) applied to every
  route of the task's resolved LLM profile, plus any ``--env`` names;
- ``task_read_only``: the task package directory, so preparation sees the
  plugins and declarations beside the manifest (#1145 item 1). The package
  directory is the first-level folder of ``<workspace>/tasks/`` holding the
  manifest; with ``--external`` it is the set of directories of the files the
  manifest references.

Location fields (data, output roots, LLM profile) stay omitted so the
workspace layout and global settings fill them. Before writing, every
manifest reference must resolve inside the run sandbox mounts
(``package_mounts``) and every ``candidate_devices`` path must pass the run
sandbox's device admission (``SandboxProfile.device_paths``) on this host;
``check`` only warns about devices. The write is a compare-and-swap on the bytes read and an
atomic owner-only (0600) publish; ``--dry-run`` prints the entry and writes
nothing. Credential values are never read.

``--from-bundle DIR`` imports an unpacked example bundle instead of naming a
manifest: ``example_bundle`` verifies and copies its package to
``<workspace>/tasks/<task_id>/``, this module registers it, and the bundle's first
experiment setup is created through ``SetupStore.create``.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.candidate_operations.models import OperationFailure

from .files import canonical, config_bytes
from .models import ConsoleConfig
from .package_mounts import check_candidate_devices, check_package_mounts
from .settings_file import SettingsInvalid
from .settings_models import ResolvedConsole


@dataclass(frozen=True)
class StarterValues:
    """Documented starting resource policy; the operator edits console.json to change it."""

    preparation_timeout_seconds: float
    candidate_timeout_seconds: float
    candidate_network: bool


#: Written explicitly into each new task entry (design 2c, lead decision Q2).
STARTER_VALUES = StarterValues(
    preparation_timeout_seconds=300.0,
    candidate_timeout_seconds=3600.0,
    candidate_network=True,
)
TASK_ID = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")
TASKS_DIRECTORY = "tasks"


class AddTaskRefused(ValueError):
    """add-task refused; console.json was not changed."""


@dataclass(frozen=True)
class AddTaskRequest:
    config: str
    manifest: str
    task_id: str | None = None
    label: str | None = None
    environment_names: tuple[str, ...] = ()
    network: bool = STARTER_VALUES.candidate_network
    devices: tuple[str, ...] | None = None  # None: ask (TTY) or none
    preparation_timeout_seconds: float = STARTER_VALUES.preparation_timeout_seconds
    candidate_timeout_seconds: float = STARTER_VALUES.candidate_timeout_seconds
    external: bool = False


@dataclass(frozen=True)
class TaskPlan:
    config_path: Path
    read_bytes: bytes  # compare-and-swap witness
    entry: dict[str, Any]
    payload: bytes  # the complete new console.json
    workspace_root: Path


# Inputs -------------------------------------------------------------------------------


def host_gpu_devices() -> tuple[str, ...]:
    """Character devices named ``/dev/nvidia*`` on this host, sorted."""
    found = []
    for name in sorted(glob.glob("/dev/nvidia*")):
        path = Path(name)
        if path.is_char_device() and not path.is_symlink():
            found.append(name)
    return tuple(found)


def choose_devices(devices: tuple[str, ...] | None) -> tuple[str, ...]:
    """``--device`` wins; otherwise ask on a TTY; a non-interactive run passes none."""
    if devices is not None:
        return devices
    nodes = host_gpu_devices()
    if nodes and sys.stdin.isatty():
        print("This host has NVIDIA device nodes: " + ", ".join(nodes))
        try:
            answer = input("Pass them to candidate runs of this task? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raise AddTaskRefused(
                "no answer to the device question; pass --device PATH ... to choose devices"
            ) from None
        if answer in ("y", "yes"):
            return nodes
    print("candidate_devices: none (pass --device PATH to give runs a GPU device node)")
    return ()


def _package_directory(manifest: Path, workspace: Path, external: bool) -> Path | None:
    tasks = workspace / TASKS_DIRECTORY
    if external:
        return None
    if not manifest.is_relative_to(tasks):
        raise AddTaskRefused(
            f"the manifest is outside {tasks}; put the task package in "
            f"{tasks}/<name>/ or pass --external"
        )
    parts = manifest.relative_to(tasks).parts
    if len(parts) < 2:
        raise AddTaskRefused(f"put the manifest inside its own package folder, {tasks}/<name>/")
    return tasks / parts[0]


def _external_directories(manifest: Path) -> tuple[str, ...]:
    """Directories holding the manifest's referenced files, outermost only."""
    from workflows.task_package_refs import manifest_references

    try:
        references = manifest_references(manifest)
    except (OSError, ValueError) as error:
        raise AddTaskRefused(str(error)) from None
    directories: set[Path] = set()
    for reference in references:
        target = reference.path.resolve()
        if reference.kind == "path":
            # An envelope path may be a directory or not exist yet; mount what holds it.
            directories.add(target if target.is_dir() else target.parent)
            continue
        if not target.exists():
            raise AddTaskRefused(
                f"manifest {reference.location} names {reference.path}, which does not exist"
            )
        directories.add(target if reference.kind == "directory" else target.parent)
    outermost = sorted(
        path
        for path in directories
        if not any(path != other and path.is_relative_to(other) for other in directories)
    )
    return tuple(map(str, outermost))


def refuse_broad_mounts(folders: tuple[str, ...], config: ConsoleConfig, workspace: Path) -> None:
    """``--external`` mounts must not expose ``/``, the home folder or console-private paths."""
    from .settings_file import protected_paths

    home = Path.home().resolve()
    protected = tuple(Path(path) for path in protected_paths(config, workspace))
    for value in folders:
        folder = Path(value)
        reason = None
        if folder == Path("/"):
            reason = "is the root directory"
        elif home.is_relative_to(folder):
            reason = "is or contains your home folder"
        else:
            hit = next(
                (p for p in protected if p.is_relative_to(folder) or folder.is_relative_to(p)),
                None,
            )
            if hit is not None:
                reason = f"overlaps the console's private path {hit}"
        if reason is not None:
            raise AddTaskRefused(
                f"--external would mount {folder}, which {reason}; move the package files "
                f"into {workspace / TASKS_DIRECTORY}/<name>/ instead"
            )


def profile_environment_names(llm_config_file: str) -> tuple[str, ...]:
    """Credential names every route of the profile may require; names only, no values."""
    from tools.candidate_worker.preflight import credential_requirements
    from tools.setup_review.routes import standard_llm_routes
    from tools.workflow_preview.config import parse_config

    config = parse_config(config_bytes(llm_config_file))
    # A task does not know which nodes its workflows will use, so every role counts.
    routes = standard_llm_routes(
        config, literature_enabled=True, analysis_enabled=True, pseudo_llm=False
    )
    return credential_requirements(tuple(routes), ()).required_names


# Plan and publish ---------------------------------------------------------------------


def _resolve(document: dict[str, Any]) -> ResolvedConsole:
    from .workspace import resolve_console

    return resolve_console((json.dumps(document, indent=2) + "\n").encode())


def _with_entry(document: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    updated = dict(document)
    updated["tasks"] = [*document.get("tasks", []), entry]
    return updated


def plan_task(request: AddTaskRequest) -> TaskPlan:
    """Validate the request and build the new console.json; writes nothing."""
    for flag, value in (("--config", request.config), ("--manifest", request.manifest)):
        if not os.path.isabs(value) or os.path.normpath(value) != value:
            raise AddTaskRefused(
                f"{flag} must be an absolute path without '..' or a trailing slash, "
                f"for example {os.path.abspath(value)}"
            )
    try:
        config_path = canonical(request.config)
        read_bytes = config_bytes(str(config_path))
        manifest = canonical(request.manifest)
    except OperationFailure:
        raise AddTaskRefused(
            "--config and --manifest must be canonical paths without symlinks"
        ) from None
    except OSError as error:
        raise AddTaskRefused(f"cannot read {error.filename or 'the given file'}") from None
    if not manifest.is_file():
        raise AddTaskRefused(f"the manifest {manifest} is not a file")
    from .settings_models import ConsoleFile

    try:
        ConsoleFile.model_validate_json(read_bytes)
    except ValueError:
        raise AddTaskRefused(
            "console.json is not a valid console configuration; run check on it first"
        ) from None
    document = json.loads(read_bytes)
    if document.get("workspace_root") is None:
        raise AddTaskRefused("console.json has no workspace_root; create it with init first")
    workspace = Path(document["workspace_root"])
    package = _package_directory(manifest, workspace, request.external)
    task_id = request.task_id or (package or manifest.parent).name
    if not TASK_ID.fullmatch(task_id):
        raise AddTaskRefused(
            f"{task_id!r} is not a valid task ID (letters, digits, - and _); pass --task-id"
        )
    if any(task.get("task_id") == task_id for task in document.get("tasks", [])):
        raise AddTaskRefused(f"console.json already has a task {task_id!r}")
    read_only = (str(package),) if package is not None else _external_directories(manifest)
    devices = choose_devices(request.devices)
    entry: dict[str, Any] = {
        "task_id": task_id,
        "label": request.label or task_id,
        "task_manifest": str(manifest),
        "task_read_only": list(read_only),
        "preparation_timeout_seconds": request.preparation_timeout_seconds,
        "candidate_timeout_seconds": request.candidate_timeout_seconds,
        "candidate_network": request.network,
        "candidate_devices": list(devices),
        "candidate_environment_names": [],
    }
    try:
        draft = _resolve(_with_entry(document, entry))
        if package is None:
            refuse_broad_mounts(read_only, draft.config, workspace)
        task = next(t for t in draft.config.tasks if t.task_id == task_id)
        required = profile_environment_names(task.llm_config_file)
        entry["candidate_environment_names"] = list(
            dict.fromkeys((*required, *request.environment_names))
        )
        updated = _with_entry(document, entry)
        resolved = _resolve(updated)
        task = next(t for t in resolved.config.tasks if t.task_id == task_id)
        check_package_mounts(task)
        check_candidate_devices(task)
    except AddTaskRefused:
        raise
    except SettingsInvalid as error:
        raise AddTaskRefused(str(error)) from None
    except (OSError, ValueError, OperationFailure) as error:
        # Pydantic and file errors: name the class only; messages may quote input values.
        raise AddTaskRefused(
            f"the new task entry is not valid ({type(error).__name__}); console.json was not changed"
        ) from None
    payload = (json.dumps(updated, indent=2) + "\n").encode()
    return TaskPlan(config_path, read_bytes, entry, payload, workspace)


def publish_task(plan: TaskPlan) -> None:
    """Compare-and-swap on the bytes ``plan_task`` read, then an atomic 0600 replace."""
    from .settings_service import _publish_private

    try:
        current = config_bytes(str(plan.config_path))
    except (OSError, OperationFailure):
        current = None
    if current != plan.read_bytes:
        raise AddTaskRefused(
            "console.json changed since add-task read it; nothing was written, run add-task again"
        )
    _publish_private(plan.config_path, plan.payload)


def create_folders(plan: TaskPlan) -> None:
    """Create the new task's derived output folders through ``init`` (never its data folder)."""
    from .workspace import CONSOLE_FILE, SETTINGS, WORKSPACE_DIRECTORY, init_workspace

    workspace = plan.workspace_root
    if (
        workspace.name == WORKSPACE_DIRECTORY
        and plan.config_path == workspace / SETTINGS / CONSOLE_FILE
    ):
        init_workspace(str(workspace.parent))
    else:
        print(
            "This console.json is not the workspace's settings/console.json; create the "
            "task's output folders yourself.",
            file=sys.stderr,
        )


# CLI ----------------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        prog="python -m tools.candidate_console add-task",
        description="Register one task package in console.json (append to tasks[]).",
    )
    cli.add_argument("--config", required=True, help="console.json path")
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", help="the task composition manifest")
    source.add_argument(
        "--from-bundle",
        metavar="DIR",
        help="an unpacked example bundle: verify it, copy its task/ to tasks/<id>/, "
        "register it and create its first experiment setup",
    )
    cli.add_argument("--task-id", help="default: the package folder name")
    cli.add_argument("--label", help="default: the task ID")
    cli.add_argument(
        "--env",
        nargs="+",
        default=[],
        metavar="NAME",
        help="extra environment variable names passed to runs (the LLM profile's are added)",
    )
    cli.add_argument(
        "--network",
        action=argparse.BooleanOptionalAction,
        default=STARTER_VALUES.candidate_network,
        help=f"candidate network access (starter: {STARTER_VALUES.candidate_network})",
    )
    cli.add_argument(
        "--device", nargs="+", metavar="PATH", help="character device passed to candidate runs"
    )
    cli.add_argument(
        "--prepare-timeout",
        type=float,
        default=STARTER_VALUES.preparation_timeout_seconds,
        metavar="S",
        help=f"seconds (starter: {STARTER_VALUES.preparation_timeout_seconds:g})",
    )
    cli.add_argument(
        "--candidate-timeout",
        type=float,
        default=STARTER_VALUES.candidate_timeout_seconds,
        metavar="S",
        help=f"seconds (starter: {STARTER_VALUES.candidate_timeout_seconds:g})",
    )
    cli.add_argument(
        "--external",
        action="store_true",
        help="allow a manifest outside <workspace>/tasks/ (mounts its referenced folders)",
    )
    cli.add_argument("--dry-run", action="store_true", help="print the entry; write nothing")
    return cli


def _request(
    args: argparse.Namespace, manifest: str, task_id: str | None, label: str | None
) -> AddTaskRequest:
    return AddTaskRequest(
        config=args.config,
        manifest=manifest,
        task_id=task_id,
        label=label,
        environment_names=tuple(args.env),
        network=args.network,
        devices=None if args.device is None else tuple(args.device),
        preparation_timeout_seconds=args.prepare_timeout,
        candidate_timeout_seconds=args.candidate_timeout,
        external=args.external,
    )


def _from_bundle(args: argparse.Namespace) -> tuple[int, str | None]:
    """Verify, copy, register, then create the first setup (``example_bundle``)."""
    from .example_bundle import (
        BundleRefused,
        copy_package,
        create_first_setup,
        describe,
        plan_import,
        read_bundle,
    )
    from .setups import SetupRefused

    if args.external:
        print("add-task refused: --external does not apply to --from-bundle.", file=sys.stderr)
        return 2, None
    try:
        bundle = read_bundle(args.from_bundle)
        target = plan_import(bundle, args.config, args.task_id)
        if args.dry_run:
            print(describe(bundle, target))
            print("Dry run: nothing was copied and console.json was not changed.")
            return 0, None
        manifest = copy_package(bundle, target)
    except (BundleRefused, AddTaskRefused) as error:
        print(f"add-task refused: {error}.", file=sys.stderr)
        return 2, None
    print(f"Copied the verified task package to {target.package}")
    left = f" {target.package} was left in place; remove it before running add-task again."
    try:
        plan = plan_task(
            _request(args, str(manifest), target.task_id, args.label or bundle.task.label)
        )
        publish_task(plan)
    except AddTaskRefused as error:
        print(f"add-task refused: {error}.{left}", file=sys.stderr)
        return 2, None
    except (OSError, OperationFailure):
        print(
            f"add-task failed: console.json could not be written; it is unchanged.{left}",
            file=sys.stderr,
        )
        return 2, None
    print(f"Added task {plan.entry['task_id']} to {plan.config_path}:")
    print(json.dumps(plan.entry, indent=2))
    try:
        create_folders(plan)
    except (OSError, ValueError) as error:
        print(f"Creating the task's folders stopped: {error}.", file=sys.stderr)
    try:
        setup_id = create_first_setup(str(plan.config_path), target.task_id, bundle.setup)
    except SetupRefused as error:
        print(
            f"The task was added, but its first experiment setup was not created: "
            f"{error.message}. Create one in the Workflow tab instead.",
            file=sys.stderr,
        )
        return 2, None
    except (OSError, ValueError, OperationFailure):
        print(
            "The task was added, but its first experiment setup was not created: the "
            "console settings could not be read. Run check, then create a setup in the "
            "Workflow tab.",
            file=sys.stderr,
        )
        return 2, None
    print(
        f"Created experiment setup {setup_id!r} ({bundle.setup.label}) from template "
        f"{bundle.setup.template_id} in {plan.workspace_root / 'projects' / setup_id}"
    )
    return 0, str(plan.config_path)


def run_command(argv: list[str]) -> tuple[int, str | None]:
    """Return the exit status and, after a write, the console.json to check."""
    args = parser().parse_args(argv)
    if args.from_bundle is not None:
        return _from_bundle(args)
    request = _request(args, args.manifest, args.task_id, args.label)
    try:
        plan = plan_task(request)
        if args.dry_run:
            print(json.dumps(plan.entry, indent=2))
            print("Dry run: console.json was not changed.")
            return 0, None
        publish_task(plan)
    except AddTaskRefused as error:
        print(f"add-task refused: {error}.", file=sys.stderr)
        return 2, None
    except (OSError, OperationFailure):
        print(
            "add-task failed: console.json could not be written; it is unchanged.", file=sys.stderr
        )
        return 2, None
    print(f"Added task {plan.entry['task_id']} to {plan.config_path}:")
    print(json.dumps(plan.entry, indent=2))
    try:
        create_folders(plan)
    except (OSError, ValueError) as error:
        print(f"Creating the task's folders stopped: {error}.", file=sys.stderr)
    return 0, str(plan.config_path)


__all__ = [
    "STARTER_VALUES",
    "AddTaskRefused",
    "AddTaskRequest",
    "plan_task",
    "publish_task",
    "run_command",
]
