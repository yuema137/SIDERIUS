"""Shared finite import namespaces, with captured-byte execution and rollback."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from threading import RLock
from types import ModuleType

from core.local_code.capture import (
    CapturedCodePackage,
    CapturedMember,
    LocalCodeError,
    MemberIdentity,
    module_key,
    sha256,
)

_METADATA = "__siderius_local_code__"
_LOCK = RLock()


def module_identity(module: ModuleType) -> MemberIdentity | None:
    value = getattr(module, _METADATA, None)
    return value if isinstance(value, MemberIdentity) else None


class _FiniteImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Own only one collision-resistant namespace; never search its filesystem."""

    def __init__(self, package: CapturedCodePackage, namespace: str):
        self.package = package
        self.namespace = namespace
        self.members = {module_key(item.pin.member): item for item in package.members}
        self.parents = {""}
        for key in self.members:
            parts = key.split(".")
            self.parents.update(".".join(parts[:index]) for index in range(1, len(parts)))
        self.parents.update(
            key for key, item in self.members.items() if item.pin.member.endswith("/__init__.py")
        )

    def find_spec(
        self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname != self.namespace and not fullname.startswith(self.namespace + "."):
            return None
        key = fullname[len(self.namespace) :].lstrip(".")
        if key not in self.members and key not in self.parents:
            raise LocalCodeError(
                f"code_package: undeclared relative import {key!r}; declare its .py member"
            )
        return importlib.util.spec_from_loader(fullname, self, is_package=key in self.parents)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        key = module.__name__[len(self.namespace) :].lstrip(".")
        member = self.members.get(key)
        if key in self.parents:
            module.__path__ = []
        if member is not None:
            module.__file__ = str(self.package.root / member.pin.member)
            setattr(
                module,
                _METADATA,
                MemberIdentity(package=self.package.identity, member=member.pin.member),
            )
            # Also cover imports delayed until a plugin method is called, when
            # no family acquisition context remains on the stack.
            with _transaction(self.namespace):
                exec(compile(member.source, module.__file__, "exec"), module.__dict__)


def _namespace(package: CapturedCodePackage) -> str:
    location = sha256(str(package.root).encode())
    return f"_siderius_task_{package.identity.digest}_{location}"


@contextmanager
def _transaction(namespace: str) -> Iterator[None]:
    previous = {
        name: module
        for name, module in sys.modules.copy().items()
        if name == namespace or name.startswith(namespace + ".")
    }
    attributes = {name: module.__dict__.copy() for name, module in previous.items()}
    try:
        yield
    except BaseException:
        for name in list(sys.modules):
            if (name == namespace or name.startswith(namespace + ".")) and name not in previous:
                del sys.modules[name]
        for name, module in previous.items():
            sys.modules[name] = module
            for key, value in list(module.__dict__.items()):
                if isinstance(value, ModuleType) and value.__name__.startswith(namespace + "."):
                    if key in attributes[name]:
                        module.__dict__[key] = attributes[name][key]
                    else:
                        del module.__dict__[key]
        raise


@contextmanager
def import_member(package: CapturedCodePackage, member: CapturedMember) -> Iterator[ModuleType]:
    """Keep acquisition AND caller's family checks inside one module transaction."""
    namespace = _namespace(package)
    with _LOCK:
        install_package_finder(package)
        with _transaction(namespace):
            key = module_key(member.pin.member)
            yield importlib.import_module(namespace + ("." + key if key else ""))


def install_package_finder(package: CapturedCodePackage) -> None:
    """Make captured names importable (including unpickling), executing no source."""
    namespace = _namespace(package)
    with _LOCK:
        if not any(
            isinstance(finder, _FiniteImporter) and finder.namespace == namespace
            for finder in sys.meta_path
        ):
            sys.meta_path.insert(0, _FiniteImporter(package, namespace))
