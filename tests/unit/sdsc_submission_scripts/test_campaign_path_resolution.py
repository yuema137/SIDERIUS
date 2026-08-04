"""The campaign path resolver: every authority-bearing path is scoped.

V20 PR E, checkpoints E-C1 (the shape) and E-C2 (the move).

Campaign identity used to live in a FILENAME PREFIX
(`${CAMPAIGN_ID}_wave_state.jsonl`) under a shared root, and a prefix is
easy to forget: `QUEUE_STOP_FILE` omitted it entirely, so one campaign's
STOP halted every campaign sharing that root. That is the defect PR E
exists to remove.

E-C1 landed the resolution block with every default pinned to the old
location, so the model was reviewable before anything moved. **E-C2 flips
those defaults**, and this file flipped with it: the parity assertions
that pinned the old paths are now the assertions that pin the new ones.
The defect class each one catches is unchanged — a path that stops
carrying campaign identity is a path two campaigns can collide on.
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


#: The five paths a campaign's authority rests on. Named once, so a new
#: authority-bearing path cannot be added without appearing here.
AUTHORITY_PATHS = [
    "QUEUE_STOP_FILE",
    "WAVE_STATE",
    "LOGF",
    "CAMPAIGN_STAMP",
    "PAIR_SUMMARY_DIR",
]


class TestTheCampaignPathsAreScoped:
    """E-C2's move. Every resolved path now sits under the campaign home.

    These replace E-C1's parity assertions one for one — same paths, same
    defect class, opposite expectation, which is what makes the move a
    reviewed diff rather than a drift.
    """

    def test_the_stop_file_moved_into_the_campaigns_control_dir(self):
        """THE §1 DEFECT. `QUEUE_STOP_FILE` used to default to
        `$WS_ROOT/STOP` — one file shared by every campaign under the
        root, so stopping one stopped all of them (BD-1)."""
        got = _resolve("QUEUE_STOP_FILE", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["QUEUE_STOP_FILE"] == f"{ROOT}/{CAMPAIGN}/control/STOP"

    def test_the_wave_state_moved_into_the_campaigns_queue_state_dir(self):
        got = _resolve("WAVE_STATE", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["WAVE_STATE"] == f"{ROOT}/{CAMPAIGN}/queue_state/wave_state.jsonl"

    def test_the_log_moved_into_the_campaigns_queue_state_dir(self):
        got = _resolve("LOGF", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["LOGF"] == f"{ROOT}/{CAMPAIGN}/queue_state/queue_runner.log"

    def test_campaign_home_is_the_id_under_the_collection_root(self):
        got = _resolve("CAMPAIGN_HOME", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["CAMPAIGN_HOME"] == f"{ROOT}/{CAMPAIGN}"

    @pytest.mark.parametrize(
        ("name", "leaf"),
        [
            ("CAMPAIGN_CONTROL_DIR", "control"),
            ("QUEUE_STATE_DIR", "queue_state"),
            ("PAIR_SUMMARY_DIR", "pair_summaries"),
        ],
    )
    def test_each_subdirectory_is_its_own_leaf_under_the_home(self, name, leaf):
        got = _resolve(name, WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got[name] == f"{ROOT}/{CAMPAIGN}/{leaf}"

    def test_the_stamp_is_a_fixed_name_inside_the_control_dir(self):
        """The filename no longer carries the id — the DIRECTORY does.
        That is the whole mechanism change (D-E-1)."""
        got = _resolve("CAMPAIGN_STAMP", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["CAMPAIGN_STAMP"] == f"{ROOT}/{CAMPAIGN}/control/campaign.json"

    @pytest.mark.parametrize("name", AUTHORITY_PATHS)
    def test_every_authority_bearing_path_contains_the_campaign_id(self, name):
        """Checkpoint E1, stated as one property rather than five literals.

        A per-path literal assertion cannot express "no authority-bearing
        path may be campaign-blind" — which is exactly the shape of the
        defect `QUEUE_STOP_FILE` had.
        """
        cid = "sentinelcampaign"
        got = _resolve(name, WS_ROOT=ROOT, CAMPAIGN_ID=cid)
        assert f"/{cid}/" in got[name] + "/", (
            f"{name} resolved to {got[name]!r}, which does not sit under a "
            f"campaign-scoped directory; two campaigns can collide on it"
        )

    def test_two_campaigns_share_no_authority_bearing_path(self):
        """The property the §1 incident violated, asserted directly."""
        a = _resolve(*AUTHORITY_PATHS, WS_ROOT=ROOT, CAMPAIGN_ID="alpha")
        b = _resolve(*AUTHORITY_PATHS, WS_ROOT=ROOT, CAMPAIGN_ID="beta")
        for name in AUTHORITY_PATHS:
            assert a[name] != b[name], f"campaigns alpha and beta share {name}"


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
        assert got[name].startswith(f"{ROOT}/{CAMPAIGN}/"), (
            f"{name} accepted an independent override ({got[name]!r}); two "
            "campaigns could now share one state directory"
        )

    def test_the_derived_directories_follow_the_home(self):
        got = _resolve(
            "CAMPAIGN_CONTROL_DIR",
            "QUEUE_STATE_DIR",
            "PAIR_SUMMARY_DIR",
            WS_ROOT=ROOT,
            CAMPAIGN_HOME="/tmp/elsewhere",
        )
        assert set(got.values()) == {
            "/tmp/elsewhere/control",
            "/tmp/elsewhere/queue_state",
            "/tmp/elsewhere/pair_summaries",
        }

    def test_the_stop_file_override_still_wins(self):
        """Compatibility only (§4.2): the docs table and
        `test_c13_stop_semantics.py` both pass it explicitly, so only the
        DEFAULT moved."""
        got = _resolve(
            "QUEUE_STOP_FILE",
            WS_ROOT=ROOT,
            CAMPAIGN_ID=CAMPAIGN,
            QUEUE_STOP_FILE="/tmp/explicit/STOP",
        )
        assert got["QUEUE_STOP_FILE"] == "/tmp/explicit/STOP"


class TestTheShellAndPythonAgreeOnTheLayout:
    """The three subdirectory names are declared twice — in the runner,
    which needs `LOGF` before it may call Python, and in
    `core.campaign_identity`, which is what actually creates them.

    The duplication is forced. Drift between the two halves is not: the
    runner would log to a directory nothing creates, and the failure would
    surface as a missing log at launch rather than at review.
    """

    def test_the_runner_resolves_exactly_the_directories_python_creates(self):
        from core.campaign_identity import campaign_subdir_paths

        home = f"{ROOT}/{CAMPAIGN}"
        got = _resolve(
            "CAMPAIGN_CONTROL_DIR",
            "QUEUE_STATE_DIR",
            "PAIR_SUMMARY_DIR",
            WS_ROOT=ROOT,
            CAMPAIGN_ID=CAMPAIGN,
        )
        assert set(got.values()) == set(campaign_subdir_paths(home))

    def test_the_runner_resolves_the_stamp_python_publishes(self):
        from core.campaign_identity import stamp_path_for

        got = _resolve("CAMPAIGN_STAMP", WS_ROOT=ROOT, CAMPAIGN_ID=CAMPAIGN)
        assert got["CAMPAIGN_STAMP"] == stamp_path_for(f"{ROOT}/{CAMPAIGN}")


class TestDefinitionScopeTouchesNothing:
    def test_sourcing_creates_no_campaign_directory(self, tmp_path):
        """The campaign directories are created by the admission guard in
        `main()`, which validates the id FIRST — never at definition
        scope, where merely reading the file would create them, and where
        a `..` id would resolve a path outside the collection root."""
        root = tmp_path / "root"
        _resolve("CAMPAIGN_HOME", WS_ROOT=str(root), CAMPAIGN_ID=CAMPAIGN)
        assert not root.exists(), "sourcing the runner created the campaign root"
