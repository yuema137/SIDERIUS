"""The campaign preflight runs for the real Gold arm (B3).

``campaign_preflight.sh`` accepted only the two X9 arms, so
``--arm goldpod`` exited 1 before any row ran — including R1c, which the
Gold launcher's OWN refusal tells the operator to come here for
(``_gold_campaign_lib.sh:326``), and R1, whose mount verification
``gold_workspace_root_check`` explicitly delegates here (``:626``).

The workaround was worse than the gap. Reaching the machine-level rows
meant passing ``--arm with-prior-art``, and R8 then built
``{root}/with-prior-art_band{band}`` — so it reported "workspace
absent/empty" about a directory the campaign never writes and PASSED
while the real ``goldpod_band{band}`` was full. A cleanliness verdict
about the wrong tree is green exactly when the launch it clears would
resume instead of starting cold.

Each test below names the defect ONLY it catches.

* ``TestGoldWorkspaceResolution`` — ``preflight_band_workspace`` honours
  its ARM argument. A resolver that ignored it (or re-derived an X9
  label) would rebuild the surrogate-directory defect one layer down,
  and every row-level test would still be green because the rows would
  agree with each other about the wrong path. Asserted against
  hardcoded literals, never against a path read back from the script.
* ``TestGoldColdStartIsAboutTheGoldWorkspace`` — the decisive pair. R8
  FAILS on a NON-EMPTY ``goldpod_band0-3`` and PASSES when it is empty;
  and an empty ``with-prior-art_band0-3`` sitting beside a full
  ``goldpod_band0-3`` cannot green the gold run. Delete these and the
  vacuous PASS comes back silently: nothing else in the suite executes
  R8 against a populated workspace.
* ``TestGoldArmRowCoverage`` — the machine/environment rows are
  EVALUATED under goldpod (verdict-agnostic: these depend on the host),
  and the three rows bound to the X9 launcher or the X9 co-residency
  posture are SKIPPED BY NAME and never reported as PASS. A skip that
  printed PASS, or a row silently dropped from the summary, is the same
  class of lie as the surrogate workspace.
* ``TestX9ArmsUnchanged`` — the differential. Both X9 arms still execute
  R4, R6 and R7; if the arm gate were inverted or matched too broadly,
  the fleet's launch-blocking rows would go quietly missing while the
  summary still looked full.
* ``TestBlindpodRefusal`` — ``blindpod`` is campaign vocabulary
  (``GOLD_ARMS``) that this script deliberately does NOT accept, because
  Gold<->Blind treatment symmetry is a separate blind-launch
  prerequisite. The refusal must SAY that; a bare "unknown --arm" reads
  as an oversight and invites someone to add the label without the
  check that conditions it.
"""

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


class TestGoldWorkspaceResolution:
    @pytest.mark.parametrize(
        "arm,band,expected",
        [
            ("goldpod", "0-3", "/persist/camp/goldpod_band0-3"),
            ("goldpod", "15-19", "/persist/camp/goldpod_band15-19"),
            ("with-prior-art", "0-3", "/persist/camp/with-prior-art_band0-3"),
            ("without-prior-art", "4-9", "/persist/camp/without-prior-art_band4-9"),
        ],
    )
    def test_the_workspace_carries_the_arm_under_check(self, arm, band, expected):
        r = _pf_call(f"preflight_band_workspace /persist/camp {arm} {band}")
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.strip() == expected

    def test_a_trailing_slash_root_does_not_double_the_separator(self):
        r = _pf_call("preflight_band_workspace /persist/camp/ goldpod 0-3")
        assert r.stdout.strip() == "/persist/camp/goldpod_band0-3"


