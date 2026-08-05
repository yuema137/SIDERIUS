"""Two campaigns under one root, and neither can reach the other.

V20 PR E, checkpoint E5 — the acceptance evidence for the whole PR.

The §1 incident: at 08:17 an operator stopped one campaign and stopped a
different one as well, because `QUEUE_STOP_FILE` defaulted to
`$WS_ROOT/STOP` — one file shared by everything under the root. Two
campaigns (`v19r2_10iter_…` and `v19r3_10iter_…`) shared a `WS_ROOT` of
`v19/`, so the stop was ambiguous by construction.

This file **observes** the fix rather than asserting a configuration
value. Every test runs the real launcher against a real temporary tree
and then looks at the filesystem: what a campaign wrote, what it did not
write, whether the other campaign's files moved, and whether a chain
actually launched. A `screen` shim records every invocation, so "nothing
launched" and "something launched" are both assertions.

**There is no negative control in this module.** The mutations that
prove these tests can fail are run against the implementation and
recorded in the design document; an `xfail`-shaped test that passes by
failing is indistinguishable from a broken test six months later.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"

#: The queue's "stopped on request" exit code (C13).
STOP_EXIT = 99


def _shim(tmp_path: Path) -> tuple[Path, Path]:
    """A `screen` that lists nothing and records every other invocation."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir(exist_ok=True)
    record = tmp_path / "screen_invocations.txt"
    exe = shim_dir / "screen"
    exe.write_text(
        f'#!/bin/bash\nif [ "$1" = "-ls" ]; then exit 1; fi\necho "$@" >> {record}\nexit 0\n'
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return shim_dir, record


def _run(
    tmp_path: Path, campaign_id: str, *args: str, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run the real launcher for one campaign against the shared root."""
    shim_dir, record = _shim(tmp_path)
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    result = subprocess.run(
        ["bash", str(RUNNER), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=dict(
            os.environ,
            WS_ROOT=str(root),
            CAMPAIGN_ID=campaign_id,
            EXIT_DIR=str(tmp_path / "markers" / campaign_id),
            PATH=f"{shim_dir}:{os.environ['PATH']}",
            **env,
        ),
        timeout=120,
    )
    result.screen_invocations = record.read_text() if record.exists() else ""  # type: ignore[attr-defined]
    record.unlink(missing_ok=True)
    return result


def _snapshot(directory: Path) -> dict[Path, tuple[bytes, int]]:
    """Bytes and mtime of every file under a directory."""
    if not directory.exists():
        return {}
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.rglob("*") if p.is_file()}


def _records(root: Path, campaign_id: str) -> list[dict]:
    state = root / campaign_id / "queue_state" / "wave_state.jsonl"
    if not state.exists():
        return []
    return [json.loads(line) for line in state.read_text().splitlines() if line.strip()]


def _completed(root: Path, campaign_id: str, run: str) -> None:
    state = root / campaign_id / "queue_state" / "wave_state.jsonl"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(f'{{"run": "{run}", "wave": 1, "exit": 0, "start": "s", "end": "e"}}\n')


def _two_campaign_tree(tmp_path: Path) -> Path:
    """The §9 fixture: a legacy global STOP, two campaign homes, and
    `alpha`'s own STOP armed.

        <root>/STOP                  legacy global — no authority
        <root>/alpha/control/STOP    alpha is stopped
        <root>/alpha/...             alpha's state
        <root>/beta/...              beta's state
    """
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    (root / "STOP").write_text("")
    for campaign_id in ("alpha", "beta"):
        for sub in ("control", "queue_state", "pair_summaries"):
            (root / campaign_id / sub).mkdir(parents=True, exist_ok=True)
    (root / "alpha" / "control" / "STOP").touch()
    return root


class TestOneCampaignsStopDoesNotStopTheOther:
    """THE §1 INCIDENT. Before PR E both campaigns read `$WS_ROOT/STOP`,
    so stopping one stopped every campaign under the root."""

    def test_the_stopped_campaign_stops_with_the_right_reason_and_code(self, tmp_path):
        root = _two_campaign_tree(tmp_path)
        # `alpha`'s wave-1 workspaces exist, so a launch would be refused
        # before `screen` even if the stop check failed to fire.
        for run in ("alpha_arch_15_19", "alpha_loss_15_19"):
            (root / run).mkdir()

        r = _run(tmp_path, "alpha")

        assert r.returncode == STOP_EXIT
        stops = [rec for rec in _records(root, "alpha") if rec.get("queue_stopped")]
        assert stops and stops[-1]["reason"] == "operator_stop_requested"
        assert r.screen_invocations == ""  # type: ignore[attr-defined]

    def test_the_other_campaign_reaches_its_launch_unaffected(self, tmp_path):
        """`beta` must not observe `alpha`'s STOP. Proved by reaching the
        `screen` shim — a launch, not merely the absence of a record."""
        root = _two_campaign_tree(tmp_path)

        r = _run(tmp_path, "beta")

        assert r.returncode != STOP_EXIT, "beta stopped on alpha's STOP file"
        stops = [rec for rec in _records(root, "beta") if rec.get("queue_stopped")]
        assert [s["reason"] for s in stops] != ["operator_stop_requested"]
        assert "siderius-beta_arch_15_19" in r.screen_invocations  # type: ignore[attr-defined]

    def test_neither_campaign_honours_the_legacy_global_stop(self, tmp_path):
        """BD-2. `$WS_ROOT/STOP` is the file that caused the incident. It
        has no authority over either campaign and is never deleted."""
        root = _two_campaign_tree(tmp_path)
        (root / "alpha" / "control" / "STOP").unlink()
        legacy = root / "STOP"
        before = (legacy.read_bytes(), legacy.stat().st_mtime_ns)

        for campaign_id in ("alpha", "beta"):
            r = _run(tmp_path, campaign_id)
            assert r.returncode != STOP_EXIT, f"{campaign_id} honoured the legacy STOP"

        assert legacy.exists(), "the legacy global STOP was deleted"
        assert (legacy.read_bytes(), legacy.stat().st_mtime_ns) == before


class TestNeitherCampaignWritesIntoTheOther:
    """Directory scoping is only real if the writes actually land in the
    campaign's own home. Asserted by bytes and mtime over the whole
    neighbouring tree, not by reading the path variables."""

    def test_a_beta_run_leaves_alphas_tree_byte_identical(self, tmp_path):
        root = _two_campaign_tree(tmp_path)
        _run(tmp_path, "alpha")  # alpha writes its own stamp and state
        before = _snapshot(root / "alpha")
        assert before, "the fixture produced no alpha files to compare"

        _run(tmp_path, "beta")

        assert _snapshot(root / "alpha") == before

    def test_an_alpha_run_leaves_betas_tree_byte_identical(self, tmp_path):
        root = _two_campaign_tree(tmp_path)
        _run(tmp_path, "beta")
        before = _snapshot(root / "beta")
        assert before, "the fixture produced no beta files to compare"

        _run(tmp_path, "alpha")

        assert _snapshot(root / "beta") == before

    def test_each_campaign_stamps_only_its_own_home(self, tmp_path):
        root = _two_campaign_tree(tmp_path)
        (root / "alpha" / "control" / "STOP").unlink()

        _run(tmp_path, "alpha")
        _run(tmp_path, "beta")

        for campaign_id in ("alpha", "beta"):
            stamp = json.loads((root / campaign_id / "control" / "campaign.json").read_text())
            assert stamp["campaign_id"] == campaign_id
            assert stamp["campaign_home"] == str(root / campaign_id)

    def test_canonical_and_derived_records_stay_in_their_own_home(self, tmp_path):
        """E-C4's two destinations are both campaign-scoped. A wave
        summary written into the neighbour's `pair_summaries/` would be
        the §1 defect with an extra step."""
        root = _two_campaign_tree(tmp_path)
        (root / "alpha" / "control" / "STOP").unlink()

        for campaign_id in ("alpha", "beta"):
            _run(tmp_path, campaign_id)

        for campaign_id, other in (("alpha", "beta"), ("beta", "alpha")):
            for record in _records(root, campaign_id):
                assert record.get("campaign_id", campaign_id) == campaign_id
                assert other not in json.dumps(record), (
                    f"{campaign_id}'s state names {other}: {record}"
                )


class TestTheCampaignsCannotBeConfusedForEachOther:
    def test_the_run_names_and_markers_are_disjoint(self, tmp_path):
        """Run names carry the campaign id (§4.4), which is why chain
        workspaces can stay flat under one root. `EXIT_DIR` markers are
        named from the run, so they are disjoint for the same reason."""
        root = _two_campaign_tree(tmp_path)
        (root / "alpha" / "control" / "STOP").unlink()

        launches = {}
        for campaign_id in ("alpha", "beta"):
            launches[campaign_id] = _run(tmp_path, campaign_id).screen_invocations  # type: ignore[attr-defined]

        assert "siderius-alpha_arch_15_19" in launches["alpha"]
        assert "siderius-beta_arch_15_19" in launches["beta"]
        assert "beta" not in launches["alpha"]
        assert "alpha" not in launches["beta"]

    def test_a_wave_record_id_names_its_own_campaign(self, tmp_path):
        """D-E-3a's `record_id` is `<campaign_id>:<wave>:<band>:<attempt>`.
        Two campaigns reaching the same wave must not produce colliding
        ids, or the two histories become impossible to tell apart."""
        root = _two_campaign_tree(tmp_path)
        (root / "alpha" / "control" / "STOP").unlink()

        ids = {}
        for campaign_id in ("alpha", "beta"):
            _run(tmp_path, campaign_id)
            ids[campaign_id] = [
                rec["record_id"] for rec in _records(root, campaign_id) if "record_id" in rec
            ]

        for campaign_id in ("alpha", "beta"):
            assert all(rid.startswith(f"{campaign_id}:") for rid in ids[campaign_id]), ids
        assert not set(ids["alpha"]) & set(ids["beta"])

    def test_a_foreign_stamp_stops_the_run_rather_than_sharing_the_home(self, tmp_path):
        """The remaining way to collide is to point one campaign at the
        other's home. The stamp is what makes that detectable."""
        root = _two_campaign_tree(tmp_path)
        (root / "alpha" / "control" / "STOP").unlink()
        _run(tmp_path, "alpha")
        before = _snapshot(root / "alpha")

        r = _run(tmp_path, "beta", CAMPAIGN_HOME=str(root / "alpha"))

        assert r.returncode != 0
        assert "alpha" in r.stderr and "beta" in r.stderr
        assert _snapshot(root / "alpha") == before


class TestLegacyAdoptionIsPerCampaign:
    def test_only_the_owning_campaign_adopts_its_legacy_state(self, tmp_path):
        """BC-2 is scoped: `alpha`'s pre-PR-E file is not `beta`'s to
        read, and a run recorded complete only in it must not let `beta`
        skip anything."""
        root = tmp_path / "root"
        root.mkdir()
        legacy = root / "alpha_wave_state.jsonl"
        legacy.write_text('{"run": "alpha_arch_15_19", "wave": 1, "exit": 0}\n')
        _completed(root, "beta", "beta_loss_00_03")

        alpha = _run(tmp_path, "alpha", "--only", "alpha_arch_15_19")
        beta = _run(tmp_path, "beta", "--only", "beta_arch_15_19")

        alpha_stamp = json.loads((root / "alpha" / "control" / "campaign.json").read_text())
        beta_stamp = json.loads((root / "beta" / "control" / "campaign.json").read_text())
        assert alpha_stamp["legacy_adopted_from"] == str(legacy)
        assert beta_stamp["legacy_adopted_from"] is None

        assert alpha.screen_invocations == ""  # type: ignore[attr-defined]
        assert "siderius-beta_arch_15_19" in beta.screen_invocations  # type: ignore[attr-defined]
        assert (legacy.read_text().count("\n")) == 1, "the legacy file was written to"
