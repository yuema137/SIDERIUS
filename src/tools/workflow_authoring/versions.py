"""Named workflow versions: a typed record file beside the ordinary source.

The record is presentation metadata for Save history. It never changes source
bytes, declaration digests or run identity; the source SHA-256 stays the only
version identity. Version bytes are the existing write-once recovery copies.
"""

import difflib
import hashlib
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from core.durable_io import publish_bytes_atomically

from .models import MAX_SOURCE_BYTES, Digest, Model, VersionName

VERSION_RECORD_SCHEMA = "siderius.workflow-versions/v1"
MAX_VERSION_RECORD_BYTES = 256 * 1024
MAX_VERSIONS = 1000


def version_record_path(source_file: Path) -> Path:
    """The record of ``workflow.py`` is the sibling ``workflow.py.versions.json``."""
    return source_file.with_name(source_file.name + ".versions.json")


class RecordedVersion(Model):
    """One Save (``saved``) or base bytes first observed at a later Save (``observed``)."""

    sha256: Digest
    name: VersionName | None
    recorded_at: AwareDatetime
    origin: Literal["saved", "observed"]

    @model_validator(mode="after")
    def saved_versions_are_named(self):
        if (self.origin == "saved") != (self.name is not None):
            raise ValueError("saved versions are named; observed versions are unnamed")
        return self


class VersionRecord(Model):
    schema_id: Literal["siderius.workflow-versions/v1"] = VERSION_RECORD_SCHEMA
    source_name: str = Field(min_length=1)
    versions: tuple[RecordedVersion, ...] = Field(default=(), max_length=MAX_VERSIONS)

    @model_validator(mode="after")
    def unique_names(self):
        names = [version.name for version in self.versions if version.name is not None]
        if len(names) != len(set(names)):
            raise ValueError("version names must be unique")
        return self


class VersionEntry(Model):
    """Projection row; ``index`` addresses this list, ``recorded=False`` is implicit."""

    index: int
    sha256: Digest
    name: str | None
    recorded_at: AwareDatetime | None
    origin: Literal["saved", "observed", "unrecorded"]
    current: bool
    bytes_available: bool


class VersionList(Model):
    record_path: str
    record_present: bool
    current_sha256: Digest
    next_name: str
    versions: tuple[VersionEntry, ...]


class VersionDetail(Model):
    version: VersionEntry
    source: str | None
    previous: VersionEntry | None
    diff: str | None


class VersionRecordError(ValueError):
    pass


def _regular_owned(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()


def read_record(source_file: Path) -> tuple[VersionRecord | None, int | None]:
    """Return the validated record and its permission bits, or ``(None, None)`` if absent."""
    path = version_record_path(source_file)
    if path.is_symlink():
        raise VersionRecordError("version record must not be a symlink")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not _regular_owned(info) or info.st_mode & 0o7000:
            raise VersionRecordError("version record must be an owned single-link regular file")
        payload = handle.read(MAX_VERSION_RECORD_BYTES + 1)
    if len(payload) > MAX_VERSION_RECORD_BYTES:
        raise VersionRecordError("version record exceeds 256 KiB")
    try:
        record = VersionRecord.model_validate_json(payload)
    except ValidationError as error:
        raise VersionRecordError(
            "version record is not a valid " + VERSION_RECORD_SCHEMA
        ) from error
    if record.source_name != source_file.name:
        raise VersionRecordError("version record belongs to a different source file")
    return record, stat.S_IMODE(info.st_mode)


def next_name(record: VersionRecord | None) -> str:
    """Smallest unused ``vN`` with N at least one more than the number of named Saves."""
    used = {version.name for version in record.versions if version.name} if record else set()
    number = len(used) + 1
    while f"v{number}" in used:
        number += 1
    return f"v{number}"


def appended_record(
    source_file: Path,
    record: VersionRecord | None,
    base_sha256: str,
    saved_sha256: str,
    name: str | None,
    now: datetime | None = None,
) -> tuple[VersionRecord, str]:
    """Record a Save; unrecorded base bytes first become an unnamed observed version."""
    now = now or datetime.now(UTC)
    record = record or VersionRecord(source_name=source_file.name)
    name = name if name is not None else next_name(record)
    if any(version.name == name for version in record.versions):
        raise VersionRecordError(f"version name {name!r} is already used")
    added: list[RecordedVersion] = []
    if not record.versions or record.versions[-1].sha256 != base_sha256:
        added.append(
            RecordedVersion(sha256=base_sha256, name=None, recorded_at=now, origin="observed")
        )
    added.append(RecordedVersion(sha256=saved_sha256, name=name, recorded_at=now, origin="saved"))
    if len(record.versions) + len(added) > MAX_VERSIONS:
        raise VersionRecordError(
            f"version record holds {MAX_VERSIONS} versions; archive it externally to continue"
        )
    return VersionRecord(source_name=record.source_name, versions=(*record.versions, *added)), name


def encode_record(record: VersionRecord) -> bytes:
    payload = (record.model_dump_json(indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_VERSION_RECORD_BYTES:
        raise VersionRecordError("version record would exceed 256 KiB")
    return payload


def write_record(source_file: Path, payload: bytes, mode: int | None) -> None:
    """Atomic temp + rename beside the source; preserves existing permission bits."""
    path = version_record_path(source_file)
    if path.is_symlink():
        raise VersionRecordError("version record must not be a symlink")
    publish_bytes_atomically(str(path), payload, mode=mode)


def read_recovery_copy(recovery_directory: Path, sha256: str) -> bytes | None:
    """Exact saved bytes from a recovery copy, or None if absent, unsafe or different."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        return None
    path = recovery_directory / (sha256 + ".py")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        if not _regular_owned(os.fstat(handle.fileno())):
            return None
        payload = handle.read(MAX_SOURCE_BYTES + 1)
    if hashlib.sha256(payload).hexdigest() != sha256:
        return None
    return payload


def project_versions(
    record: VersionRecord | None,
    current_sha256: str,
    available: frozenset[str],
) -> tuple[VersionEntry, ...]:
    """Chronological rows; current bytes not last-recorded appear as one unrecorded row."""
    recorded = record.versions if record else ()
    rows = [
        VersionEntry(
            index=index,
            sha256=version.sha256,
            name=version.name,
            recorded_at=version.recorded_at,
            origin=version.origin,
            current=False,
            bytes_available=version.sha256 in available,
        )
        for index, version in enumerate(recorded)
    ]
    if rows and rows[-1].sha256 == current_sha256:
        rows[-1] = rows[-1].model_copy(update={"current": True})
    else:
        rows.append(
            VersionEntry(
                index=len(rows),
                sha256=current_sha256,
                name=None,
                recorded_at=None,
                origin="unrecorded",
                current=True,
                bytes_available=True,
            )
        )
    return tuple(rows)


def version_diff(previous: bytes, current: bytes, previous_label: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            previous.decode("utf-8", errors="replace").splitlines(True),
            current.decode("utf-8", errors="replace").splitlines(True),
            fromfile=previous_label,
            tofile=label,
        )
    )


def recorded_name(source_file: Path, sha256: str) -> str | None:
    """Display-only name of the latest Save of ``sha256``; never a run identity input.

    An absent, unreadable or invalid record yields None: the caller still binds
    the SHA-256, and the history view reports the record refusal itself.
    """
    try:
        record = read_record(source_file)[0]
    except (OSError, VersionRecordError):
        return None
    names = [v.name for v in record.versions if v.sha256 == sha256] if record else []
    return next((name for name in reversed(names) if name is not None), None)
