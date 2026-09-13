"""Finite task-owned source selection and immutable content identity."""

from __future__ import annotations

import hashlib
import json
import keyword
import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from core.local_code.failure import CodeFailure


class LocalCodeError(RuntimeError):
    """A declared package cannot be used; never downgrade to a scan warning."""

    def __init__(self, message: str, *, report: CodeFailure | None = None):
        super().__init__(message)
        self.report = report


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def module_key(member: str) -> str:
    parts = list(PurePosixPath(member).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class CodePackageDeclaration(BaseModel):
    """Only explicitly listed normalized Python files belong to the package."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    root: str = Field(min_length=1)
    files: tuple[str, ...] = Field(min_length=1)

    @field_validator("files")
    @classmethod
    def finite_python_names(cls, files: tuple[str, ...]) -> tuple[str, ...]:
        modules: dict[str, str] = {}
        for member in files:
            path = PurePosixPath(member)
            parts = (*path.parts[:-1], path.stem)
            if (
                str(path) != member
                or path.is_absolute()
                or path.suffix != ".py"
                or any(not part.isidentifier() or keyword.iskeyword(part) for part in parts)
            ):
                raise ValueError(
                    f"code_package member {member!r}: use normalized relative Python paths"
                )
            key = module_key(member)
            if key in modules:
                raise ValueError(
                    f"code_package duplicate/conflicting members: {modules[key]!r}, {member!r}"
                )
            modules[key] = member
        for key, member in modules.items():
            if PurePosixPath(member).name != "__init__.py" and any(
                other.startswith(key + ".") for other in modules
            ):
                raise ValueError(f"code_package module/package collision at {member!r}")
        return tuple(sorted(files))


class MemberPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    member: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PackageIdentity(BaseModel):
    """Semantic identity contains no host locators or runtime module names."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["task-local-code-v1"] = "task-local-code-v1"
    members: tuple[MemberPin, ...] = Field(min_length=1)

    @property
    def digest(self) -> str:
        return sha256(canonical_bytes(self.model_dump(mode="json")))


class MemberIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    package: PackageIdentity
    member: str


class CapturedMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pin: MemberPin
    source: bytes = Field(repr=False, exclude=True)


class CapturedCodePackage(BaseModel):
    """Exact immutable source bytes; disk is never reread by parent imports."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    root: Path
    locator_root: Path
    members: tuple[CapturedMember, ...]

    @property
    def identity(self) -> PackageIdentity:
        return PackageIdentity(members=tuple(member.pin for member in self.members))

    def member(self, path: str | Path) -> CapturedMember | None:
        # Keep lexical in-root paths in scope even when a symlink now escapes.
        target = Path(os.path.abspath(path))
        relative: str | None = None
        for root in (self.root, self.locator_root):
            if target.is_relative_to(root):
                relative = target.relative_to(root).as_posix()
                break
        if relative is None:
            resolved = target.resolve()
            if not resolved.is_relative_to(self.root):
                return None
            relative = resolved.relative_to(self.root).as_posix()
        for member in self.members:
            if member.pin.member == relative:
                return member
        raise LocalCodeError(
            f"code_package: undeclared member {relative!r}; add it to code_package.files"
        )


def capture_package(
    declaration: CodePackageDeclaration, manifest_dir: str | Path
) -> CapturedCodePackage:
    """Resolve root once and read each selected file exactly once before effects."""
    locator_root = Path(os.path.abspath(Path(manifest_dir) / declaration.root))
    root = locator_root.resolve()
    members: list[CapturedMember] = []
    for member in declaration.files:
        path = root / member
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise LocalCodeError(f"code_package member {member!r} escapes root {root}")
            source = resolved.read_bytes()
        except OSError as exc:
            raise LocalCodeError(
                f"code_package member {member!r} is missing/unreadable at {path}; restore declared source"
            ) from exc
        members.append(
            CapturedMember(
                pin=MemberPin(member=member, content_sha256=sha256(source)), source=source
            )
        )
    return CapturedCodePackage(root=root, locator_root=locator_root, members=tuple(members))
