"""FU-B-15: the sampler must label the tuner parent by PID, not by name.

B-G0 and B-G1 both produced **no** `P0_TUNER_PARENT` sample. The
classifier matched `ml_hyperparameter_tune_agent` in the command line,
but the B-G scenarios launch through `scripts/bg_admission_validation.py`,
so the parent was never labelled and "parent held 0 MiB" rested on
absence from NVML rather than on a labelled measurement.

That matters most for B-G2, where the no-candidate-child proof has to
distinguish four things on one card: the tuner parent, the holder, a
candidate training/inference child, and anything foreign. A command-line
substring cannot separate them reliably; a registered PID can.

These tests drive the real `classify` and `read_pid` out of the shipped
script rather than restating them, so a change to the script that breaks
attribution fails here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLER = REPO_ROOT / "scripts" / "diagnostics" / "bg_gpu_sampler.sh"


def _drive(outdir: Path, calls: str) -> dict[str, str]:
    """Run the script's own helpers against `outdir`.

    Slices the real source between `read_pid()` and the sample loop, so
    the functions under test are the shipped ones. Importing them any
    other way would mean testing a copy.
    """
    src = SAMPLER.read_text()
    body = src[src.index("read_pid() {") : src.index("iter=0")]
    script = f"""set -u
OUTDIR={outdir!s}
PARENT_PID_FILE="$OUTDIR/tuner_parent.pid"
HOLDER_PID_FILE="$OUTDIR/holder.pid"
{body}
PARENT_PID=$(read_pid "$PARENT_PID_FILE")
HOLDER_PID=$(read_pid "$HOLDER_PID_FILE")
{calls}
"""
    # Written to a file rather than passed with `bash -c`. The sliced
    # body contains `preflight_worker_main` as a *case pattern*, and the
    # unit-suite guard inspects argv for exactly that name — via `-c` it
    # would read as a launch. Keeping the script out of argv leaves the
    # guard armed instead of suppressing it with a marker.
    runner = outdir / "_drive.sh"
    runner.write_text(script)
    out = subprocess.run(
        ["bash", str(runner)], capture_output=True, text=True, timeout=30, check=False
    )
    assert out.returncode == 0, out.stderr
    return dict(line.split("=", 1) for line in out.stdout.strip().splitlines() if "=" in line)


@pytest.fixture
def outdir(tmp_path: Path) -> Path:
    return tmp_path


def test_the_sampler_script_exists_and_parses():
    assert SAMPLER.exists()
    subprocess.run(["bash", "-n", str(SAMPLER)], check=True, timeout=30)


def test_a_registered_parent_pid_is_labelled_parent(outdir: Path):
    """The exact FU-B-15 defect: this PID's command line contains no
    tuner name at all, so name matching would call it FOREIGN."""
    (outdir / "tuner_parent.pid").write_text("424242")
    got = _drive(outdir, 'echo "role=$(classify 424242)"')
    assert got["role"] == "P0_TUNER_PARENT"


def test_a_registered_holder_pid_is_labelled_holder(outdir: Path):
    (outdir / "holder.pid").write_text("515151")
    got = _drive(outdir, 'echo "role=$(classify 515151)"')
    assert got["role"] == "HOLDER"


def test_identity_beats_name_matching(outdir: Path):
    """A registered PID wins even against a matching command line. The
    registration is exact; the substring is a guess."""
    (outdir / "tuner_parent.pid").write_text("1")
    got = _drive(outdir, 'echo "role=$(classify 1)"')
    assert got["role"] == "P0_TUNER_PARENT"


def test_an_unregistered_pid_still_falls_back_to_the_name(outdir: Path):
    """Registration is an improvement, not a prerequisite: a process
    nobody registered must still be classified."""
    got = _drive(outdir, 'echo "role=$(classify 1)"')
    assert got["role"] in {"FOREIGN", "gone"}


def test_a_missing_registration_file_is_not_an_error(outdir: Path):
    """A sampler that aborted when the harness had not yet written its
    PID would lose the very window it exists to observe."""
    got = _drive(outdir, 'echo "parent=[$PARENT_PID]"; echo "ok=yes"')
    assert got["parent"] == "[]"
    assert got["ok"] == "yes"


def test_a_malformed_registration_cannot_inject_a_pattern(outdir: Path):
    """`read_pid` strips to digits, so a stray newline or a hostile
    string cannot become a match-anything value."""
    (outdir / "tuner_parent.pid").write_text("  9\n9 \n")
    got = _drive(outdir, 'echo "parent=[$PARENT_PID]"')
    assert got["parent"] == "[99]"


def test_an_empty_registration_does_not_match_every_pid(outdir: Path):
    """The failure that would look like success: if an empty PARENT_PID
    compared equal to anything, every process would be reported as the
    parent and the no-child proof would be worthless."""
    (outdir / "tuner_parent.pid").write_text("")
    got = _drive(outdir, 'echo "role=$(classify 1)"')
    assert got["role"] != "P0_TUNER_PARENT"


def test_the_validation_launcher_is_a_known_role_not_foreign():
    """Belt and braces for an unregistered run: the B-G launcher name is
    now in the fallback table, so an operator running the sampler
    without registration still gets a labelled parent."""
    assert "bg_admission_validation" in SAMPLER.read_text()
