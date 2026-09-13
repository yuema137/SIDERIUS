"""Run decisions and the small optional acquisition boundary used by families."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from pathlib import Path
from types import ModuleType

from core.local_code.capture import CapturedCodePackage, CapturedMember, LocalCodeError
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
