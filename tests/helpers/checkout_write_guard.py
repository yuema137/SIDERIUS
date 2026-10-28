"""Fail a test the moment it writes, removes or renames a git-tracked file.

CI bulk shards run concurrently in ONE checkout. A test that edits a tracked
file "temporarily" (write, assert, restore) races every sibling shard that
reads that file: #973 failed an unrelated shard with "selected input changed:
task.manifest" because a resume test appended a newline to the tracked
quickstart manifest. Restoring in ``finally`` does not help; the window is the
defect. This guard turns every such edit into an immediate, attributable
failure in the test that made it, whichever file it touches.

Mechanism: one process-wide ``sys.addaudithook`` (audit hooks cannot be
removed, so it is installed once and dispatches to registered guards). A guard
is armed only while a test runs (``watching``) and inspects these events:

* ``open`` with any write/append/create/truncate/update mode or flag;
* ``os.remove`` (also raised by ``os.unlink``);
* ``os.rename`` (also raised by ``os.replace``), source or destination;
* ``os.truncate`` by path;
* ``shutil.rmtree`` of a tracked file's directory or any ancestor.

Limits, by construction: spawned subprocesses do not inherit the hook (a
child ``git checkout`` or shell ``echo >`` is invisible; the CI harness's
before/after digest in ``tools.ci.execution`` is the backstop), and a
relative path paired with ``dir_fd`` is not resolved.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WATCHED = frozenset({"open", "os.remove", "os.rename", "os.truncate", "shutil.rmtree"})


class CheckoutWriteEscape(BaseException):
    """A test mutated a tracked checkout file.

    ``BaseException`` for the same reason as ``RealSubprocessEscape`` in
    ``tests/unit/conftest.py``: production code under test wraps bodies in
    ``except Exception``, which would swallow the signal into a status value.
    """


def tracked_paths(root: Path) -> frozenset[str]:
    """Absolute paths of every file ``git ls-files`` reports under ``root``.

    Raises ``RuntimeError`` when git cannot answer: a guard that silently
    disarms itself would report a clean suite it never checked.
    """
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"checkout write guard cannot list tracked files under {root}: {exc}. "
            "Run the suite from a git checkout with git on PATH."
        ) from exc
    names = [name for name in os.fsdecode(listing).split("\0") if name]
    bases = {os.path.abspath(root), os.path.realpath(root)}
    return frozenset(os.path.join(base, name) for base in bases for name in names)


def _parents(paths: frozenset[str]) -> frozenset[str]:
    dirs: set[str] = set()
    for path in paths:
        parent = os.path.dirname(path)
        while parent not in dirs and parent != os.path.dirname(parent):
            dirs.add(parent)
            parent = os.path.dirname(parent)
    return frozenset(dirs)


def _absolute(path: object, dir_fd: object = None) -> str | None:
    """Absolute spelling of a path argument, or None when it cannot be named."""
    if isinstance(path, int) or not isinstance(path, (str, bytes, os.PathLike)):
        return None  # a file descriptor
    text = os.fsdecode(path)
    if dir_fd not in (None, -1) and not os.path.isabs(text):
        return None  # relative to an open directory; not resolvable here
    return os.path.abspath(text)


def _targets(event: str, args: tuple) -> tuple[str | None, ...]:
    """Paths an audited event would mutate; empty when it is not a mutation."""
    if event == "open":
        path, mode, flags = args
        writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        )
        return (_absolute(path),) if writes else ()
    if event == "os.rename":
        src, dst, src_fd, dst_fd = args
        return (_absolute(src, src_fd), _absolute(dst, dst_fd))
    if event in ("os.remove", "shutil.rmtree"):
        return (_absolute(args[0], args[1]),)
    if event == "os.truncate":
        return (_absolute(args[0]),)
    return ()


class CheckoutWriteGuard:
    """Refuses mutations of ``tracked`` files while a test is being watched."""

    def __init__(self, tracked: frozenset[str]) -> None:
        self._tracked = tracked
        self._tracked_dirs = _parents(tracked)
        self._test_id: str | None = None

    @contextmanager
    def watching(self, test_id: str) -> Iterator[None]:
        """Arm the guard for ``test_id`` for the duration of the block."""
        previous, self._test_id = self._test_id, test_id
        try:
            yield
        finally:
            self._test_id = previous

    def audit(self, event: str, args: tuple) -> None:
        if self._test_id is None or event not in _WATCHED:
            return
        protected = self._tracked_dirs if event == "shutil.rmtree" else frozenset()
        for path in _targets(event, args):
            if path is not None and (path in self._tracked or path in protected):
                raise CheckoutWriteEscape(
                    f"test {self._test_id} attempted {event} on tracked checkout path "
                    f"{path}. Concurrent CI shards share this checkout, so even a "
                    "restored edit can fail another test (#973). Copy the file "
                    "under tmp_path and mutate the copy, or mark the test "
                    "@pytest.mark.allow_checkout_writes(reason=...) if the edit "
                    "is the behaviour under test."
                )


_GUARDS: list[CheckoutWriteGuard] = []
_HOOK_INSTALLED = False


def _dispatch(event: str, args: tuple) -> None:
    if event in _WATCHED:
        for guard in tuple(_GUARDS):
            guard.audit(event, args)


def register(guard: CheckoutWriteGuard) -> None:
    """Route audit events to ``guard``; installs the process hook once."""
    global _HOOK_INSTALLED
    if not _HOOK_INSTALLED:
        sys.addaudithook(_dispatch)
        _HOOK_INSTALLED = True
    _GUARDS.append(guard)


def unregister(guard: CheckoutWriteGuard) -> None:
    _GUARDS.remove(guard)
