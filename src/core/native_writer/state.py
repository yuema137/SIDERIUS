"""Private bounded no-follow state beside the explicitly selected workspace."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from .models import WriterModel, WriterRefusal

_LIMIT = 4096
Model = TypeVar("Model", bound=WriterModel)


def canonical_workspace(workspace: str | Path) -> Path:
    path = Path(workspace).expanduser().resolve()
    if path == path.parent or not path.parent.is_dir():
        raise WriterRefusal("writer_parent_required")
    return path


def _private(info: os.stat_result, *, directory: bool) -> None:
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected_type(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or (not directory and info.st_nlink != 1)
    ):
        raise WriterRefusal("unsafe_writer_state")


class WriterState:
    """Own only one control-directory descriptor, never an execution decision."""

    def __init__(self, workspace: str | Path, *, create: bool):
        self.workspace = canonical_workspace(workspace)
        self.path = self.workspace.parent / f".{self.workspace.name}.siderius-writer"
        if create:
            with suppress(FileExistsError):
                self.path.mkdir(mode=0o700)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _private(os.fstat(self.fd), directory=True)
        except BaseException:
            os.close(self.fd)
            raise

    def close(self) -> None:
        os.close(self.fd)

    def open_lock(self, *, create: bool = True) -> int:
        # The inode is permanent: replacing it could admit two independent owners.
        flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
        fd = os.open("writer.lock", flags, 0o600, dir_fd=self.fd)
        try:
            _private(os.fstat(fd), directory=False)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def read(self, name: str, model: type[Model]) -> Model | None:
        payload = self.read_bytes(name)
        return model.model_validate_json(payload) if payload is not None else None

    def read_bytes(self, name: str) -> bytes | None:
        """Return the same bounded bytes used for parsing and identity checks."""
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        except FileNotFoundError:
            return None
        try:
            _private(os.fstat(fd), directory=False)
            payload = os.read(fd, _LIMIT + 1)
            if len(payload) > _LIMIT:
                raise WriterRefusal("writer_state_limit")
            return payload
        finally:
            os.close(fd)

    def publish(self, name: str, value: WriterModel) -> None:
        """Write once without exposing a partially serialized accepted record."""
        data = value.model_dump_json().encode()
        if len(data) > _LIMIT:
            raise WriterRefusal("writer_state_limit")
        temporary = f".pending-{uuid4()}"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=self.fd,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Hardlink publication is atomic and cannot overwrite a competing claim.
            os.link(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        finally:
            os.unlink(temporary, dir_fd=self.fd)
        os.fsync(self.fd)

    def remove(self, name: str, expected: WriterModel) -> None:
        if self.read(name, type(expected)) != expected:
            raise WriterRefusal("writer_state_changed")
        os.unlink(name, dir_fd=self.fd)
        os.fsync(self.fd)