class TestGoldColdStartIsAboutTheGoldWorkspace:
    def test_r8_fails_on_a_non_empty_gold_workspace(self, pf_tree, tmp_path):
        root = tmp_path / "root"
        (root / "goldpod_band0-3").mkdir(parents=True)
        (root / "goldpod_band0-3" / "manifest.json").write_text("{}\n")
        r = _run_preflight(pf_tree, root, "goldpod")
        combined = r.stdout + r.stderr
        assert f"FAIL  R8 item1 band 0-3 workspace NOT empty ({root}/goldpod_band0-3)" in combined
        assert "PASS  R8 item1 band 0-3" not in combined, (
            "the populated band must not also report a PASS row"
        )
        assert r.returncode != 0

    def test_r8_passes_on_an_empty_gold_workspace(self, pf_tree, tmp_path):
        root = tmp_path / "root"
        (root / "goldpod_band0-3").mkdir(parents=True)
        r = _run_preflight(pf_tree, root, "goldpod")
        for band in _BANDS:
            assert (
                f"PASS  R8 item1 band {band} workspace absent/empty ({root}/goldpod_band{band})"
                in r.stdout
            )

    def test_an_empty_x9_directory_cannot_green_a_full_gold_workspace(self, pf_tree, tmp_path):
        """The exact shape of the workaround this fix exists to kill."""
        root = tmp_path / "root"
        (root / "with-prior-art_band0-3").mkdir(parents=True)  # the surrogate, empty
        (root / "goldpod_band0-3").mkdir(parents=True)  # the real one, full
        (root / "goldpod_band0-3" / "records").mkdir()
        r = _run_preflight(pf_tree, root, "goldpod")
        combined = r.stdout + r.stderr
        assert "FAIL  R8 item1 band 0-3 workspace NOT empty" in combined
        assert "with-prior-art_band0-3" not in combined, (
            "a gold preflight must never report on an X9 directory"
        )


class TestGoldArmRowCoverage:
    def test_every_machine_level_row_is_evaluated(self, pf_tree, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        r = _run_preflight(pf_tree, root, "goldpod")
        verdicts: dict[str, set[str]] = {}
        for verdict, row in _summary_rows(r.stdout):
            verdicts.setdefault(row, set()).add(verdict)
        for row in MACHINE_LEVEL_ROWS:
            assert row in verdicts, f"row {row} never reached the summary under goldpod"
            assert verdicts[row] & {"PASS", "FAIL"}, (
                f"row {row} was not evaluated under goldpod (verdicts: {verdicts[row]})"
            )

    def test_the_x9_bound_rows_are_skipped_by_name_and_never_pass(self, pf_tree, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        r = _run_preflight(pf_tree, root, "goldpod")
        rows = _summary_rows(r.stdout)
        for row in X9_BOUND_ROWS:
            present = {verdict for verdict, name in rows if name == row}
            assert present == {"SKIP"}, (
                f"row {row} under goldpod: expected only SKIP, got {present}"
            )
        assert "NOT APPLICABLE to arm goldpod" in r.stdout

    def test_a_skipped_row_does_not_block_the_launch(self, pf_tree, tmp_path):
        """SKIP must not be counted as a failure: an inapplicable check has
        proven nothing, and blocking on it would push the operator straight
        back to the surrogate-arm workaround."""
        root = tmp_path / "root"
        root.mkdir()
        r = _run_preflight(pf_tree, root, "goldpod")
        skips = sum(1 for verdict, _ in _summary_rows(r.stdout) if verdict == "SKIP")
        fails = sum(1 for verdict, _ in _summary_rows(r.stdout) if verdict == "FAIL")
        assert skips == len(X9_BOUND_ROWS)
        assert f"failures={fails}" in r.stdout


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


class TestBlindpodRefusal:
    def test_blindpod_is_refused_naming_the_blind_launch_prerequisite(self, pf_tree, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        r = _run_preflight(pf_tree, root, "blindpod")
        assert r.returncode != 0
        assert "blindpod" in r.stderr
        assert "symmetry" in r.stderr, "the refusal must name WHY, not just refuse"
        assert "[preflight]" not in r.stdout, "no row may run for a refused arm"

    def test_an_unknown_arm_lists_what_is_accepted(self, pf_tree, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        r = _run_preflight(pf_tree, root, "with-prior-fart")
        assert r.returncode != 0
        assert "goldpod" in r.stderr and "with-prior-art" in r.stderr
