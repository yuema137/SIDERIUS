"""No-follow fixed-file access and bounded decoding for the local trusted store."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import BaseModel

from core.control_json import JSON_LIMIT, ControlOverflow, encode_control
from core.durable_io import publish_bytes_atomically, publish_bytes_write_once

from .models import OperationFailure


def canonical(value: str) -> Path:
    path = Path(value)
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise OperationFailure("path", "cannot resolve selected path") from error
    if not path.is_absolute() or str(path) != value or path != resolved:
        raise OperationFailure("path", "use canonical absolute paths without aliases")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise OperationFailure("path", "symlink components are not allowed")
    return path


def overlap(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


@contextmanager
def directory(path: Path) -> Iterator[int]:
    """Pin every directory while traversing, refusing symlinks at each component."""
    if not path.is_absolute() or ".." in path.parts:
        raise OperationFailure("path", "expected an absolute confined directory")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def private(metadata: os.stat_result, *, directory: bool) -> None:
    expected = 0o700 if directory else 0o600
    valid_type = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if (
        not valid_type
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != expected
    ):
        raise OperationFailure("permissions", f"operation state requires owned mode {expected:o}")


def private_directory(path: Path, *, create: bool = False) -> None:
    if create:
        with directory(path.parent) as parent, suppress(FileExistsError):
            os.mkdir(path.name, mode=0o700, dir_fd=parent)
    with directory(path) as descriptor:
        private(os.fstat(descriptor), directory=True)


@contextmanager
def open_file(path: Path, *, private_file: bool = False) -> Iterator[int]:
    with directory(path.parent) as parent:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OperationFailure("integrity", "expected a regular file")
        if private_file:
            private(metadata, directory=False)
        yield descriptor
    finally:
        os.close(descriptor)


def read_bytes(path: Path, *, private_file: bool = False) -> bytes:
    with open_file(path, private_file=private_file) as descriptor:
        if os.fstat(descriptor).st_size > JSON_LIMIT:
            raise OperationFailure("record_size", "JSON record exceeds 4 MiB")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            payload = stream.read(JSON_LIMIT + 1)
        if len(payload) > JSON_LIMIT:
            raise OperationFailure("record_size", "JSON record exceeds 4 MiB")
        return payload


def read_model[Model: BaseModel](
    path: Path, model: type[Model], *, private_file: bool = False
) -> Model:
    return model.model_validate_json(read_bytes(path, private_file=private_file))


def encode(model: BaseModel) -> bytes:
    """Encode a record once, refusing bytes that the bounded reader cannot load."""
    try:
        return encode_control(model)
    except ControlOverflow as error:
        raise OperationFailure("record_size", "JSON record exceeds 4 MiB") from error


def publish(path: Path, model: BaseModel, *, replace: bool = False) -> None:
    publish_encoded(path, encode(model), replace=replace)


def publish_encoded(path: Path, payload: bytes, *, replace: bool = False) -> None:
    """Publish bytes already admitted by encode through the private directory owner."""
    with directory(path.parent) as descriptor:
        private(os.fstat(descriptor), directory=True)
        # Keep the existing durable publisher while pinning its target directory.
        target = f"/proc/self/fd/{descriptor}/{path.name}"
        (publish_bytes_atomically if replace else publish_bytes_write_once)(target, payload)
