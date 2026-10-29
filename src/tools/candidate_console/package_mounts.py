"""Task package mounts: every manifest-referenced file must be visible in the run sandbox.

A manifest reference must be visible to both sandboxed stages. The paths both
mount are the manifest file, the data root and ``task_read_only``
(``candidate_prepare.launch.supervise`` also mounts the LLM profile, but the
candidate run in ``candidate_prepare.bundle`` does not), plus what
``workspace_sandbox.command`` mounts for every profile: the serving checkout
(``runtime_roots``), ``SYSTEM_DIRECTORIES`` and ``SYSTEM_FILES``. Network files
are left out because preparation runs offline. A plugin or declaration beside
the manifest that none of those cover fails inside the sandbox;
:func:`check_package_mounts` refuses it at ``check`` time and names the file.
The sandbox profile itself is unchanged.
"""

from __future__ import annotations

from pathlib import Path

from tools.workspace_sandbox.profile import (
    SYSTEM_DIRECTORIES,
    SYSTEM_FILES,
    SandboxProfile,
    runtime_roots,
)
from workflows.task_package_refs import ManifestReference, manifest_references

from .models import ConsoleConfig, TaskChoice
from .settings_file import SettingsInvalid


def mounted_paths(task: TaskChoice) -> tuple[Path, ...]:
    """The read-only paths both a preparation and a candidate run of ``task`` can see."""
    return (
        Path(task.task_manifest),
        Path(task.data_root),
        *map(Path, task.task_read_only),
        *runtime_roots(),
        *SYSTEM_DIRECTORIES,
        *SYSTEM_FILES,
    )


def _real(path: Path) -> Path:
    # The sandbox binds real paths; a symlink inside a mount that points outside is not visible.
    return path.resolve()


def unmounted_reference(
    references: tuple[ManifestReference, ...], mounts: tuple[Path, ...]
) -> ManifestReference | None:
    """The first reference outside every mount, or ``None``."""
    real_mounts = tuple(_real(mount) for mount in mounts)
    for reference in references:
        target = _real(reference.path)
        if not any(target == mount or target.is_relative_to(mount) for mount in real_mounts):
            return reference
    return None


def check_package_mounts(task: TaskChoice) -> None:
    """Refuse, naming the file, when a file/dir reference is missing or any reference is unmounted."""
    try:
        references = manifest_references(task.task_manifest)
    except (OSError, ValueError) as error:
        raise SettingsInvalid(f"task {task.task_id}: {error}") from None
    for reference in references:
        exists = {
            "directory": reference.path.is_dir,
            "file": reference.path.is_file,
            "path": lambda: True,  # composition only resolves an envelope path
        }[reference.kind]()
        if not exists:
            raise SettingsInvalid(
                f"task {task.task_id} manifest {reference.location} names {reference.path}, "
                "which does not exist"
            )
    outside = unmounted_reference(references, mounted_paths(task))
    if outside is not None:
        raise SettingsInvalid(
            f"task {task.task_id} manifest {outside.location} names {outside.path}, which is "
            "outside every mounted path (manifest, data folder, task_read_only, serving "
            "checkout, system directories); add its package directory to task_read_only"
        )


def device_problem(device: str) -> str | None:
    """Why the run sandbox would refuse ``device`` on this host, or ``None``.

    Calls the sandbox's own admission, ``SandboxProfile.device_paths`` (a
    canonical existing path under ``/dev`` that is a character device), and
    returns its refusal reason; this module adds no second device rule.
    """
    try:
        SandboxProfile.device_paths((Path(device),))
    except ValueError as error:
        return str(error)
    return None


def check_candidate_devices(task: TaskChoice) -> None:
    """Refuse, naming the path, a ``candidate_devices`` entry the sandbox cannot pass.

    Only ``add-task`` calls this, where the paths are typed. ``check``/``serve``
    report the same problems as warnings (:func:`device_warnings`), because a
    node such as ``/dev/nvidia-uvm`` may appear only after first CUDA use; run
    admission (``SandboxProfile.device_paths``) stays the hard gate.
    """
    for device in task.candidate_devices:
        problem = device_problem(device)
        if problem is not None:
            raise SettingsInvalid(
                f"task {task.task_id} candidate_devices names {device}, which the run "
                f"sandbox refuses ({problem}); list only device nodes present on this "
                "machine (for example ls -l /dev/nvidia*)"
            )


def device_warnings(devices: tuple[str, ...]) -> tuple[str, ...]:
    """The device paths of one task's run that the sandbox would refuse, as warnings.

    ``check``/``serve`` print this list for every task; Run review repeats it for the
    reviewed request, so an unusable device is named before Launch. A GPU node needs
    no further setting: the sandbox adds read-only ``/sys`` and the NVIDIA control
    nodes itself (``tools.workspace_sandbox.gpu``).
    """
    return tuple(
        f"Device {device} cannot be passed into the run sandbox ({problem}); "
        "a run given it will be refused."
        for device in devices
        if (problem := device_problem(device)) is not None
    )


def gpu_warnings(config: ConsoleConfig) -> tuple[str, ...]:
    """Each task's device warnings, prefixed with its ID (``check``/``serve`` stderr)."""
    return tuple(
        f"Task {task.task_id}: {warning}"
        for task in config.tasks
        for warning in device_warnings(task.candidate_devices)
    )
