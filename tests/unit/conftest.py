"""Unit tests may never launch the real training or inference scripts.

A stub that stops intercepting does not fail — it lets the real thing
run. PR A hit this when the pre-flight call site moved and six test
files kept stubbing the old entry point; the suite sat for minutes
instead of erroring. B-C2a hit it again, at larger scale: routing the
plain GPU branch off ``subprocess.run`` silently invalidated 58 stubs
across six files, and real ``train_engine_sandbox.py`` processes
launched out of the unit suite.

Both times the failure was silent and expensive, and both times a
name-based check would have missed it: the tests *were* patching
something, just no longer the thing that runs. So this guard watches the
**effect** rather than the name — if an argv about to be executed names
a real heavy script, the test fails immediately, before the work starts.

This is test infrastructure. It changes no production behaviour, and it
does not care which seam production currently uses, so it keeps working
when that seam moves again.
"""

from __future__ import annotations

import subprocess

import pytest


class RealSubprocessEscape(BaseException):
    """Raised when a unit test is about to launch real heavy work.

    Deliberately derived from ``BaseException``, not ``Exception``:
    ``execute_training`` wraps its body in a generic ``except Exception``
    that degrades any error into ``{"status": "error"}``. An
    ``AssertionError`` would therefore be swallowed into a status
    dictionary, and the test would fail later for a confusing reason
    instead of stopping here. A guard whose whole purpose is to fail
    fast must not be catchable by the code it is guarding.
    """


#: Scripts that do real GPU/compute work. A unit test that reaches one
#: has lost its stub, whatever it thought it was patching.
_FORBIDDEN_SCRIPTS = (
    "train_engine_sandbox.py",
    "inference_single.py",
    "denoising_score_single.py",
    "preflight_worker_main",
)


def _offending_script(cmd: object) -> str | None:
    parts: list[str]
    if isinstance(cmd, (list, tuple)):
        parts = [str(p) for p in cmd]
    elif isinstance(cmd, str):
        parts = [cmd]
    else:
        return None
    joined = " ".join(parts)
    return next((s for s in _FORBIDDEN_SCRIPTS if s in joined), None)


@pytest.fixture(autouse=True)
def forbid_real_heavy_subprocess(monkeypatch, request):
    """Fail fast if a unit test is about to run real training work.

    Opt out with ``@pytest.mark.allow_real_subprocess`` for a test that
    genuinely needs to spawn one — the marker makes that intent explicit
    and greppable rather than accidental.
    """
    if request.node.get_closest_marker("allow_real_subprocess"):
        return

    real_run = subprocess.run
    real_popen = subprocess.Popen

    def _refuse(cmd, via: str) -> None:
        script = _offending_script(cmd)
        if script is None:
            return
        raise RealSubprocessEscape(
            f"unit test {request.node.nodeid} was about to launch the real "
            f"{script!r} via subprocess.{via}. A stub is missing or aimed "
            "at a retired entry point — which does not raise, it just lets "
            "the real thing run and the suite hang. Patch the production "
            "seam the executor actually calls, or mark the test "
            "@pytest.mark.allow_real_subprocess if the launch is intended."
        )

    def _guarded_run(cmd, *args, **kwargs):
        _refuse(cmd, "run")
        return real_run(cmd, *args, **kwargs)

    class _GuardedPopen(real_popen):  # type: ignore[misc, valid-type]
        """A Popen SUBCLASS, not a wrapper function.

        Replacing the class with a plain function changes its type, so a
        test that subclasses ``subprocess.Popen`` — a legitimate way to
        make ``communicate`` raise — fails with a confusing
        ``TypeError`` instead of running. A guard must not change the
        shape of what it guards.
        """

        def __init__(self, cmd, *args, **kwargs):
            _refuse(cmd, "Popen")
            super().__init__(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _guarded_run)
    monkeypatch.setattr(subprocess, "Popen", _GuardedPopen)
