"""D-B4: pair-cap oversubscription is denied by default.

`ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-1` meant "allow unless the operator
says otherwise", so a pair whose configured caps exceeded the host
aggregate ceiling launched anyway and the host watchdog was the first
component to notice. During C12 it was, and what it produced was a kill.

The override survives -- an operator who knows the caps are conservative
may still need it -- but it must now be asked for, it is announced
loudly, it is recorded in provenance, and it is refused outright in the
formal V20 Gate, where a knowingly oversubscribed run would be neither
comparable nor defensible.

These tests drive the real guard blocks sliced out of the shipped
launchers, so a regression in either script fails here.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SDSC = REPO_ROOT / "sdsc_submission_scripts"
GATE = SDSC / "v19_gate0_pair_runner.sh"
QUEUE = SDSC / "v19_queue_runner.sh"
LAUNCHERS = (GATE, QUEUE)


def guard_block(path: Path) -> str:
    """The real `ALLOW_PAIR_CAP_OVERSUBSCRIPTION` decision, verbatim."""
    src = path.read_text()
    i = src.index("ALLOW_PAIR_CAP_OVERSUBSCRIPTION")
    start = src.rindex("if ", 0, i)
    # Must span BOTH paths: the deny branch and the override branch that
    # follows the inner `fi`. Two slicing bugs lived here -- searching for
    # a bare "fi" matched the one inside "con*fi*gured", and stopping at
    # the inner `fi` cut the override branch off entirely, so tests failed
    # against guards that were correct.
    end_marker = "PAIR_OVERSUBSCRIPTION_OVERRIDE=1"
    j = src.index(end_marker, i)
    return src[start : src.index("\n", j)]


def run_guard(path: Path, env_value: str | None) -> subprocess.CompletedProcess:
    """Execute the guard with the pair check forced to FAIL.

    A passing check never reaches the branch, so the default only matters
    on the infeasible path — which is exactly the case D-B4 changes.
    """
    block = guard_block(path)
    block = re.sub(r"\bexit 1\b", "echo BLOCKED >&2; exit 1", block)
    block = re.sub(r"^\s*(DISPOSITION|record_queue_stop)", r"  echo \1", block, flags=re.M)
    script = (
        "set -u\n"
        'log() { echo "$@"; }\n'
        'record_queue_stop() { echo "record_queue_stop $*"; }\n'
        "DISPOSITION=''\nWAVE=1\nARCH_RUN=a\nLOSS_RUN=b\nPAIR_CHECK='caps exceed ceiling'\n"
        "PAIR_OVERSUBSCRIPTION_OVERRIDE=0\n" + block + "\n"
        'echo "OVERRIDE_FLAG=${PAIR_OVERSUBSCRIPTION_OVERRIDE}"\n'
        'echo "REACHED_END"\n'
    )
    env = {"PATH": "/usr/bin:/bin"}
    if env_value is not None:
        env["ALLOW_PAIR_CAP_OVERSUBSCRIPTION"] = env_value
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False, env=env
    )


class TestTheDefaultIsFailClosed:
    @pytest.mark.parametrize("path", LAUNCHERS, ids=lambda p: p.name)
    def test_the_default_literal_is_zero_not_one(self, path):
        """`:-1` was the whole defect: absent meant allow."""
        src = path.read_text()
        assert "ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-0" in src
        assert "ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-1" not in src

    @pytest.mark.parametrize("path", LAUNCHERS, ids=lambda p: p.name)
    def test_an_infeasible_pair_is_denied_when_unset(self, path):
        out = run_guard(path, None)
        assert out.returncode != 0, "an infeasible pair must not launch by default"
        assert "REACHED_END" not in out.stdout

    @pytest.mark.parametrize("path", LAUNCHERS, ids=lambda p: p.name)
    def test_an_explicit_zero_is_also_denied(self, path):
        out = run_guard(path, "0")
        assert out.returncode != 0

    @pytest.mark.parametrize("path", LAUNCHERS, ids=lambda p: p.name)
    def test_the_denial_names_the_reason(self, path):
        out = run_guard(path, None)
        blob = out.stdout + out.stderr
        assert "pair_infeasible_under_host_quota" in blob


class TestTheOverrideStillExistsButIsLoud:
    def test_the_queue_runner_allows_an_explicit_override(self):
        """Not the Gate — an operator running a normal wave who knows the
        caps are conservative must still be able to proceed."""
        out = run_guard(QUEUE, "1")
        assert out.returncode == 0
        assert "REACHED_END" in out.stdout

    def test_the_override_is_announced_not_silent(self):
        out = run_guard(QUEUE, "1")
        blob = out.stdout + out.stderr
        assert "OVERRIDE ACTIVE" in blob
        assert "oversubscribed" in blob

    def test_the_override_is_recorded_in_provenance(self):
        """A run that knowingly oversubscribed must be identifiable
        afterwards, not only in a log line someone might not read."""
        out = run_guard(QUEUE, "1")
        assert "OVERRIDE_FLAG=1" in out.stdout

    def test_no_override_leaves_the_provenance_flag_clear(self):
        out = run_guard(QUEUE, "1")
        assert "OVERRIDE_FLAG=1" in out.stdout
        src = QUEUE.read_text()
        assert "PAIR_OVERSUBSCRIPTION_OVERRIDE=1" in src


class TestTheFormalGateForbidsTheOverride:
    def test_the_gate_refuses_even_an_explicit_override(self):
        """The strictest context must not have the weakest guarantee."""
        out = run_guard(GATE, "1")
        assert out.returncode != 0
        blob = out.stdout + out.stderr
        assert "override refused" in blob.lower()

    def test_the_gate_records_a_distinct_disposition(self):
        out = run_guard(GATE, "1")
        blob = out.stdout + out.stderr
        assert "pair_oversubscription_override_forbidden_in_gate" in blob

    def test_the_gate_never_reaches_the_launch_path_with_an_override(self):
        out = run_guard(GATE, "1")
        assert "REACHED_END" not in out.stdout


class TestNothingElseMoved:
    """D-B4 changes one default. It must not quietly retune capacity."""

    def test_the_pair_ceiling_constant_is_unchanged(self):
        src = (REPO_ROOT / "core" / "runtime_control" / "pair_admission.py").read_text()
        assert re.search(r"DEFAULT_PAIR_CEILING_GIB\s*=\s*28\.0", src)

    def test_the_host_quota_env_name_is_unchanged(self):
        src = (REPO_ROOT / "core" / "runtime_control" / "pair_admission.py").read_text()
        assert "SIDERIUS_GPU_VRAM_QUOTA_MIB" in src

    @pytest.mark.parametrize("path", LAUNCHERS, ids=lambda p: p.name)
    def test_the_per_chain_cap_variable_is_untouched(self, path):
        assert "PAIR_CAP_GIB" in path.read_text()
