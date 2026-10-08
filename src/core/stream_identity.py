"""Stream file identity without retaining a second full artifact in memory."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import BinaryIO


def stream_file_identity(
    handle: BinaryIO,
    *,
    byte_limit: int | None = None,
    check_budget: Callable[[], None] | None = None,
) -> tuple[str, int]:
    """Hash from the current position; callers own the handle and any deadline."""
    digest = hashlib.sha256()
    size = 0
    while True:
        if check_budget is not None:
            check_budget()
        read_size = 1024 * 1024
        if byte_limit is not None:
            read_size = min(read_size, byte_limit - size + 1)
        chunk = handle.read(read_size)
        if not chunk:
            break
        size += len(chunk)
        if byte_limit is not None and size > byte_limit:
            raise ValueError("artifact exceeds its declared byte size")
        digest.update(chunk)
    if check_budget is not None:
        check_budget()
    return digest.hexdigest(), size
