"""The checkout write guard fails a test that mutates a git-tracked file (#973).

Each case uses a guard bound to a throwaway git repository, so a broken guard
mutates only that repository. The two session-wiring cases touch the real
checkout only through an append-mode open that is closed without writing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers.checkout_write_guard import (
    GUARD_KEY,
    CheckoutWriteEscape,
    CheckoutWriteGuard,
    fail_report_on_violation,
    register,
    tracked_paths,
    unregister,
)

_CHECKOUT = Path(__file__).resolve().parents[3]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "pkg" / "tracked.yaml").write_text("a: 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


@pytest.fixture
def armed(repo: Path) -> Iterator[CheckoutWriteGuard]:
    guard = CheckoutWriteGuard(tracked_paths(repo))
    register(guard)
    try:
        with guard.watching("test-under-guard"):
            yield guard
    finally:
        unregister(guard)


@pytest.fixture
def session_guard(request: pytest.FixtureRequest) -> CheckoutWriteGuard:
    """The conftest guard. A test tripping it on purpose must drain it in its
    body: the call-phase report is made before fixture teardown."""
    return request.config.stash[GUARD_KEY]


_MUTATIONS: dict[str, Callable[[Path, Path], object]] = {
    "open-append": lambda t, o: open(t, "a").close(),
    "open-update": lambda t, o: open(t, "r+").close(),
    "path-write_text": lambda t, o: t.write_text("a: 2\n", encoding="utf-8"),
    "os-open-flags": lambda t, o: os.close(os.open(t, os.O_WRONLY)),
    "write-via-symlink": lambda t, o: (o.symlink_to(t), o.write_text("x", encoding="utf-8")),
    "os-truncate": lambda t, o: os.truncate(t, 0),
    "os-unlink": lambda t, o: os.unlink(t),
    "os-remove": lambda t, o: os.remove(t),
    "rename-from": lambda t, o: os.rename(t, o),
    "replace-onto": lambda t, o: (o.write_text("x", encoding="utf-8"), os.replace(o, t)),
    "rmtree-parent": lambda t, o: shutil.rmtree(t.parent),
}


@pytest.mark.parametrize("mutate", list(_MUTATIONS.values()), ids=list(_MUTATIONS))
@pytest.mark.usefixtures("armed")
def test_every_mutation_route_to_a_tracked_file_is_refused(repo: Path, tmp_path: Path, mutate):
    """Each route is a distinct audit event or argument shape (mode string,
    os.open flags, an untracked symlink to a tracked file, rename source vs
    destination, ancestor directory).

    Fails as: the route reaches the tracked file unrefused, so the test either
    sees no CheckoutWriteEscape or finds the file's bytes changed.
    """
    tracked = repo / "pkg" / "tracked.yaml"
    with pytest.raises(CheckoutWriteEscape, match="test-under-guard"):
        mutate(tracked, tmp_path / "other.yaml")
    assert tracked.read_text(encoding="utf-8") == "a: 1\n"


@pytest.mark.usefixtures("armed")
def test_reads_and_untracked_writes_pass(repo: Path, tmp_path: Path):
    """The guard must not trip on the ordinary traffic of every test.

    Fails as: a read of a tracked file, or a write/rename/rmtree of an
    untracked path (tmp_path or an untracked file beside a tracked one),
    raises CheckoutWriteEscape -- a false positive across the whole suite.
    """
    assert (repo / "pkg" / "tracked.yaml").read_text(encoding="utf-8") == "a: 1\n"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "f.txt").write_text("x", encoding="utf-8")
    os.replace(scratch / "f.txt", scratch / "g.txt")
    shutil.rmtree(scratch)
    (repo / "pkg" / "untracked.log").write_text("x", encoding="utf-8")
    os.unlink(repo / "pkg" / "untracked.log")


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_worker_thread_escape_still_fails_the_test(armed: CheckoutWriteGuard, repo: Path):
    """The raise lands in the writing thread, not in the test.

    Fails as: the refused write is not recorded, so fail_report_on_violation
    leaves a passing report and the test that owns the thread stays green.
    """
    tracked = repo / "pkg" / "tracked.yaml"
    worker = threading.Thread(target=tracked.write_text, args=("a: 2\n",))
    worker.start()
    worker.join()
    report = SimpleNamespace(failed=False, outcome="passed", longrepr=None)
    fail_report_on_violation(armed, report)
    assert report.outcome == "failed" and "tracked.yaml" in report.longrepr
    assert tracked.read_text(encoding="utf-8") == "a: 1\n"


def test_a_non_git_root_fails_loudly(tmp_path: Path):
    """No git listing must stop the session, never disarm the guard.

    Fails as: tracked_paths returns an empty set and every write passes.
    """
    with pytest.raises(RuntimeError, match="cannot list tracked files"):
        tracked_paths(tmp_path)


def test_the_session_guard_is_armed_for_the_real_checkout(session_guard: CheckoutWriteGuard):
    """conftest must arm the guard around each test of this checkout.

    Fails as: pytest_sessionstart/pytest_runtest_protocol stop wiring the
    guard, so this append-mode open of a tracked file succeeds (it writes
    nothing, so the checkout is unchanged either way).
    """
    with pytest.raises(CheckoutWriteEscape, match=r"pyproject\.toml"):
        open(_CHECKOUT / "pyproject.toml", "a").close()
    assert session_guard.take_violations(), "the refusal was not recorded for the report"


@pytest.mark.allow_checkout_writes(reason="proves the opt-out marker disarms the guard")
def test_the_marker_disarms_the_guard():
    """The documented opt-out must actually opt out.

    Fails as: the marker is ignored and this append-mode open (no bytes
    written) raises CheckoutWriteEscape.
    """
    open(_CHECKOUT / "pyproject.toml", "a").close()


@pytest.mark.allow_checkout_writes
def test_a_marker_without_reason_does_not_disarm(session_guard: CheckoutWriteGuard):
    """An opt-out must state why; a bare marker is not one.

    Fails as: the bare marker disarms the guard and the open succeeds.
    """
    with pytest.raises(CheckoutWriteEscape):
        open(_CHECKOUT / "pyproject.toml", "a").close()
    assert session_guard.take_violations()
