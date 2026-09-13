"""Immutable workspace transport of captured locators/pins, never source bytes."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, MutableMapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from core.generated_library import verified_chain_workspace
from core.local_code.capture import (
    CapturedCodePackage,
    CodePackageDeclaration,
    LocalCodeError,
    PackageIdentity,
    canonical_bytes,
    capture_package,
    sha256,
)

MANIFEST_ENV = "SIDERIUS_TASK_CODE_MANIFEST"
DIGEST_ENV = "SIDERIUS_TASK_CODE_SHA256"


class CodeTransport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    root: Path
    locator_root: Path
    identity: PackageIdentity

    @model_validator(mode="after")
    def validate_locators_and_members(self) -> CodeTransport:
        if not self.root.is_absolute() or not self.locator_root.is_absolute():
            raise ValueError("code transport roots must be absolute")
        declaration = CodePackageDeclaration(
            root=".", files=tuple(pin.member for pin in self.identity.members)
        )
        if declaration.files != tuple(pin.member for pin in self.identity.members):
            raise ValueError("code transport pins must be in canonical member order")
        return self


def read_inherited_package(environ: Mapping[str, str]) -> CapturedCodePackage | None:
    """Verify carrier and ALL members before returning any executable snapshot."""
    path = environ.get(MANIFEST_ENV)
    digest = environ.get(DIGEST_ENV)
    if path is None and digest is None:
        return None
    if not path or not digest or not Path(path).is_absolute():
        raise LocalCodeError(
            "code_package transport requires both absolute manifest and SHA256 keys"
        )
    try:
        payload = Path(path).read_bytes()
        if sha256(payload) != digest:
            raise LocalCodeError(
                f"code_package transport digest mismatch at {path}; restore parent-pinned manifest"
            )
        transport = CodeTransport.model_validate_json(payload)
        captured = capture_package(
            CodePackageDeclaration(
                root=str(transport.locator_root),
                files=tuple(pin.member for pin in transport.identity.members),
            ),
            transport.locator_root,
        )
    except (OSError, ValueError) as exc:
        raise LocalCodeError(f"code_package transport refused: {exc}") from exc
    if captured.root != transport.root:
        raise LocalCodeError("code_package locator root changed since parent capture")
    if captured.identity != transport.identity:
        expected = {pin.member: pin.content_sha256 for pin in transport.identity.members}
        changed = [
            member.pin.member
            for member in captured.members
            if expected.get(member.pin.member) != member.pin.content_sha256
        ]
        raise LocalCodeError(
            f"code_package member digest mismatch: {changed}; restore parent-pinned source"
        )
    return captured


def _write_once(path: Path, payload: bytes) -> None:
    """Atomic no-replace publication; existing bytes must match exactly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".task-code-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise LocalCodeError(
                        f"code_package immutable transport mismatch at {path}"
                    ) from None
        finally:
            temporary.unlink()


def write_transport(package: CapturedCodePackage, environ: MutableMapping[str, str]) -> None:
    """Use only captured pins; edits after acquisition cannot re-pin at spawn."""
    try:
        workspace = verified_chain_workspace(environ=environ)
        transport = CodeTransport(
            root=package.root, locator_root=package.locator_root, identity=package.identity
        )
        payload = canonical_bytes(transport.model_dump(mode="json"))
        digest = sha256(payload)
        path = Path(workspace) / "task_code" / f"{digest}.json"
        _write_once(path, payload)
    except OSError as exc:
        raise LocalCodeError(f"code_package cannot materialize captured transport: {exc}") from exc
    except ValueError as exc:
        raise LocalCodeError(f"code_package transport refused: {exc}") from exc
    environ[MANIFEST_ENV] = str(path)
    environ[DIGEST_ENV] = digest
