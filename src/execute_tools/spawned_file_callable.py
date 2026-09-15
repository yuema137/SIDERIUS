"""Subprocess-safe calls into externally owned Python plugin files.

Task-composition ``file:`` plugins intentionally live outside the installed
SIDERIUS package.  A callable taken directly from such a dynamically loaded
module cannot be unpickled by a fresh ``multiprocessing`` spawn worker: the
synthetic parent-process module name has no import authority in that worker.

This module keeps the process boundary task-neutral.  Workers receive a
validated file/symbol/content identity, load that exact file themselves, and
only then call the declared symbol.  No task name, dataset shape, or scoring
rule is interpreted here.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import multiprocessing as mp
import re
import sys
import types
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

_MODULE_PREFIX = "siderius_spawned_file_plugin_"


class SpawnedFileCallable(BaseModel):
    """Immutable identity of one callable loaded from an external file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    absolute_path: str
    symbol: str
    content_sha256: str

    @field_validator("absolute_path")
    @classmethod
    def _absolute_existing_file(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("spawned plugin path must be absolute")
        if not path.is_file():
            raise ValueError(f"spawned plugin file does not exist: {value}")
        return str(path.resolve())

    @field_validator("symbol")
    @classmethod
    def _valid_symbol(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError(f"spawned plugin symbol is not an identifier: {value!r}")
        return value

    @field_validator("content_sha256")
    @classmethod
    def _valid_digest(cls, value: str) -> str:
        lowered = value.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", lowered):
            raise ValueError("spawned plugin content_sha256 must be a SHA-256 hex digest")
        return lowered

    @classmethod
    def capture(cls, path: str | Path, symbol: str) -> SpawnedFileCallable:
        """Capture the exact file bytes the parent intends workers to run."""

        resolved = Path(path).resolve(strict=True)
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        return cls(
            absolute_path=str(resolved),
            symbol=symbol,
            content_sha256=digest,
        )


def _load_callable(reference: SpawnedFileCallable) -> Any:
    path = Path(reference.absolute_path)
    source = path.read_bytes()
    actual_digest = hashlib.sha256(source).hexdigest()
    if actual_digest != reference.content_sha256:
        raise RuntimeError(
            "spawned plugin content changed after capture: "
            f"expected {reference.content_sha256}, observed {actual_digest}"
        )

    # Include the path as well as the content identity.  Two plugins may have
    # identical bytes while relying on their own ``__file__`` for sibling
    # resources; sharing one cached module would silently give the second one
    # the first plugin's path.
    cache_identity = hashlib.sha256(
        f"{reference.absolute_path}\0{reference.content_sha256}".encode()
    ).hexdigest()
    module_name = _MODULE_PREFIX + cache_identity
    module = sys.modules.get(module_name)
    if module is None:
        module = types.ModuleType(module_name)
        module.__file__ = str(path)
        module.__package__ = ""
        sys.modules[module_name] = module
        try:
            # Execute the bytes that were just verified, rather than asking a
            # loader to reopen the path after the digest check.  This closes
            # the check/load race and makes the advertised content pin real.
            exec(compile(source, str(path), "exec"), module.__dict__)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

    try:
        target = getattr(module, reference.symbol)
    except AttributeError as exc:
        raise RuntimeError(f"spawned plugin {path} has no symbol {reference.symbol!r}") from exc
    if not callable(target):
        raise TypeError(f"spawned plugin symbol {reference.symbol!r} is not callable")
    return target


def _invoke_file_callable(request: tuple[SpawnedFileCallable, Any]) -> Any:
    reference, argument = request
    return _load_callable(reference)(argument)


def map_spawned_file_callable[T](
    reference: SpawnedFileCallable,
    items: Iterable[T],
    *,
    max_workers: int,
) -> list[Any]:
    """Map an external file callable in fresh ``spawn`` worker processes.

    The importable worker target belongs to SIDERIUS.  The task-owned target
    is resolved from its content-pinned file inside each worker, so it never
    relies on the parent's synthetic ``sys.modules`` entry.
    """

    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    requests = ((reference, item) for item in items)
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=max_workers,
        mp_context=mp.get_context("spawn"),
    ) as executor:
        results = list(executor.map(_invoke_file_callable, requests))
    return results
