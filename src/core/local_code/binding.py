"""Run decisions and the small optional acquisition boundary used by families."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from pathlib import Path
from types import ModuleType

from core.local_code.capture import (
    CapturedCodePackage,
    CapturedMember,
    CodePackageDeclaration,
    LocalCodeError,
    MemberIdentity,
    capture_package,
)
from core.local_code.importing import import_member


class _Unbound(Enum):
    VALUE = "no-active-decision"


UNBOUND = _Unbound.VALUE
_ACTIVE: ContextVar[CapturedCodePackage | None | _Unbound] = ContextVar(
    "local_code", default=UNBOUND
)


def active_package() -> CapturedCodePackage | None:
    value = _ACTIVE.get()
    return value if isinstance(value, CapturedCodePackage) else None


@contextmanager
def bind_code_package(package: CapturedCodePackage | None) -> Iterator[None]:
    """Restore the exact preceding decision; this does not manage family registries."""
    token = _ACTIVE.set(package)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def selected_member(path: str | Path) -> CapturedMember | None:
    package = active_package()
    return package.member(path) if package is not None else None


def selected_identity(path: str | Path) -> MemberIdentity | None:
    package = active_package()
    member = package.member(path) if package is not None else None
    return (
        MemberIdentity(package=package.identity, member=member.pin.member)
        if package is not None and member is not None
        else None
    )


@contextmanager
def composition_package(
    raw: object, manifest_dir: str | Path
) -> Iterator[CapturedCodePackage | None]:
    """Validate the optional declaration before any composition plugin effects."""
    package = None
    if raw is not None:
        try:
            declaration = CodePackageDeclaration.model_validate(raw)
            package = capture_package(declaration, manifest_dir)
        except ValueError as exc:
            raise LocalCodeError(f"code_package: {exc}") from exc
    with bind_code_package(package):
        yield package


def scan_candidate_allowed(path: str | Path) -> bool:
    """Discovery calls this BEFORE reading/hashing a candidate, unlike selection."""
    try:
        selected_member(path)
    except LocalCodeError:
        return False
    return True


@contextmanager
def acquire_module(path: str | Path) -> Iterator[ModuleType | None]:
    """None delegates an unrelated/unbound file to its unchanged family loader."""
    package = active_package()
    member = package.member(path) if package is not None else None
    if package is None or member is None:
        yield None
    else:
        with import_member(package, member) as module:
            yield module
