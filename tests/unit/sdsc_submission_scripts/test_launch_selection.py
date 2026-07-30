"""V19 O2 — selective chain launching (`--only`) tests.

`filter_roster()` in `_chain_common.sh` is side-effect-free (pure
stdout/rc), so it is exercised directly by sourcing the library in a
bash subprocess — no GPU, no screen, no launch. Launcher-level tests
cover only the argument/selection error paths, all of which exit
BEFORE preflight (which needs CUDA and data).

Design: docs/design/v19_priorities/o1a_o2_operator_tooling.md §2.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"
LAUNCHER = REPO_ROOT / "sdsc_submission_scripts" / "launch_v18_wave1.sh"

ROSTER = [
    "chain_a:4-9:4,5:loss",
    "chain_b:4-9:4,5:arch",
    "chain_c:10-14:10,11:loss",
]


def _filter(only: str, roster: list[str] | None = None) -> subprocess.CompletedProcess:
    roster = ROSTER if roster is None else roster
    quoted = " ".join(f"'{r}'" for r in roster)
    return subprocess.run(
        ["bash", "-c", f"source '{LIB}' && filter_roster '{only}' {quoted}"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


class TestFilterRoster:
    def test_omitted_only_is_identity_in_order(self):
        r = _filter("")
        assert r.returncode == 0
        assert r.stdout.splitlines() == ROSTER

    def test_single_name(self):
        r = _filter("chain_b")
        assert r.returncode == 0
        assert r.stdout.splitlines() == ["chain_b:4-9:4,5:arch"]

    def test_reversed_input_preserves_canonical_order(self):
        r = _filter("chain_c,chain_a")
        assert r.returncode == 0
        assert r.stdout.splitlines() == [
            "chain_a:4-9:4,5:loss",
            "chain_c:10-14:10,11:loss",
        ]

    def test_all_names_equals_identity(self):
        r = _filter("chain_a,chain_b,chain_c")
        assert r.returncode == 0
        assert r.stdout.splitlines() == ROSTER

    def test_whitespace_trimmed(self):
        r = _filter("  chain_a ,\tchain_c  ")
        assert r.returncode == 0
        assert r.stdout.splitlines() == [
            "chain_a:4-9:4,5:loss",
            "chain_c:10-14:10,11:loss",
        ]

    def test_unknown_name_fails_listing_valid_names(self):
        r = _filter("chain_x")
        assert r.returncode == 1
        assert r.stdout == ""  # no fallback to "all"
        assert "unknown name" in r.stderr
        assert "chain_a" in r.stderr and "chain_c" in r.stderr

    def test_duplicate_rejected_not_deduplicated(self):
        r = _filter("chain_a,chain_a")
        assert r.returncode == 1
        assert r.stdout == ""
        assert "duplicate" in r.stderr

    def test_blank_selection_fails(self):
        for only in (" , ", ",", "  "):
            r = _filter(only)
            assert r.returncode == 1, f"only={only!r}"
            assert r.stdout == ""
            assert "selected nothing" in r.stderr


class TestLauncherSelectionErrorPaths:
    """These paths exit before preflight — safe without GPU/screen/data."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(LAUNCHER), *args],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

    def test_unknown_only_name_fails_before_any_launch(self):
        r = self._run("1a", "--only", "not_a_chain")
        assert r.returncode == 1
        assert "unknown name" in r.stderr
        assert "v18r_loss_04_09" in r.stderr  # valid names listed
        assert "[launched]" not in r.stdout

    def test_duplicate_only_name_fails(self):
        r = self._run("1a", "--only", "v18r_loss_04_09,v18r_loss_04_09")
        assert r.returncode == 1
        assert "duplicate" in r.stderr

    def test_only_without_value_fails(self):
        r = self._run("1a", "--only")
        assert r.returncode == 1
        assert "--only requires" in r.stderr

    def test_unknown_flag_fails_with_usage(self):
        r = self._run("1a", "--bogus")
        assert r.returncode == 1
        assert "unknown argument" in r.stderr

    def test_bad_phase_shows_only_in_usage(self):
        r = self._run("9z")
        assert r.returncode == 1
        assert "--only" in r.stderr
