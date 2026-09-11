"""Bounded CLI checks for the maintained campaign admission entrypoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ENTRY = REPO / "scripts/runtime/campaign_admission.py"


def _invoke(root: Path, home: Path, campaign_id: str = "c3-test") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ENTRY), "--campaign-id", campaign_id, "--ws-root", str(root),
         "--campaign-home", str(home), "--runner", "run_chain.sh", "--runner-pid", str(__import__("os").getpid())],
        cwd=Path("/tmp"), env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
        text=True, capture_output=True, check=False, timeout=10,
    )


def test_relocated_admission_cli_success_and_duplicate_refusal(tmp_path: Path) -> None:
    root = tmp_path / "campaigns"
    home = root / "c3-test"
    first = _invoke(root, home)
    assert first.returncode == 0, first.stderr
    assert len(first.stdout.splitlines()) == 2
    second = _invoke(root, home, campaign_id="bad/id")
    assert second.returncode == 2
    assert "campaign_admission" in second.stderr
