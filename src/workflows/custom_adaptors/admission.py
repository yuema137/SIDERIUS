"""Admission records in the external project (operator decision B6-D11).

``<project>/.siderius/adaptors/<id>/<identity>.admission.json`` is written only
after a passing self-test and never inside the framework checkout or installed
packages. Records are write-once: an identical re-admission is a no-op and a
different record for the same identity is refused unless ``replace`` is set.
A consumer must match both ``identity_sha256`` and ``manifest_sha256``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.durable_io import publish_bytes_atomically, publish_bytes_write_once
from core.layout import checkout_root, package_root
from core.local_code import PackageIdentity
from core.runtime_control.gpu_milestone_trace import resolve_git_sha
from workflows.custom_adaptors.errors import CustomAdaptorError
from workflows.custom_adaptors.manifest import LoadedAdaptor
from workflows.custom_adaptors.self_test import FixtureResult, SelfTestReport

ADMISSION_DIRECTORY = Path(".siderius") / "adaptors"


class AdaptorAdmissionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["siderius.adaptor-admission/v1"] = "siderius.adaptor-admission/v1"
    adaptor_id: str
    adaptor_version: str
    role: Literal["combine", "select", "distribute"]
    deterministic: Literal[True]
    manifest: str
    manifest_sha256: str
    identity_sha256: str
    package: PackageIdentity
    self_test: tuple[FixtureResult, ...]
    framework_revision: str


def _framework_locations() -> tuple[Path, ...]:
    roots = (checkout_root(), package_root())
    return tuple(root.resolve() for root in roots if root is not None)


def admission_path(project: Path, loaded: LoadedAdaptor) -> Path:
    """Refuse a project inside the framework; return the record location."""
    project = project.resolve()
    for root in _framework_locations():
        if project.is_relative_to(root):
            raise CustomAdaptorError(
                "admission_location",
                f"project {project} is inside framework source {root}; use the external project",
            )
    if not loaded.directory.is_relative_to(project):
        raise CustomAdaptorError(
            "admission_location", f"manifest directory {loaded.directory} is outside {project}"
        )
    return (
        project
        / ADMISSION_DIRECTORY
        / loaded.manifest.id
        / f"{loaded.identity_sha256}.admission.json"
    )


def write_admission(
    project: Path, loaded: LoadedAdaptor, report: SelfTestReport, *, replace: bool = False
) -> Path:
    """Write the record for a passing self-test of exactly this identity."""
    if (report.identity_sha256, report.manifest_sha256) != (
        loaded.identity_sha256,
        loaded.manifest.digest,
    ):
        raise CustomAdaptorError(
            "admission_conflict", "self-test report belongs to a different identity or manifest"
        )
    path = admission_path(project, loaded)
    record = AdaptorAdmissionRecord(
        adaptor_id=loaded.manifest.id,
        adaptor_version=loaded.manifest.version,
        role=loaded.manifest.role,
        deterministic=loaded.manifest.deterministic,
        manifest=loaded.path.relative_to(project.resolve()).as_posix(),
        manifest_sha256=loaded.manifest.digest,
        identity_sha256=loaded.identity_sha256,
        package=loaded.package.identity,
        self_test=report.fixtures,
        framework_revision=resolve_git_sha(),
    )
    payload = (record.model_dump_json(indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if replace:
        publish_bytes_atomically(str(path), payload, mode=0o644)
        return path
    try:
        publish_bytes_write_once(str(path), payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise CustomAdaptorError(
                "admission_conflict",
                f"{path} already holds a different record for this identity; "
                "re-run admit with --replace to supersede it",
            ) from None
    return path
