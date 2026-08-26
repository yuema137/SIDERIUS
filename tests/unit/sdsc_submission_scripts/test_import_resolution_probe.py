"""The E1 import-resolution probe (P0 launch blocker, supervisor 2026-08-25).

The venv's editable install maps packages to the MAIN checkout; an unpinned
child whose cwd leaves the campaign tree imports THAT tree's code. The probe
(`_import_resolution_probe.py`, run by preflight R2b from a neutral cwd)
proves the PYTHONPATH pin. These tests run the REAL probe as a subprocess
from a temp cwd — the actual failure mode's geometry, not a -c simulation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE = REPO_ROOT / "sdsc_submission_scripts" / "_import_resolution_probe.py"


def _run(tmp_path: Path, intended: Path, pin: Path | None) -> subprocess.CompletedProcess:
    import shutil

    work = tmp_path / "neutral"
    work.mkdir(exist_ok=True)
    shutil.copy(PROBE, work / "probe.py")
    env = {"PATH": "/usr/bin:/bin"}
    if pin is not None:
        env["PYTHONPATH"] = str(pin)
    return subprocess.run(
        [sys.executable, "probe.py", str(intended)],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_pinned_to_this_tree_passes(tmp_path):
    """Defect only this catches: the probe's PASS path broken (e.g. the
    annotation regex missing the tolerant type on a tree that HAS #299) —
    preflight R2b would then hard-fail a correct launch. Fails by: rc != 0."""
    r = _run(tmp_path, intended=REPO_ROOT, pin=REPO_ROOT)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "[import-probe] PASS" in r.stdout


def test_wrong_intended_tree_fails_with_the_named_reason(tmp_path):
    """Defect only this catches: the probe going green when resolution lands
    OUTSIDE the intended tree — the exact silent-wrong-code condition R2b
    exists to block. Fails by: rc == 0, or the refusal not naming the
    outside-tree cause."""
    r = _run(tmp_path, intended=tmp_path / "not_a_checkout", pin=REPO_ROOT)
    # DECLARED DELTA (Lane F / F5 strict cause-keying, 2026-08-26): FOREIGN
    # is now the probe's contract code 4, distinct from the #299
    # semantic-leg's 1 and from DEPS-UNAVAILABLE's 3, so run_chain's guard
    # can key its dry-run relaxation on the exact cause. R2b consumes the
    # probe nonzero-generically and is unaffected.
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "resolves OUTSIDE the intended tree" in r.stderr
