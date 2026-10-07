"""Regular-file identity checks shared by artifact readers, without deserialization."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import BinaryIO, Literal


class FileIdentityError(ValueError):
    def __init__(self, reason: Literal["not_regular", "size_mismatch"]):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class FileSnapshot:
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int


@contextmanager
def open_identity_file(path: str, *, require_no_follow: bool = False) -> Iterator[BinaryIO]:
    """Keep one unbuffered fd; nonblocking open prevents FIFO startup hangs."""
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if require_no_follow and not no_follow:
        raise OSError("file identity requires O_NOFOLLOW support")
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | no_follow)
    try:
        handle = os.fdopen(descriptor, "rb", buffering=0)
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        yield handle


def regular_file_snapshot(handle: BinaryIO, *, expected_size: int | None = None) -> FileSnapshot:
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode):
        raise FileIdentityError("not_regular")
    if expected_size is not None and info.st_size != expected_size:
        raise FileIdentityError("size_mismatch")
    return FileSnapshot(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def path_matches_snapshot(path: str, snapshot: FileSnapshot) -> bool:
    """A held fd alone cannot detect atomic replacement of its pathname."""
    info = os.stat(path, follow_symlinks=False)
    return (info.st_dev, info.st_ino) == (snapshot.device, snapshot.inode)
