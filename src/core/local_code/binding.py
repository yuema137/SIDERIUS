"""Run decisions and the small optional acquisition boundary used by families."""

from __future__ import annotations

import os
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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
from core.local_code.importing import import_member, install_package_finder


class _Unbound(Enum):
    VALUE = "no-active-decision"


UNBOUND = _Unbound.VALUE


@dataclass(frozen=True)
class _Inherited:
    package: CapturedCodePackage


_ACTIVE: ContextVar[CapturedCodePackage | _Inherited | None | _Unbound] = ContextVar(
    "local_code", default=UNBOUND
)


def active_package() -> CapturedCodePackage | None:
    value = _ACTIVE.get()
    if value is UNBOUND:
        from core.local_code.transport import read_inherited_package

        inherited = read_inherited_package(os.environ)
        if inherited is not None:
            value = _Inherited(inherited)
            _ACTIVE.set(value)
    if isinstance(value, _Inherited):
        return value.package
    return value if isinstance(value, CapturedCodePackage) else None


@contextmanager
def bind_code_package(package: CapturedCodePackage | None) -> Iterator[None]:
    """Restore the exact preceding decision; this does not manage family registries."""
    previous = _ACTIVE.get()
    if isinstance(previous, _Inherited):
        if package is None or package.identity != previous.package.identity:
            raise LocalCodeError(
                "code_package declaration is absent/different from inherited parent pin"
            )
        value: CapturedCodePackage | _Inherited | None = previous
    else:
        value = package
    token = _ACTIVE.set(value)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


@contextmanager
def root_code_scope() -> Iterator[None]:
    """An actual root entry explicitly suppresses stale inherited transport."""
    token = _ACTIVE.set(None)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def package_subprocess_env(environ: MutableMapping[str, str]) -> None:
    from core.local_code.failure import FAILURE_ENV, read_failure_channel
    from core.local_code.transport import DIGEST_ENV, MANIFEST_ENV, write_transport

    package = active_package()
    if package is not None:
        write_transport(package, environ)
        if isinstance(_ACTIVE.get(), _Inherited):
            channel = read_failure_channel(environ)
            if channel is not None and channel.package_digest != package.identity.digest:
                raise LocalCodeError("code_package inherited failure channel differs from package")
        else:
            environ.pop(FAILURE_ENV, None)  # A new root cannot reuse ambient launch state.
    elif _ACTIVE.get() is None:
        environ.pop(MANIFEST_ENV, None)
        environ.pop(DIGEST_ENV, None)
        environ.pop(FAILURE_ENV, None)
    elif FAILURE_ENV in environ:
        raise LocalCodeError("code_package failure channel is present without package transport")


def bootstrap_code_package(manifest_path: str | None = None, digest: str | None = None) -> None:
    """Verify/install captured names before imports or spawn-pool unpickling.

    Pool owners pass the same shared-env carrier as serializable initargs;
    this does not mutate os.environ, start workers, or execute plugin source.
    """
    try:
        _bootstrap_code_package(manifest_path, digest)
    except LocalCodeError as exc:
        _report_bootstrap_refusal(exc)
        raise


def _report_bootstrap_refusal(exc: LocalCodeError) -> None:
    """Pool initializer errors otherwise become an untyped BrokenProcessPool."""
    from core.local_code.failure import publish_failure, read_failure_channel

    if _ACTIVE.get() is None or isinstance(_ACTIVE.get(), CapturedCodePackage):
        return
    try:
        channel = read_failure_channel(os.environ)
        if channel is not None:
            publish_failure(channel, exc)
    except (OSError, LocalCodeError):
        # Retain the original refusal. Broken report storage cannot guarantee
        # nested-pool diagnosis; never relabel every BrokenProcessPool instead.
        pass


def _bootstrap_code_package(manifest_path: str | None, digest: str | None) -> None:
    from core.local_code.failure import read_failure_channel

    inherited_decision = _ACTIVE.get() is UNBOUND or isinstance(_ACTIVE.get(), _Inherited)
    channel = read_failure_channel(os.environ) if inherited_decision else None
    if (
        channel is not None
        and (manifest_path is not None or digest is not None)
        and digest != channel.transport_digest
    ):
        raise LocalCodeError("code_package initializer transport differs from inherited channel")
    if manifest_path is None and digest is None:
        package = active_package()
    else:
        from core.local_code.transport import DIGEST_ENV, MANIFEST_ENV, read_inherited_package

        carrier = {MANIFEST_ENV: manifest_path or "", DIGEST_ENV: digest or ""}
        package = read_inherited_package(carrier)
        previous = _ACTIVE.get()
        if (
            isinstance(previous, _Inherited)
            and package is not None
            and package.identity != previous.package.identity
        ):
            raise LocalCodeError("code_package initializer differs from inherited parent pin")
        if package is not None:
            _ACTIVE.set(_Inherited(package))
    if package is not None:
        if channel is not None and channel.package_digest != package.identity.digest:
            raise LocalCodeError("code_package initializer channel differs from parent pin")
        install_package_finder(package)


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
    existing = active_package()
    inherited = isinstance(_ACTIVE.get(), _Inherited)
    package = None
    if raw is not None:
        try:
            declaration = CodePackageDeclaration.model_validate(raw)
            root = (Path(manifest_dir) / declaration.root).resolve()
            matches = (
                existing is not None
                and root == existing.root
                and declaration.files == tuple(member.pin.member for member in existing.members)
            )
            if inherited and not matches:
                raise LocalCodeError("code_package declaration differs from inherited parent pin")
            package = existing if matches else capture_package(declaration, manifest_dir)
        except ValueError as exc:
            raise LocalCodeError(f"code_package: {exc}") from exc
    with bind_code_package(package):
        yield package


def scan_candidate_allowed(path: str | Path) -> bool:
    """Discovery calls this BEFORE reading/hashing a candidate, unlike selection."""
    package = active_package()  # Transport refusal is NOT discovery tolerance.
    try:
        if package is not None:
            package.member(path)
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
