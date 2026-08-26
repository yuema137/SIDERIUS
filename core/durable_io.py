"""Durable file publication — the three write shapes SIDERIUS persistence uses.

Consolidates, without redesigning, three mechanisms that already existed as
separate copies in the repository:

* **atomic replace** — ``core/wave_records.py::_write_derived`` and
  ``execute_tools/per_file_best.py::_atomic_write_bytes``: same-directory
  temp file, ``flush`` + ``fsync``, ``os.replace``. A reader sees the old
  file or the new one, never a torn one, and a failed publish leaves the
  previous version untouched.
* **write-once** — ``core/run_invariants.py::write_run_invariants``: same
  temp file, published with ``os.link``, which FAILS when the target exists
  instead of overwriting it. First writer wins; a second writer receives
  ``FileExistsError`` and must decide, by name, what that means.
* **durable append** — ``core/wave_records.py::_append_canonical``: append,
  ``flush``, ``fsync``. The canonical evidence is on disk before any derived
  view that describes it can be.

Two details are load-bearing and deliberately uniform here:

1. Every payload is serialised to bytes BEFORE any file is opened, so a
   serialisation failure leaves the on-disk artifact exactly as it was.
   ``json.dump`` straight into an ``open(path, "w")`` truncates the target
   first and then fails half-way — which is how a validation error in the
   tuner's output writer could leave a truncated ``run_output`` behind.
2. Temp files are dot-prefixed (``.<basename>.XXXX.tmp``) so that no
   ``summary_*.json`` / ``run_output_*.json`` glob anywhere in the repository
   can observe a half-written file as if it were a finished one.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from typing import Any


def _open_temp_beside(path: str) -> tuple[int, str]:
    """A temp file in the target's directory, hidden from ``*.json`` globs."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    basename = os.path.basename(path)
    return tempfile.mkstemp(dir=directory, prefix=f".{basename}.", suffix=".tmp")


def _write_durably(fd: int, payload: bytes) -> None:
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def publish_bytes_atomically(path: str, payload: bytes) -> None:
    """Replace ``path`` with ``payload`` atomically (temp + fsync + ``os.replace``).

    Raises:
        OSError: the payload could not be made durable or published. The
            previous version of ``path`` (if any) is untouched and the temp
            file is removed.
    """
    fd, tmp_path = _open_temp_beside(path)
    try:
        _write_durably(fd, payload)
        os.replace(tmp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)


def publish_bytes_write_once(path: str, payload: bytes) -> None:
    """Create ``path`` with ``payload`` exactly once (temp + fsync + ``os.link``).

    Raises:
        FileExistsError: ``path`` already exists. It is NOT modified; the
            caller owns the decision of what a second write means.
        OSError: any other durability or link failure. The temp file is
            removed in every case.
    """
    fd, tmp_path = _open_temp_beside(path)
    try:
        _write_durably(fd, payload)
        os.link(tmp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)


def encode_json(
    obj: Any,
    *,
    indent: int | None = None,
    ensure_ascii: bool = True,
    default: Callable[[Any], Any] | None = None,
    trailing_newline: bool = False,
) -> bytes:
    """Serialise ``obj`` to UTF-8 bytes with ``json.dump``-compatible options.

    Kept separate from the publish functions so a caller can hash or
    compare the exact bytes it is about to publish.
    """
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii, default=default)
    if trailing_newline:
        text += "\n"
    return text.encode("utf-8")


def publish_json_atomically(
    path: str,
    obj: Any,
    *,
    indent: int | None = None,
    ensure_ascii: bool = True,
    default: Callable[[Any], Any] | None = None,
    trailing_newline: bool = False,
) -> None:
    """``json.dump(obj, open(path, "w"))``, made atomic and serialise-first.

    The keyword surface mirrors ``json.dump`` so a call site that used to
    write ``json.dump(x, f, indent=4, ensure_ascii=False)`` produces the
    SAME bytes through this function — the on-disk format every existing
    reader consumes is unchanged; only the write mechanism is.
    """
    payload = encode_json(
        obj,
        indent=indent,
        ensure_ascii=ensure_ascii,
        default=default,
        trailing_newline=trailing_newline,
    )
    publish_bytes_atomically(path, payload)


def _ends_with_newline(path: str) -> bool | None:
    """``True``/``False`` for a non-empty file, ``None`` if absent or empty."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                return None
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) == b"\n"
    except FileNotFoundError:
        return None


def append_line_durably(path: str, line: str) -> None:
    """Append one line and ``fsync`` it before returning.

    A file whose last write was torn (no terminating newline — a crash
    mid-append) is repaired by starting the new line on a fresh line, so
    the torn fragment stays a fragment instead of gluing itself onto the
    next record. ``line`` must not contain a newline of its own.

    Raises:
        ValueError: ``line`` contains a newline.
        OSError: the append could not be made durable.
    """
    if "\n" in line or "\r" in line:
        raise ValueError("append_line_durably: a line may not contain a newline")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    prefix = "\n" if _ends_with_newline(path) is False else ""
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(prefix + line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
