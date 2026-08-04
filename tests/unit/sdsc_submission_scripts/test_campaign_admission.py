"""Campaign admission: the guard that binds a run to its state directory.

V20 PR E, checkpoints E-C2 (§4.2a), E-C2b and E-C3 (BC-2, BC-3).

These tests run the **real launcher** against a temporary root and then
look at the filesystem. That is deliberate: every claim admission makes is
about a side effect and its ORDER, and neither can be checked by reading a
variable back out of the script.

A PATH `screen` shim records every invocation, so **both** directions are
assertions rather than assumptions: "no chain was launched" is an empty
record, and E-C3's blocker case — a run recorded complete only in a
legacy file must still be LAUNCHED — is a non-empty one. No real chain
starts: the shim's `-ls` reports nothing alive, so the launcher records a
missing marker and stops. Where a wave run must not reach `screen` at
all, `block_launches=True` pre-creates the workspaces so the launcher's
own workspace-exists guard refuses first.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"

#: Exit code the queue uses for "stopped on request" (C13).
STOP_EXIT = 99


def _screen_shim(tmp_path: Path) -> tuple[Path, Path]:
    """A `screen` that lists nothing and RECORDS every other invocation.

    A launch is `screen -dmS …`, so a non-empty record file is proof the
    runner tried to start a chain.
    """
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir(exist_ok=True)  # tests that run the launcher twice
    record = tmp_path / "screen_invocations.txt"
    shim = shim_dir / "screen"
    shim.write_text(
        f'#!/bin/bash\nif [ "$1" = "-ls" ]; then exit 1; fi\necho "$@" >> {record}\nexit 0\n'
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return shim_dir, record


def _run(
    tmp_path: Path,
    *args: str,
    campaign_id: str | None = "v19",
    block_launches: bool = False,
    **env: str,
) -> subprocess.CompletedProcess[str]:
    """Run the launcher. `campaign_id=None` leaves the variable UNSET,
    which is a different input from the empty string (E-C2b)."""
    shim_dir, record = _screen_shim(tmp_path)
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    if block_launches:
        # The workspace-exists guard refuses before `screen` is reached,
        # so a full wave run terminates deterministically without
        # starting anything or entering the 90 s pair stagger.
        for run in (f"{campaign_id}_arch_15_19", f"{campaign_id}_loss_15_19"):
            (root / run).mkdir(exist_ok=True)
    child_env = dict(
        os.environ,
        WS_ROOT=str(root),
        EXIT_DIR=str(tmp_path / "markers"),
        PATH=f"{shim_dir}:{os.environ['PATH']}",
        **env,
    )
    if campaign_id is None:
        child_env.pop("CAMPAIGN_ID", None)
    else:
        child_env["CAMPAIGN_ID"] = campaign_id
    result = subprocess.run(
        ["bash", str(RUNNER), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=child_env,
        timeout=120,
    )
    result.screen_invocations = record.read_text() if record.exists() else ""  # type: ignore[attr-defined]
    return result


def _completed(root: Path, campaign_id: str, run: str) -> None:
    state = root / campaign_id / "queue_state" / "wave_state.jsonl"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(f'{{"run": "{run}", "wave": 1, "exit": 0, "start": "s", "end": "e"}}\n')


def _write_stamp(root: Path, home_id: str, stamped_as: str) -> Path:
    control = root / home_id / "control"
    control.mkdir(parents=True, exist_ok=True)
    path = control / "campaign.json"
    path.write_text(
        json.dumps(
            {
                "campaign_id": stamped_as,
                "created_at": "2026-08-04T00:00:00Z",
                "ws_root": str(root),
                "campaign_home": str(root / home_id),
                "runner": "v19_queue_runner.sh",
                "runner_pid": 1,
                "legacy_adopted_from": None,
            }
        )
    )
    return path


class TestARunCreatesItsCampaignHome:
    def test_a_targeted_run_creates_the_three_directories_and_the_stamp(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        _completed(root, "v19", "v19_arch_15_19")

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert r.returncode == 0, r.stderr
        home = root / "v19"
        assert (home / "control").is_dir()
        assert (home / "queue_state").is_dir()
        assert (home / "pair_summaries").is_dir()
        assert (home / "control" / "campaign.json").is_file()
        assert (home / "queue_state" / "queue_runner.log").is_file()

    def test_the_stamp_records_this_campaigns_identity(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        _completed(root, "v19", "v19_arch_15_19")

        _run(tmp_path, "--only", "v19_arch_15_19")

        stamp = json.loads((root / "v19" / "control" / "campaign.json").read_text())
        assert stamp["campaign_id"] == "v19"
        assert stamp["campaign_home"] == str(root / "v19")
        assert stamp["legacy_adopted_from"] is None

    def test_the_resolved_paths_are_logged_at_startup(self, tmp_path):
        """BD-1 is operator-visible: someone who touches the old shared
        STOP must be able to see, from the log alone, which file this
        campaign actually reads."""
        root = tmp_path / "root"
        root.mkdir()
        _completed(root, "v19", "v19_arch_15_19")

        _run(tmp_path, "--only", "v19_arch_15_19")

        log = (root / "v19" / "queue_state" / "queue_runner.log").read_text()
        assert "campaign admission:" in log
        assert str(root / "v19" / "control" / "STOP") in log
        assert str(root / "v19" / "queue_state" / "wave_state.jsonl") in log

    def test_re_running_the_same_campaign_validates_the_existing_stamp(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        _completed(root, "v19", "v19_arch_15_19")

        _run(tmp_path, "--only", "v19_arch_15_19")
        stamp = root / "v19" / "control" / "campaign.json"
        before = (stamp.read_text(), stamp.stat().st_mtime_ns)
        _run(tmp_path, "--only", "v19_arch_15_19")

        assert (stamp.read_text(), stamp.stat().st_mtime_ns) == before


class TestAnUnsafeIdIsRefusedBeforeAnythingIsCreated:
    # The EMPTY id has its own class below: proving it is refused requires
    # distinguishing it from an UNSET variable, which this parametrize
    # cannot express.
    @pytest.mark.parametrize("campaign_id", ["..", ".", "a/b", "a b", "x" * 129])
    def test_the_run_refuses_and_the_root_gains_nothing(self, tmp_path, campaign_id):
        """D-E-9's ordering guarantee, observed rather than inferred: the
        listing before and after must be identical, so no `mkdir` ran."""
        root = tmp_path / "root"
        root.mkdir()
        before = sorted(p.name for p in root.iterdir())

        r = _run(tmp_path, "--only", "v19_arch_15_19", campaign_id=campaign_id)

        assert r.returncode != 0
        assert sorted(p.name for p in root.iterdir()) == before
        assert "REFUSED" in r.stderr
        assert r.screen_invocations == ""  # type: ignore[attr-defined]

    def test_the_parent_of_the_root_is_untouched_by_a_dotdot_id(self, tmp_path):
        """The specific hazard: `CAMPAIGN_ID=..` resolves the home to the
        collection root's PARENT, so an unvalidated `mkdir -p` would
        create a campaign's control state OUTSIDE its collection root —
        and succeed, silently.

        Asserted on the three directories admission creates rather than on
        a whole-tree listing, so the test names the escape it is looking
        for instead of failing on unrelated harness files.
        """
        root = tmp_path / "root"
        root.mkdir()

        r = _run(tmp_path, "--only", "v19_arch_15_19", campaign_id="..")

        assert r.returncode != 0
        for leaked in ("control", "queue_state", "pair_summaries"):
            assert not (tmp_path / leaked).exists(), (
                f"a `..` campaign id created {leaked}/ outside the collection root"
            )

    def test_an_id_containing_two_dots_is_accepted(self, tmp_path):
        """POSITIVE CONTROL (D-E-9). The rule rejects an id EQUAL to `.`
        or `..`, never one that merely contains `..`. `alpha..beta` is a
        legal directory name that cannot traverse, and without this case
        the validator could tighten silently."""
        root = tmp_path / "root"
        root.mkdir()
        _completed(root, "alpha..beta", "alpha..beta_arch_15_19")

        r = _run(
            tmp_path,
            "--only",
            "alpha..beta_arch_15_19",
            campaign_id="alpha..beta",
        )

        assert r.returncode == 0, r.stderr
        assert (root / "alpha..beta" / "control").is_dir()


class TestAnUnsetIdAndAnEmptyIdAreDifferentInputs:
    """E-C2b. `${CAMPAIGN_ID-v19}`, not `${CAMPAIGN_ID:-v19}`.

    The two expansions differ on exactly one input, and it is the
    dangerous one. `:-` treats an explicitly empty value as if the
    variable had never been set, so an operator who CLEARS the variable
    specifically to avoid reusing an identity gets `v19` — the identity
    they were avoiding — and then writes into that campaign's control
    state. D-E-9 requires an empty id to be refused; under `:-` it could
    never reach the validator to be refused.

    Unset must keep defaulting, because that is every existing caller.
    """

    def test_an_unset_id_still_defaults_to_v19(self, tmp_path):
        """BACKWARD COMPATIBILITY. Every caller that never set the
        variable — the docs, the operator's muscle memory, the other
        tests in this suite — must be unaffected."""
        root = tmp_path / "root"
        root.mkdir()
        _completed(root, "v19", "v19_arch_15_19")

        r = _run(tmp_path, "--only", "v19_arch_15_19", campaign_id=None)

        assert r.returncode == 0, r.stderr
        assert (root / "v19" / "control" / "campaign.json").is_file()
        stamp = json.loads((root / "v19" / "control" / "campaign.json").read_text())
        assert stamp["campaign_id"] == "v19"

    def test_an_explicitly_empty_id_is_refused(self, tmp_path):
        """MUTATION TARGET: restoring `${CAMPAIGN_ID:-v19}`.

        Under `:-` this run silently becomes campaign `v19` and exits 0.
        """
        root = tmp_path / "root"
        root.mkdir()

        r = _run(tmp_path, "--only", "v19_arch_15_19", campaign_id="")

        assert r.returncode != 0, "an explicitly empty campaign id was accepted"
        assert "REFUSED" in r.stderr

    def test_the_empty_id_refusal_touches_nothing(self, tmp_path):
        """The full refusal contract in one place: no directory created,
        no STOP consulted, no state written, no chain launched.

        The STOP claim is asserted through the exit code. A run that read
        a STOP and obeyed it exits 99 (`CHAIN_STOP_EXIT_CODE`) and leaves
        a `queue_stopped` record; a refusal exits 1 and leaves none. Both
        a legacy shared STOP and a `v19` campaign STOP are armed here, so
        if the empty id resolved to either location the run would stop
        rather than refuse.
        """
        root = tmp_path / "root"
        root.mkdir()
        (root / "STOP").touch()
        (root / "v19" / "control").mkdir(parents=True)
        (root / "v19" / "control" / "STOP").touch()
        before = sorted(p.name for p in root.iterdir())

        r = _run(tmp_path, "--only", "v19_arch_15_19", campaign_id="")

        assert r.returncode == 1, f"expected a refusal (1), got {r.returncode}"
        assert r.returncode != STOP_EXIT, "the empty id read a STOP file"
        assert sorted(p.name for p in root.iterdir()) == before
        assert not (root / "v19" / "queue_state").exists(), "state was written"
        assert r.screen_invocations == ""  # type: ignore[attr-defined]

    def test_the_runner_uses_the_unset_only_expansion(self):
        """MUTATION TARGET, stated structurally so the one-character
        difference cannot be reintroduced by a careless edit."""
        src = RUNNER.read_text(encoding="utf-8")
        assert 'CAMPAIGN_ID="${CAMPAIGN_ID-v19}"' in src
        assert 'CAMPAIGN_ID="${CAMPAIGN_ID:-v19}"' not in src


class TestAForeignStampRefusesBeforeAnyWrite:
    def test_a_mismatched_stamp_stops_the_run(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        _write_stamp(root, "v19", stamped_as="beta")

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert r.returncode != 0
        assert "beta" in r.stderr and "v19" in r.stderr
        assert r.screen_invocations == ""  # type: ignore[attr-defined]

    def test_the_refusal_writes_no_state_into_the_foreign_home(self, tmp_path):
        """The refusal is reported to stderr and NOT appended to the wave
        state: writing a record about campaign A's refused launch into the
        home campaign B owns is the cross-campaign write this PR removes."""
        root = tmp_path / "root"
        root.mkdir()
        stamp = _write_stamp(root, "v19", stamped_as="beta")
        before = {p: p.stat().st_mtime_ns for p in (root / "v19").rglob("*")}

        _run(tmp_path, "--only", "v19_arch_15_19")

        assert {p: p.stat().st_mtime_ns for p in (root / "v19").rglob("*")} == before
        assert json.loads(stamp.read_text())["campaign_id"] == "beta"
        assert not (root / "v19" / "queue_state").exists()

    @pytest.mark.parametrize("content", ["", "{", "[]", '{"created_at": "x"}'])
    def test_an_unreadable_stamp_stops_the_run(self, tmp_path, content):
        """A stamp that cannot be parsed cannot prove a match, and a home
        whose owner is unknown may not be launched into."""
        root = tmp_path / "root"
        root.mkdir()
        (root / "v19" / "control").mkdir(parents=True)
        (root / "v19" / "control" / "campaign.json").write_text(content)

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert r.returncode != 0
        assert r.screen_invocations == ""  # type: ignore[attr-defined]


class TestTheStopFileIsCampaignScoped:
    def test_the_campaigns_own_stop_file_stops_the_queue(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        (root / "v19" / "control").mkdir(parents=True)
        (root / "v19" / "control" / "STOP").touch()

        r = _run(tmp_path, block_launches=True)

        assert r.returncode == STOP_EXIT
        records = [
            json.loads(line)
            for line in (root / "v19" / "queue_state" / "wave_state.jsonl").read_text().splitlines()
            if line.strip()
        ]
        stops = [rec for rec in records if rec.get("queue_stopped")]
        assert stops and stops[-1]["reason"] == "operator_stop_requested"
        assert r.screen_invocations == ""  # type: ignore[attr-defined]

    def test_a_legacy_shared_stop_no_longer_stops_the_queue(self, tmp_path):
        """BD-2, and the §1 incident in one assertion: `$WS_ROOT/STOP` is
        the file that halted an unrelated campaign. It is not consulted.

        (Its observation RECORD is E-C3. This commit proves only that it
        has no authority.)
        """
        root = tmp_path / "root"
        root.mkdir()
        (root / "STOP").touch()

        r = _run(tmp_path, block_launches=True)

        assert r.returncode != STOP_EXIT, "the legacy shared STOP still stopped the queue"
        state = root / "v19" / "queue_state" / "wave_state.jsonl"
        reasons = [
            json.loads(line).get("reason")
            for line in state.read_text().splitlines()
            if line.strip() and json.loads(line).get("queue_stopped")
        ]
        assert "operator_stop_requested" not in reasons
        assert (root / "STOP").exists(), "the legacy STOP was deleted; it must be preserved"
        assert r.screen_invocations == ""  # type: ignore[attr-defined]


class TestAdmissionIsReachedBeforeAnythingElse:
    SRC = RUNNER.read_text(encoding="utf-8")

    def test_the_guard_is_called_from_main_before_the_only_branch(self):
        """MUTATION TARGET: deleting or relocating the call.

        Reachability, not presence: the admission call must sit between
        argument parsing and the first branch that can launch or write.
        """
        body = self.SRC[self.SRC.index("main() {") :]
        admit = body.index('ADMIT_OUT="$(admit_campaign)"')
        only = body.index('if [ -n "$ONLY" ]; then')
        assert admit < only
        assert body.index("mkdir -p") > admit

    def test_no_log_call_precedes_admission(self):
        """`log()` appends to LOGF, which now lives in a directory the
        admission guard is what creates. A `log` above it would fail —
        and under `set -e` would kill the runner with no diagnostic."""
        body = self.SRC[self.SRC.index("main() {") :]
        prologue = body[: body.index('ADMIT_OUT="$(admit_campaign)"')]
        offending = [
            line
            for line in prologue.splitlines()
            # comments quote `log` while explaining why it is absent
            if line.split("#", 1)[0].strip().startswith("log ")
        ]
        assert not offending, f"log() is called before the log directory exists: {offending}"

    def test_the_refusal_uses_the_guarded_invocation_form(self):
        """MUTATION TARGET: the `$3a.4` hazard.

        `set -e` is inherited from `_chain_common.sh:40`. A bare
        `VAR="$(admit_campaign)"` followed by `RC=$?` terminates the shell
        at the failure, before any diagnostic runs — fail-closed by
        accident, and indistinguishable in the artifacts from a crash.
        """
        assert 'ADMIT_OUT="$(admit_campaign)" || ADMIT_RC=$?' in self.SRC

    def test_errexit_is_still_enabled_where_the_refusal_runs(self, tmp_path):
        """The guarded form must not have been bought by disabling
        `errexit` — that would silently weaken every other command."""
        root = tmp_path / "root"
        root.mkdir()
        r = _run(tmp_path, "--only", "v19_arch_15_19", campaign_id="..")
        assert r.returncode != 0
        # `main` runs with the inherited options; prove they are still set
        # by asking the runner itself.
        probe = subprocess.run(
            [
                "bash",
                "-c",
                f"V19_QUEUE_NO_MAIN=1 source '{RUNNER}'; case $- in *e*) echo ERREXIT;; esac",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=dict(os.environ, WS_ROOT=str(root)),
            timeout=60,
        )
        assert "ERREXIT" in probe.stdout


class TestLegacyAdoption:
    """E-C3, BC-2. A campaign interrupted before the PR E move resumes
    without relaunching what it finished — and a legacy file never
    acquires standing authority over a campaign that did not adopt it.

    Every test here runs the real launcher, so "the chain is launched" is
    an observation of the `screen` shim, not an inference.
    """

    def _legacy(self, root: Path, campaign_id: str, run: str) -> Path:
        path = root / f"{campaign_id}_wave_state.jsonl"
        path.write_text(f'{{"run": "{run}", "wave": 1, "exit": 0, "start": "s", "end": "e"}}\n')
        return path

    def _canonical(self, root: Path, campaign_id: str, body: str = "") -> Path:
        path = root / campaign_id / "queue_state" / "wave_state.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    def test_a_pre_move_campaign_resumes_without_relaunching(self, tmp_path):
        """First start, no canonical state, legacy present → adopt, and
        the completed chain is skipped."""
        root = tmp_path / "root"
        root.mkdir()
        legacy = self._legacy(root, "v19", "v19_arch_15_19")

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert r.returncode == 0, r.stderr
        stamp = json.loads((root / "v19" / "control" / "campaign.json").read_text())
        assert stamp["legacy_adopted_from"] == str(legacy)
        log = (root / "v19" / "queue_state" / "queue_runner.log").read_text()
        assert "SKIP v19_arch_15_19: already completed" in log
        assert r.screen_invocations == ""  # type: ignore[attr-defined]

    def test_a_run_complete_only_in_legacy_is_launched_when_state_exists(self, tmp_path):
        """**THE BLOCKER CASE.**

        Canonical state exists and lacks the record; the legacy file has
        it. The chain MUST launch. The rejected per-record fallback would
        have skipped it — letting a file this campaign never adopted
        decide that work was already done.
        """
        root = tmp_path / "root"
        root.mkdir()
        self._canonical(root, "v19", '{"run": "v19_loss_10_14", "wave": 2, "exit": 0}\n')
        self._legacy(root, "v19", "v19_arch_15_19")

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        stamp = json.loads((root / "v19" / "control" / "campaign.json").read_text())
        assert stamp["legacy_adopted_from"] is None, "adoption was granted after first start"
        log = (root / "v19" / "queue_state" / "queue_runner.log").read_text()
        assert "SKIP v19_arch_15_19" not in log, (
            "a run recorded complete ONLY in the legacy file was skipped"
        )
        assert "siderius-v19_arch_15_19" in r.screen_invocations, (  # type: ignore[attr-defined]
            "the chain was not launched"
        )

    def test_a_legacy_file_appearing_later_never_gains_authority(self, tmp_path):
        """Monotonicity, end to end: adoption is decided at first start,
        so a file restored from a backup afterwards changes nothing."""
        root = tmp_path / "root"
        root.mkdir()
        self._canonical(root, "v19", "")

        # A first run with no legacy file present, purely to create the
        # stamp. Its launch outcome is not the subject and is not asserted.
        _run(tmp_path, "--only", "v19_loss_00_03")
        stamp_file = root / "v19" / "control" / "campaign.json"
        before = (stamp_file.read_text(), stamp_file.stat().st_mtime_ns)

        self._legacy(root, "v19", "v19_arch_15_19")
        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert (stamp_file.read_text(), stamp_file.stat().st_mtime_ns) == before
        assert json.loads(stamp_file.read_text())["legacy_adopted_from"] is None
        log = (root / "v19" / "queue_state" / "queue_runner.log").read_text()
        assert "SKIP v19_arch_15_19" not in log
        assert "siderius-v19_arch_15_19" in r.screen_invocations  # type: ignore[attr-defined]

    def test_another_campaigns_legacy_file_is_never_adopted(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        self._legacy(root, "beta", "v19_arch_15_19")

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        stamp = json.loads((root / "v19" / "control" / "campaign.json").read_text())
        assert stamp["legacy_adopted_from"] is None
        assert "siderius-v19_arch_15_19" in r.screen_invocations  # type: ignore[attr-defined]

    def test_a_fresh_post_pr_e_campaign_adopts_nothing(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        _completed(root, "v19", "v19_arch_15_19")

        _run(tmp_path, "--only", "v19_arch_15_19")

        stamp = json.loads((root / "v19" / "control" / "campaign.json").read_text())
        assert stamp["legacy_adopted_from"] is None
        log = (root / "v19" / "queue_state" / "queue_runner.log").read_text()
        assert "legacy state: not adopted" in log

    @pytest.mark.parametrize("content", ["", "not json at all\n", "\x00\x01binary"])
    def test_an_unusable_adopted_file_yields_no_evidence(self, tmp_path, content):
        """Warn and continue, never block. Refusing here would hand a
        legacy file veto power over a new campaign — the opposite of what
        adoption is for. No evidence means the chain launches."""
        root = tmp_path / "root"
        root.mkdir()
        (root / "v19_wave_state.jsonl").write_text(content)

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        stamp = json.loads((root / "v19" / "control" / "campaign.json").read_text())
        assert stamp["legacy_adopted_from"] == str(root / "v19_wave_state.jsonl")
        assert "siderius-v19_arch_15_19" in r.screen_invocations  # type: ignore[attr-defined]

    def test_an_adopted_file_deleted_afterwards_yields_no_evidence(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        legacy = self._legacy(root, "v19", "v19_arch_15_19")

        _run(tmp_path, "--only", "v19_arch_15_19")  # adopts, skips
        legacy.unlink()
        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert "siderius-v19_arch_15_19" in r.screen_invocations  # type: ignore[attr-defined]

    def test_a_tampered_adoption_path_stops_the_run(self, tmp_path):
        """A stamp records one decision; it is not a read capability."""
        root = tmp_path / "root"
        root.mkdir()
        control = root / "v19" / "control"
        control.mkdir(parents=True)
        (control / "campaign.json").write_text(
            json.dumps(
                {
                    "campaign_id": "v19",
                    "created_at": "2026-08-04T00:00:00Z",
                    "ws_root": str(root),
                    "campaign_home": str(root / "v19"),
                    "runner": "v19_queue_runner.sh",
                    "runner_pid": 1,
                    "legacy_adopted_from": "/etc/passwd",
                }
            )
        )

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert r.returncode != 0
        assert r.screen_invocations == ""  # type: ignore[attr-defined]

    def test_the_legacy_filename_appears_only_in_a_read_position(self):
        """MUTATION TARGET: a write that targets the legacy filename.

        BC-1: nothing on disk is moved, rewritten or deleted by shipped
        code.
        """
        live = [
            line.strip()
            for line in RUNNER.read_text(encoding="utf-8").splitlines()
            if "_wave_state" in line and not line.strip().startswith("#")
        ]
        assert live == ['LEGACY_WAVE_STATE="$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl"'], live


class TestTheLegacyGlobalStopIsObservedNotHonoured:
    """BC-3. The file that halted an unrelated campaign in the 08:17
    incident. Ignoring it silently would destroy the operator's ability to
    reconstruct that; honouring it would reproduce the defect."""

    def test_it_is_recorded_and_the_run_continues(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        legacy_stop = root / "STOP"
        legacy_stop.touch()
        _completed(root, "v19", "v19_arch_15_19")

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert r.returncode == 0, r.stderr
        records = [
            json.loads(line)
            for line in (root / "v19" / "queue_state" / "wave_state.jsonl").read_text().splitlines()
            if line.strip()
        ]
        observed = [rec for rec in records if rec.get("legacy_global_stop_observed")]
        assert len(observed) == 1, records
        assert observed[0]["path"] == str(legacy_stop)
        assert observed[0]["mtime"] != "unknown"
        assert observed[0]["honoured"] is False
        assert observed[0]["removed"] is False

    def test_it_is_not_deleted(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        legacy_stop = root / "STOP"
        legacy_stop.touch()
        before = (legacy_stop.stat().st_mtime_ns, legacy_stop.stat().st_size)
        _completed(root, "v19", "v19_arch_15_19")

        _run(tmp_path, "--only", "v19_arch_15_19")

        assert legacy_stop.exists(), "the legacy global STOP was deleted"
        assert (legacy_stop.stat().st_mtime_ns, legacy_stop.stat().st_size) == before

    def test_no_record_is_written_when_it_is_absent(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        _completed(root, "v19", "v19_arch_15_19")

        _run(tmp_path, "--only", "v19_arch_15_19")

        text = (root / "v19" / "queue_state" / "wave_state.jsonl").read_text()
        assert "legacy_global_stop_observed" not in text


class TestLegacyBytesAreNeverTouched:
    """E2 evidence: BC-1 asserted over a whole fixture tree, by bytes and
    mtime, rather than by reading the code for writes."""

    def test_a_legacy_tree_is_byte_and_mtime_identical_after_a_run(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        (root / "v19_wave_state.jsonl").write_text(
            '{"run": "v19_arch_15_19", "wave": 1, "exit": 0, "start": "s", "end": "e"}\n'
        )
        (root / "v19_queue_runner.log").write_text("2026-07-31 08:17:00 legacy log line\n")
        (root / "STOP").write_text("")
        (root / "v19_campaign.json").write_text('{"legacy": "stamp"}\n')
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir() if p.is_file()}

        r = _run(tmp_path, "--only", "v19_arch_15_19")

        assert r.returncode == 0, r.stderr
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir() if p.is_file()}
        assert after == before, "a pre-existing legacy file was modified"
