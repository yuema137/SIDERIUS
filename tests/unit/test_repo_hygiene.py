"""No test artifact may be committed to the repository.

4,923 files — 21 MB, roughly ten times the whole `tests/` tree — were once
committed under `MagicMock/TidmadSandbox().base_dir/`. They came from a
mock standing in for a sandbox:

    >>> os.fspath(MagicMock().base_dir)
    'MagicMock/TidmadSandbox().base_dir/140313120295728'

`MagicMock` implements `__fspath__`, so `Path(sandbox.base_dir)` accepts a
mock **silently** — no `TypeError`, no warning — and the
`mkdir(parents=True)` that follows materialises that literal path relative
to the working directory. A test that forgets
`sandbox.base_dir = str(tmp_path)` therefore writes a real tree into the
repository root, and `git add -A` commits it.

`.gitignore` alone would not have caught this: the files were already
tracked, and ignore rules do not apply to tracked paths. The check has to
be against the index.

These assert on `git ls-files`, so they fail on what is actually
**committed** rather than on what happens to be on disk.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A path segment produced by stringifying a mock rather than a real path.
#: `MagicMock/...` is the `__fspath__` form; `<MagicMock ...>` is the plain
#: `repr`, which reaches a filename through an f-string instead.
_MOCK_PATH = re.compile(r"(^|/)(MagicMock|NonCallableMagicMock|Mock)(/|$)|<(MagicMock|Mock)[ >]")

#: Runtime artifacts that belong in a temp directory, never in the index.
#: `.exit` and `.pid` are the chain markers the launchers write to
#: `EXIT_DIR`; `.worker.log` is the measurement worker's transcript.
_RUNTIME_ARTIFACT = re.compile(r"\.(exit|pid)$|\.worker\.log$")


def _tracked_files() -> list[str]:
    """Every path in the index, from the checkout under test."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    if result.returncode != 0:  # not a git checkout (e.g. a source tarball)
        pytest.skip(f"not a git checkout: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


class TestNoMockDerivedPathIsCommitted:
    def test_no_tracked_path_was_produced_by_a_mock(self):
        """THE REGRESSION. `MagicMock/TidmadSandbox().base_dir/...` was
        tracked for the length of a whole PR before anyone looked."""
        offenders = [p for p in _tracked_files() if _MOCK_PATH.search(p)]
        assert not offenders, (
            f"{len(offenders)} tracked path(s) were produced by stringifying a "
            f"mock — a test wrote into the repo instead of a tmp_path. First "
            f"few: {offenders[:3]}"
        )

    def test_the_ignore_rule_is_present_as_a_second_line_of_defence(self):
        """`.gitignore` cannot untrack what is already tracked, so it is a
        guard against RE-adding, not the fix. The fix is the test above;
        this asserts the guard did not get dropped."""
        assert "MagicMock/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


class TestNoRuntimeArtifactIsCommitted:
    def test_no_marker_or_worker_log_is_tracked(self):
        """1,641 `.worker.log` files came in with the mock tree. Chain
        `.exit` / `.pid` markers belong in `EXIT_DIR` (default `/tmp`) and
        are evidence of a run, not of the source."""
        offenders = [p for p in _tracked_files() if _RUNTIME_ARTIFACT.search(p)]
        assert not offenders, f"{len(offenders)} runtime artifact(s) are tracked: {offenders[:3]}"


class TestMocksStillStringifyIntoPaths:
    """The reason the rules above cannot be relaxed.

    If a future Python or `unittest.mock` made `os.fspath(MagicMock())`
    raise, the hazard would be gone and these tests would be theatre. It
    does not — so this documents the live behaviour rather than assuming
    it, and will fail loudly if it ever changes.
    """

    def test_a_magicmock_attribute_is_accepted_as_a_path(self):
        import os
        from unittest.mock import MagicMock

        rendered = os.fspath(MagicMock(name="Sandbox()").base_dir)

        assert rendered.startswith("MagicMock/"), rendered
        assert _MOCK_PATH.search(rendered), (
            "a mock no longer renders as a MagicMock/ path — the detection "
            "pattern above needs updating, not deleting"
        )
