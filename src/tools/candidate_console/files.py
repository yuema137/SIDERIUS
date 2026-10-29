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


def open_directory(path: Path) -> int:
    """Open an absolute directory by walking no-follow descriptors from ``/``; caller closes."""
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
    except BaseException:
        os.close(directory)
        raise
    return directory


def write_all(descriptor: int, payload: bytes) -> None:
    """Write every byte; ``os.write`` may return a short count."""
    view = memoryview(payload)
    while view:
        view = view[os.write(descriptor, view) :]


def _file_bytes(value: str, *, owner_only: bool) -> bytes:
    path = canonical(value)
    directory = open_directory(path.parent)
    descriptor = None
    try:
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


def require_owner_only_file(value: str) -> None:
    """Refuse unless ``value`` is a canonical regular file you own with mode 600.

    Checks metadata only (no-follow ``stat`` through no-follow parents); the file
    is never opened, so its contents are neither read nor exposed.
    """
    path = canonical(value)
    directory = open_directory(path.parent)
    try:
        metadata = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
    finally:
        os.close(directory)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise OperationFailure("configuration", "private file requires owner-only mode 600")


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


def parse_credential_payload(payload: bytes) -> dict[str, str]:
    """Parse already-checked private credential bytes as JSON or dotenv.

    Detection rule: a leading UTF-8 BOM is ignored; if the first non-whitespace
    byte is ``{`` the payload must be a strict JSON object of string names to
    string values (``[`` or ``"`` is refused as malformed JSON); otherwise it is
    dotenv text (``KEY=value``, ``export`` prefixes, comments and quotes as
    python-dotenv defines them). Dotenv parsing never interpolates ``${...}``
    references and reads only these bytes, never a second path. Names without
    a value are absent. Errors never carry values or line contents.
    """
    import io

    from dotenv import dotenv_values
    from pydantic import ValidationError

    text: str | None = None
    payload = payload.removeprefix(b"\xef\xbb\xbf")  # editors may write a UTF-8 BOM
    try:
        if payload.lstrip()[:1] in (b"{", b"[", b'"'):
            return TypeAdapter(dict[str, str]).validate_json(payload, strict=True)
        text = payload.decode("utf-8")
    except (ValidationError, UnicodeDecodeError):
        pass  # Raised below, outside the handler: the original text can quote values.
    if text is None:
        raise ValueError("credential file must be a JSON object of strings or UTF-8 dotenv text")
    parsed = dotenv_values(stream=io.StringIO(text), interpolate=False)
    return {name: item for name, item in parsed.items() if item is not None}


def credential_values(value: str | None) -> dict[str, str]:
    """Read the selected private JSON or dotenv source; callers must never expose values."""
    if value is None:
        return {}
    return parse_credential_payload(private_bytes(value))


def credentials(value: str | None, names: tuple[str, ...]) -> dict[str, str]:
    if not names:
        return {}
    try:
        values = credential_values(value)
    except (OSError, ValueError, OperationFailure) as error:
        raise OperationFailure("credentials", "configured credentials are unavailable") from error
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise OperationFailure("credentials", "missing credentials: " + ", ".join(missing))
    return {name: values[name] for name in names}
