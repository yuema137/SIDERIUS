"""The campaign path resolver, and the proof that E-C1 moved nothing.

V20 PR E, checkpoint E-C1.

Campaign identity currently lives in a FILENAME PREFIX
(`${CAMPAIGN_ID}_wave_state.jsonl`) under a shared root, and a prefix is
easy to forget: `QUEUE_STOP_FILE` omits it entirely, so one campaign's STOP
halts every campaign sharing that root.

E-C1 introduces the resolution block with **every default pinned to today's
location**, so the shape is reviewable before anything moves. These tests
are the proof of that claim: each resolved path must still equal the literal
form it had before the commit. E-C2 flips the defaults, and the diff there
is then a visible, reviewed change rather than an accident.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"


def _resolve(*names: str, **env) -> dict[str, str]:
    """Source the runner and read variables back.

    `V19_QUEUE_NO_MAIN=1` plus the source-safe guard means `main` never
    runs, so this cannot launch anything.
    """
    echo = "; ".join(f'echo "{n}=${{{n}}}"' for n in names)
    result = subprocess.run(
        ["bash", "-c", f"V19_QUEUE_NO_MAIN=1 source '{RUNNER}'; {echo}"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, **{k: str(v) for k, v in env.items()}),
        timeout=60,
    )
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


CAMPAIGN = "v19"
ROOT = "/tmp/pr-e-parity-root"


class TestEC1MovedNothing:
    """Default parity. Every resolved path must equal its pre-commit form."""

    def test_the_stop_file_is_still_the_shared_root_one(self):
        """The defect is not fixed yet, and this commit must not pretend
        otherwise. `QUEUE_STOP_FILE` still omits campaign identity."""
        got = _resolve("QUEUE_STOP_FILE", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["QUEUE_STOP_FILE"] == f"{ROOT}/STOP"

    def test_the_wave_state_is_still_the_prefixed_file(self):
        got = _resolve("WAVE_STATE", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["WAVE_STATE"] == f"{ROOT}/{CAMPAIGN}_wave_state.jsonl"

    def test_the_log_is_still_the_prefixed_file(self):
        got = _resolve("LOGF", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["LOGF"] == f"{ROOT}/{CAMPAIGN}_queue_runner.log"

    def test_campaign_home_defaults_to_the_shared_root(self):
        """E-C2 changes exactly this line to `$WS_ROOT/$CAMPAIGN_ID`, and
        that one-line difference is the whole path move."""
        got = _resolve("CAMPAIGN_HOME", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["CAMPAIGN_HOME"] == ROOT

    @pytest.mark.parametrize(
        "name", ["CAMPAIGN_CONTROL_DIR", "QUEUE_STATE_DIR", "PAIR_SUMMARY_DIR"]
    )
    def test_the_subdirectories_still_resolve_to_the_home(self, name):
        got = _resolve(name, WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got[name] == ROOT

    def test_the_stamp_path_is_defined_and_under_the_control_dir(self):
        got = _resolve("CAMPAIGN_STAMP", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["CAMPAIGN_STAMP"] == f"{ROOT}/{CAMPAIGN}_campaign.json"


class TestTheOverrideSurfaceIsNarrow:
    """`CAMPAIGN_HOME` is overridable; the three directories under it are
    NOT independently overridable.

    Separate overrides would let two campaigns be pointed at one state
    directory — recreating the cross-campaign authority defect this PR
    exists to remove.
    """

    def test_campaign_home_honours_an_override(self):
        got = _resolve("CAMPAIGN_HOME", WS_ROOT=ROOT, CAMPAIGN_HOME="/tmp/elsewhere")
        assert got["CAMPAIGN_HOME"] == "/tmp/elsewhere"

    @pytest.mark.parametrize(
        "name", ["CAMPAIGN_CONTROL_DIR", "QUEUE_STATE_DIR", "PAIR_SUMMARY_DIR"]
    )
    def test_a_subdirectory_override_has_no_effect(self, name):
        """MUTATION TARGET: giving these a `${NAME:-…}` form.

        If this ever passes with the override honoured, two campaigns can
        be aimed at one state directory again.
        """
        got = _resolve(name, WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN, **{name: "/tmp/hijack"})
        assert got[name] == ROOT, (
            f"{name} accepted an independent override; two campaigns could "
            "now share one state directory"
        )

    def test_the_derived_directories_follow_the_home(self):
        got = _resolve(
            "CAMPAIGN_CONTROL_DIR",
            "QUEUE_STATE_DIR",
            "PAIR_SUMMARY_DIR",
            WS_ROOT=ROOT,
            CAMPAIGN_HOME="/tmp/elsewhere",
        )
        assert set(got.values()) == {"/tmp/elsewhere"}


class TestDefinitionScopeTouchesNothing:
    def test_sourcing_creates_no_campaign_directory(self, tmp_path):
        """E-C1 adds no `mkdir`. The directory arrives in E-C2, created by
        the guard that also validates the id — never at definition scope,
        where merely reading the file would create it."""
        root = tmp_path / "root"
        _resolve("CAMPAIGN_HOME", WS_ROOT=str(root), CAMPAIGN_ID=CAMPAIGN)
        assert not root.exists(), "sourcing the runner created the campaign root"
