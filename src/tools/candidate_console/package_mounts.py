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

import re
from pathlib import Path

from tools.workspace_sandbox.profile import SYSTEM_DIRECTORIES, SYSTEM_FILES, runtime_roots
from workflows.task_package_refs import ManifestReference, manifest_references

from .models import ConsoleConfig, TaskChoice
from .settings_file import SettingsInvalid

GPU_DEVICE = re.compile(r"/dev/nvidia[0-9]+")
GPU_WITHOUT_SYS = (
    "GPU devices are passed but /sys is not mounted read-only; CUDA may fail to start "
    "inside the run sandbox (see README)."
)


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
    """Refuse, naming the file, when a manifest reference is missing or not mounted."""
    try:
        references = manifest_references(task.task_manifest)
    except (OSError, ValueError) as error:
        raise SettingsInvalid(f"task {task.task_id}: {error}") from None
    for reference in references:
        exists = (
            reference.path.is_dir() if reference.kind == "directory" else reference.path.is_file()
        )
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


def gpu_warnings(config: ConsoleConfig) -> tuple[str, ...]:
    """One warning per task passing NVIDIA device nodes without a read-only ``/sys``."""
    return tuple(
        f"Task {task.task_id}: {GPU_WITHOUT_SYS}"
        for task in config.tasks
        if any(GPU_DEVICE.fullmatch(device) for device in task.candidate_devices)
        and "/sys" not in task.task_read_only
    )
