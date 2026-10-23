"""Bounded private operator files; no browser-supplied paths."""

import os
import stat
from pathlib import Path

from pydantic import TypeAdapter

from tools.candidate_operations.models import OperationFailure

LIMIT = 256 * 1024


def canonical(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or str(path) != value or path.resolve() != path:
        raise OperationFailure("configuration", "configured paths must be canonical")
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise OperationFailure("configuration", "configured paths must not contain symlinks")
    return path


def _file_bytes(value: str, *, owner_only: bool) -> bytes:
    path = canonical(value)
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    descriptor = None
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (
                owner_only
                and (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600)
            )
            or metadata.st_size > LIMIT
        ):
            raise OperationFailure("configuration", "private file requires owner-only mode 600")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            payload = stream.read(LIMIT + 1)
        if len(payload) > LIMIT:
            raise OperationFailure("configuration", "private file exceeds limit")
        return payload
    finally:
        os.close(directory)
        if descriptor is not None:
            os.close(descriptor)


def private_bytes(value: str) -> bytes:
    return _file_bytes(value, owner_only=True)


def config_bytes(value: str) -> bytes:
    return _file_bytes(value, owner_only=False)


def token(value: str) -> str:
    import base64
    import re

    text = private_bytes(value).decode("ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,256}", text):
        raise OperationFailure("configuration", "token must encode at least 32 random bytes")
    if len(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))) < 32:
        raise OperationFailure("configuration", "token is too short")
    return text


def credentials(value: str | None, names: tuple[str, ...]) -> dict[str, str]:
    if not names:
        return {}
    try:
        values = (
            {}
            if value is None
            else TypeAdapter(dict[str, str]).validate_json(private_bytes(value), strict=True)
        )
    except (OSError, ValueError) as error:
        raise OperationFailure("credentials", "configured credentials are unavailable") from error
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise OperationFailure("credentials", "missing credentials: " + ", ".join(missing))
    return {name: values[name] for name in names}
