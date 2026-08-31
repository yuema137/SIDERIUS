"""X9 campaign preflight preserves both declared arms and every blocking row."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_SDSC = _REPO / "sdsc_submission_scripts"
_PREFLIGHT = _SDSC / "campaign_preflight.sh"

#: Rows that describe the HOST or the CHECKOUT and therefore hold for any
#: launch topology. Hardcoded: reading the script's own row list back would
#: compare it to itself and pass for any list.
MACHINE_LEVEL_ROWS = ("R1", "R1b", "R1c", "R2", "R2b", "R3", "R5", "R8")

#: Rows bound to the X9 band launcher (R6/R7) or to the X9 four-way
#: co-residency posture (R4), which the campaign does not adopt.
X9_BOUND_ROWS = ("R4", "R6", "R7")

_BANDS = ("0-3", "4-9", "10-14", "15-19")


def _pf_call(fn_and_args: str) -> subprocess.CompletedProcess:
    """Source the preflight (entry-guarded) and call one pure function."""
    script = f'source "{_PREFLIGHT}"\n{fn_and_args}\n'
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


@pytest.fixture
def pf_tree(tmp_path: Path) -> Path:
    """A project tree holding the REAL preflight beside fast stubs.

    The preflight derives its project dir from its own location, so the
    script is copied under ``tmp_path/sdsc`` and every heavy sibling is
    stubbed: a launcher that exits 0 printing nothing (R6/R7 evaluate and
    fail on content, in milliseconds instead of the 1-5 minutes real
    dry-runs take) and a python that exits 1 (R1c/R2b/R3/R7 evaluate and
    fail without importing the framework). No test here asserts those
    verdicts — only WHICH rows were reached.
    """
    sdsc = tmp_path / "sdsc"
    sdsc.mkdir()
    for name in (
        "campaign_preflight.sh",
        "_import_resolution_probe.py",
        "h100_posture.env",
        "campaign_arm_symmetry.py",
    ):
        shutil.copy2(_SDSC / name, sdsc / name)
    launcher = sdsc / "launch_prior_baseline_experiment.sh"
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    fake_python = tmp_path / "fakepython"
    fake_python.write_text("#!/bin/sh\nexit 1\n")
    fake_python.chmod(0o755)
    return tmp_path


def _run_preflight(tree: Path, workspace_root: Path, arm: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "bash",
            str(tree / "sdsc" / "campaign_preflight.sh"),
            "--workspace-root",
            str(workspace_root),
            "--arm",
            arm,
            "--revision",
            "deadbeefcafe",
            "--skip_llm_smoke",
            "--",
            "--healthgate_mode",
            "blocking",
            "--result_authority",
            "scientific",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tree),
            "SIDERIUS_PYTHON": str(tree / "fakepython"),
        },
    )


def _summary_rows(stdout: str) -> list[tuple[str, str]]:
    """(verdict, row_id) for every row of the printed summary block.

    Read from the SUMMARY, not from the streamed lines: the summary is
    the operator-facing artifact, and a row that never reaches it is
    invisible however loudly it printed on the way past.
    """
    rows: list[tuple[str, str]] = []
    in_summary = False
    for line in stdout.splitlines():
        if "CAMPAIGN PREFLIGHT SUMMARY" in line:
            in_summary = True
            continue
        if not in_summary:
            continue
        parts = line.strip().split(None, 2)
        if len(parts) >= 2 and parts[0] in {"PASS", "FAIL", "SKIP", "INFO"}:
            rows.append((parts[0], parts[1]))
    return rows


class TestX9ArmsUnchanged:
    @pytest.mark.parametrize("arm", ["with-prior-art", "without-prior-art"])
    def test_the_launcher_bound_rows_still_execute(self, pf_tree, tmp_path, arm):
        root = tmp_path / "root"
        root.mkdir()
        r = _run_preflight(pf_tree, root, arm)
        rows = _summary_rows(r.stdout)
        assert not any(verdict == "SKIP" for verdict, _ in rows), (
            "no row may be skipped for an X9 arm"
        )
        for row in X9_BOUND_ROWS:
            assert any(name == row for _, name in rows), f"row {row} vanished for arm {arm}"

    @pytest.mark.parametrize("arm", ["with-prior-art", "without-prior-art"])
    def test_r8_still_inspects_that_arms_own_workspace(self, pf_tree, tmp_path, arm):
        root = tmp_path / "root"
        (root / f"{arm}_band0-3").mkdir(parents=True)
        (root / f"{arm}_band0-3" / "manifest.json").write_text("{}\n")
        r = _run_preflight(pf_tree, root, arm)
        combined = r.stdout + r.stderr
        assert f"FAIL  R8 item1 band 0-3 workspace NOT empty ({root}/{arm}_band0-3)" in combined


