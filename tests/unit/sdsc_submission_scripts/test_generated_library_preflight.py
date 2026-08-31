"""The X9 preflight validates the declared generated-library root through the production authority."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from core.generated_library import (
    GENERATED_LIBRARY_ENV_VAR,
    generated_library_provenance,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SDSC = REPO_ROOT / "sdsc_submission_scripts"
PREFLIGHT = SDSC / "campaign_preflight.sh"


def _bash(*argv: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a campaign script with a controlled environment.

    ``SIDERIUS_GENERATED_LIBRARY_DIR`` is REMOVED by default: the pytest
    session sets it (``tests/conftest.py`` isolation fixture), and inheriting
    that would make the undeclared case untestable — the very state these
    tests exist to reject would silently look declared.
    """
    merged = dict(os.environ)
    merged.pop("CUDA_VISIBLE_DEVICES", None)
    merged.pop(GENERATED_LIBRARY_ENV_VAR, None)
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", *argv],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=merged,
        timeout=300,
    )


def _r1c_rows(env: dict[str, str] | None) -> list[str]:
    """Run the preflight and return only its R1c verdict rows.

    The overall preflight exit status is deliberately NOT asserted: other
    rows (dataset availability, a clean tree, LLM smoke) depend on the host
    and on the working tree being committed, and are owned elsewhere. What
    this file owns is R1c's verdict.
    """
    revision = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    proc = _bash(
        str(PREFLIGHT),
        "--workspace-root",
        str(REPO_ROOT / ".git"),  # an existing, writable, persistent dir
        "--arm",
        "without-prior-art",
        "--revision",
        revision,
        "--skip_llm_smoke",
        "--",
        "--healthgate_mode",
        "blocking",
        "--result_authority",
        "scientific",
        env=env,
    )
    return [
        line
        for line in (proc.stdout + proc.stderr).splitlines()
        if "R1c" in line and ("PASS" in line or "FAIL" in line)
    ]


class TestPreflightR1cValidatesTheSuppliedRoot:
    def test_r1c_fails_when_the_variable_is_unset(self):
        """The defect only this catches: preflight passing a campaign whose
        library resolves to the shared default root. R1b already checks the
        calibration store this way; the generated library had no such row,
        and R8 cannot supply one because it globs the checkout only.

        Fails by: no FAIL row, or a message that does not name the default
        resolution as the reason."""
        rows = _r1c_rows(None)
        assert rows, "R1c produced no verdict"
        assert all("FAIL" in row for row in rows), rows
        assert any("DEFAULT root" in row for row in rows), rows

    def test_r1c_passes_for_a_persistent_supplied_root(self, tmp_path):
        """The defect only this catches: a guard that fails closed on
        everything, which would make every campaign unlaunchable and be
        disabled within a day.

        Fails by: a FAIL row for a supplied root on a persistent
        filesystem."""
        lib = tmp_path / "campaign_library"
        lib.mkdir()
        rows = _r1c_rows({GENERATED_LIBRARY_ENV_VAR: str(lib)})
        assert rows, "R1c produced no verdict"
        assert all("PASS" in row for row in rows), rows
        assert any("source=env" in row for row in rows), rows

    def test_r1c_fails_when_the_production_authority_refuses_the_value(self):
        """The defect only this catches: R1c re-deriving the root in bash
        instead of calling the authority. A bash re-implementation would
        happily accept a RELATIVE path that
        `core.generated_library.resolve_generated_library` refuses — two
        authorities, free to drift, and the preflight would bless a value the
        run then rejects (or worse, anchors to the launch cwd).

        Fails by: a PASS row for a value the authority refuses."""
        rows = _r1c_rows({GENERATED_LIBRARY_ENV_VAR: "relative/library"})
        assert rows, "R1c produced no verdict"
        assert all("FAIL" in row for row in rows), rows
        assert any("could not be resolved" in row for row in rows), rows
