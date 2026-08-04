"""The campaign identity, the stamp, and the order admission runs in.

V20 PR E, D-E-9 and §4.2a.

`campaign_id` becomes a directory name, so it is a path component chosen
by an operator on a command line. Two failure modes follow, and both are
guarded here:

- an id that escapes its collection root (`..`), or is not a legal
  filename at all;
- a campaign home whose owner cannot be proven, so campaign `beta` writes
  into the state directory campaign `alpha` already owns.

The **order** is as load-bearing as the checks. An id validated after
`mkdir` has already created the directory it was supposed to prevent, and
a stamp validated after a write has already performed the write it was
supposed to refuse. The ordering tests observe the filesystem before and
after; they do not read the implementation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.campaign_identity import (
    CAMPAIGN_SUBDIRS,
    CampaignIdError,
    CampaignStamp,
    CampaignStampError,
    admit_campaign,
    adopted_legacy_state,
    legacy_wave_state_name,
    read_campaign_stamp,
    resolve_adoption,
    stamp_path_for,
    validate_campaign_id,
)


def _admit(
    home: Path,
    campaign_id: str = "alpha",
    ws_root: Path | None = None,
    *,
    adoption: bool = False,
):
    """Admit a campaign. `adoption=True` supplies the two paths that
    enable the BC-2 decision, which the launcher always passes."""
    root = ws_root or home.parent
    extra = {}
    if adoption:
        extra = {
            "wave_state": str(home / "queue_state" / "wave_state.jsonl"),
            "legacy_wave_state": str(root / legacy_wave_state_name(campaign_id)),
        }
    return admit_campaign(
        campaign_id=campaign_id,
        ws_root=str(root),
        campaign_home=str(home),
        runner="v19_queue_runner.sh",
        runner_pid=4242,
        **extra,
    )


class TestTheIdentityRule:
    """D-E-9: `fullmatch([A-Za-z0-9._-]{1,128})` and not equal to `.`/`..`."""

    @pytest.mark.parametrize(
        ("value", "why"),
        [
            ("", "empty — would resolve the home to the collection root"),
            (".", "the current directory"),
            ("..", "the parent — escapes the collection root"),
            ("a/b", "a path separator"),
            ("/abs", "an absolute path"),
            ("../escape", "a traversal prefix"),
            ("a\\b", "a backslash"),
            ("a\nb", "a control character"),
            ("a\x00b", "a NUL"),
            ("a b", "a space is not in the class"),
            ("x" * 129, "over the 128-character bound"),
        ],
    )
    def test_an_unsafe_id_is_refused(self, value, why):
        with pytest.raises(CampaignIdError):
            validate_campaign_id(value)

    @pytest.mark.parametrize("value", ["alpha..beta", "a.b_c-d", "v19", "x", "x" * 128])
    def test_a_safe_id_is_accepted(self, value):
        """POSITIVE CONTROL, and the reason it exists.

        The rule rejects an id **equal to** `.` or `..`. It must never
        tighten to "contains `..`": `alpha..beta` is an ordinary
        directory name, and since `/` and `\\` are already excluded the
        id is always exactly one segment, so it cannot traverse. Without
        this case the validator could silently become stricter and no
        test would notice.
        """
        assert validate_campaign_id(value) == value

    def test_a_stamp_cannot_grandfather_an_unsafe_id(self):
        """A stamp written before this validator existed is still read
        through it — otherwise the file becomes a way to reintroduce the
        id the command line refuses."""
        with pytest.raises(Exception) as exc:
            CampaignStamp(
                campaign_id="../escape",
                created_at="2026-08-04T00:00:00Z",
                ws_root="/r",
                campaign_home="/r/x",
                runner="v19_queue_runner.sh",
                runner_pid=1,
            )
        assert "safe path component" in str(exc.value) or "traversal" in str(exc.value)


class TestAdmissionOrder:
    """The two guarantees of §4.2a, observed on the filesystem."""

    def test_an_invalid_id_creates_nothing(self, tmp_path):
        """GUARANTEE 1: refuse before ANY mkdir.

        `..` is the case that matters — the resolved home would be the
        collection root's parent, and a `mkdir -p` there succeeds.
        """
        before = sorted(p.name for p in tmp_path.iterdir())
        with pytest.raises(CampaignIdError):
            _admit(tmp_path / "..", campaign_id="..")
        assert sorted(p.name for p in tmp_path.iterdir()) == before

    def test_a_foreign_stamp_is_refused_before_anything_is_written(self, tmp_path):
        """GUARANTEE 2: refuse before any new state write.

        The pre-existing directories are not this run's side effect, so
        their presence is not a violation; a NEW file would be.
        """
        home = tmp_path / "alpha"
        _admit(home)  # campaign alpha owns it
        before = {p: p.stat().st_mtime_ns for p in home.rglob("*")}

        with pytest.raises(CampaignStampError) as exc:
            _admit(home, campaign_id="beta")

        assert "alpha" in str(exc.value) and "beta" in str(exc.value)
        assert {p: p.stat().st_mtime_ns for p in home.rglob("*")} == before

    def test_admission_creates_the_three_directories_and_one_stamp(self, tmp_path):
        home = tmp_path / "alpha"
        result = _admit(home)
        assert result.outcome == "created"
        for name in CAMPAIGN_SUBDIRS:
            assert (home / name).is_dir(), name
        assert (home / "control" / "campaign.json").is_file()

    def test_a_second_run_validates_without_rewriting(self, tmp_path):
        """Re-running the same campaign is the normal resume case: the
        stamp is proof of ownership, not a per-run record."""
        home = tmp_path / "alpha"
        _admit(home)
        stamp = home / "control" / "campaign.json"
        before = (stamp.read_text(), stamp.stat().st_mtime_ns)

        result = _admit(home)

        assert result.outcome == "validated"
        assert (stamp.read_text(), stamp.stat().st_mtime_ns) == before

    def test_a_campaign_dir_without_a_stamp_is_adopted(self, tmp_path):
        """Every pre-PR-E campaign is this case: the directory may exist,
        the stamp cannot."""
        home = tmp_path / "alpha"
        (home / "queue_state").mkdir(parents=True)
        (home / "queue_state" / "wave_state.jsonl").write_text("{}\n")

        result = _admit(home)

        assert result.outcome == "created"
        assert (home / "queue_state" / "wave_state.jsonl").read_text() == "{}\n"

    def test_legacy_adopted_from_is_declared_and_null(self, tmp_path):
        """E-C3 populates it. Declaring it here means adoption is a value
        change, not a schema change."""
        result = _admit(tmp_path / "alpha")
        assert result.stamp.legacy_adopted_from is None
        payload = json.loads((tmp_path / "alpha" / "control" / "campaign.json").read_text())
        assert "legacy_adopted_from" in payload
        assert payload["legacy_adopted_from"] is None


class TestTheStampMustBeReadable:
    """A stamp that cannot be parsed cannot prove a match, and a home
    whose owner is unknown may not be launched into."""

    @pytest.mark.parametrize(
        ("content", "why"),
        [
            ("", "empty"),
            ("{", "truncated"),
            ("[]", "not an object"),
            ('{"created_at": "x"}', "no campaign_id"),
            (
                '{"campaign_id": "../escape", "created_at": "t", "ws_root": "/r", '
                '"campaign_home": "/r/x", "runner": "r", "runner_pid": 1}',
                "unsafe recorded id",
            ),
        ],
    )
    def test_an_unusable_stamp_refuses(self, tmp_path, content, why):
        home = tmp_path / "alpha"
        (home / "control").mkdir(parents=True)
        stamp_path_for(str(home))
        Path(stamp_path_for(str(home))).write_text(content)

        with pytest.raises(CampaignStampError):
            _admit(home)

    def test_an_absent_stamp_is_a_value_not_an_error(self, tmp_path):
        assert read_campaign_stamp(str(tmp_path / "nothing.json")) is None


class TestFirstWriterWins:
    def test_a_losing_writer_validates_instead_of_overwriting(self, tmp_path):
        """The `os.link` property, exercised through admission.

        Simulated rather than threaded: the stamp is published between
        this caller's inspection and its write, which is exactly the
        window a concurrent runner occupies. The loser must accept the
        winner's file, not clobber it.
        """
        home = tmp_path / "alpha"
        _admit(home)
        stamp = home / "control" / "campaign.json"
        winner_pid = json.loads(stamp.read_text())["runner_pid"]

        result = admit_campaign(
            campaign_id="alpha",
            ws_root=str(tmp_path),
            campaign_home=str(home),
            runner="v19_queue_runner.sh",
            runner_pid=winner_pid + 1,
        )

        assert result.outcome == "validated"
        assert json.loads(stamp.read_text())["runner_pid"] == winner_pid

    def test_no_temp_file_survives_a_publish(self, tmp_path):
        home = tmp_path / "alpha"
        _admit(home)
        _admit(home)
        leftovers = [p.name for p in (home / "control").iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []


class TestUnwritableRoot:
    def test_a_read_only_root_is_reported_with_the_path(self, tmp_path):
        """Fatal, and named: an unstampable campaign cannot be guarded,
        so continuing would launch work into an unbound directory."""
        root = tmp_path / "ro"
        root.mkdir()
        os.chmod(root, 0o500)
        try:
            with pytest.raises(OSError) as exc:
                _admit(root / "alpha")
            assert "alpha" in str(exc.value)
        finally:
            os.chmod(root, 0o700)


class TestAdoptionIsDecidedOnce:
    """BC-2. Adoption is a campaign-level MODE granted at first start,
    never a per-record fallback.

    The rejected design consulted the legacy file whenever the new state
    happened to lack a record. Its worst case is that a run recorded
    complete ONLY in legacy gets skipped on the strength of a file the
    new campaign was never meant to obey — cross-STATE authority instead
    of cross-CAMPAIGN authority, which is the same defect wearing a
    different hat.
    """

    def _legacy(self, root: Path, campaign_id: str = "alpha") -> Path:
        path = root / legacy_wave_state_name(campaign_id)
        path.write_text('{"run": "alpha_arch_15_19", "wave": 1, "exit": 0}\n')
        return path

    def test_first_start_with_legacy_present_adopts_it(self, tmp_path):
        legacy = self._legacy(tmp_path)
        result = _admit(tmp_path / "alpha", adoption=True)
        assert result.stamp.legacy_adopted_from == str(legacy)

    def test_first_start_without_legacy_adopts_nothing(self, tmp_path):
        result = _admit(tmp_path / "alpha", adoption=True)
        assert result.stamp.legacy_adopted_from is None

    def test_an_existing_canonical_state_blocks_adoption(self, tmp_path):
        """THE BLOCKER CASE, at the decision layer.

        The campaign already has its own history, so the legacy file is
        never in range — however many records the new state is missing.
        """
        self._legacy(tmp_path)
        home = tmp_path / "alpha"
        (home / "queue_state").mkdir(parents=True)
        (home / "queue_state" / "wave_state.jsonl").write_text("")

        result = _admit(home, adoption=True)

        assert result.stamp.legacy_adopted_from is None

    def test_a_legacy_file_appearing_later_is_never_adopted(self, tmp_path):
        """Monotonicity: adoption can only be granted at first start, so a
        file restored from a backup cannot acquire authority over a
        campaign that is already running."""
        home = tmp_path / "alpha"
        first = _admit(home, adoption=True)
        assert first.stamp.legacy_adopted_from is None
        stamp_file = Path(first.stamp_path)
        before = (stamp_file.read_text(), stamp_file.stat().st_mtime_ns)

        self._legacy(tmp_path)
        second = _admit(home, adoption=True)

        assert second.stamp.legacy_adopted_from is None
        assert (stamp_file.read_text(), stamp_file.stat().st_mtime_ns) == before

    def test_another_campaigns_legacy_file_is_out_of_range(self, tmp_path):
        """Scoping. `beta`'s legacy file is not `alpha`'s to adopt, and
        the check is a comparison rather than a naming convention."""
        (tmp_path / legacy_wave_state_name("beta")).write_text("{}\n")
        result = _admit(tmp_path / "alpha", adoption=True)
        assert result.stamp.legacy_adopted_from is None

    def test_the_decision_needs_both_paths(self, tmp_path):
        """A caller that supplies neither gets no adoption rather than a
        guess — the launcher always supplies both."""
        self._legacy(tmp_path)
        result = _admit(tmp_path / "alpha", adoption=False)
        assert result.stamp.legacy_adopted_from is None


class TestAdoptionIsNotAReadCapability:
    """A stamp records ONE adoption decision. It is not a licence to read
    an arbitrary file, so the recorded path is re-validated at every use
    and not only when it was written."""

    def _stamp(self, tmp_path: Path, adopted: str) -> CampaignStamp:
        return CampaignStamp(
            campaign_id="alpha",
            created_at="2026-08-04T00:00:00Z",
            ws_root=str(tmp_path),
            campaign_home=str(tmp_path / "alpha"),
            runner="v19_queue_runner.sh",
            runner_pid=1,
            legacy_adopted_from=adopted,
        )

    @pytest.mark.parametrize(
        "adopted",
        [
            "/etc/passwd",
            "beta_wave_state.jsonl",
            "sub/alpha_wave_state.jsonl",
            "alpha_wave_state.jsonl.bak",
        ],
    )
    def test_a_tampered_adoption_path_is_refused(self, tmp_path, adopted):
        """MUTATION TARGET: honouring the field as written.

        A hand-edited stamp must stop the run, not widen what it may
        read.
        """
        path = adopted if adopted.startswith("/") else str(tmp_path / adopted)
        with pytest.raises(CampaignStampError):
            adopted_legacy_state(self._stamp(tmp_path, path))

    def test_the_campaigns_own_legacy_path_is_accepted(self, tmp_path):
        """POSITIVE CONTROL — without it the validator could tighten to
        "refuse everything" and every test above would still pass."""
        good = str(tmp_path / legacy_wave_state_name("alpha"))
        assert adopted_legacy_state(self._stamp(tmp_path, good)) == good

    def test_no_adoption_is_a_value_not_an_error(self, tmp_path):
        stamp = self._stamp(tmp_path, str(tmp_path / legacy_wave_state_name("alpha")))
        assert adopted_legacy_state(stamp.model_copy(update={"legacy_adopted_from": None})) is None

    def test_a_stamp_with_a_tampered_path_stops_admission(self, tmp_path):
        """Reachability: the re-validation must be on the production
        admission path, not only in a helper nobody calls."""
        home = tmp_path / "alpha"
        (home / "control").mkdir(parents=True)
        Path(stamp_path_for(str(home))).write_text(
            self._stamp(tmp_path, "/etc/passwd").model_dump_json()
        )
        with pytest.raises(CampaignStampError):
            _admit(home, adoption=True)

    def test_an_adopted_path_that_vanished_is_still_reported_as_adopted(self, tmp_path):
        """Absence is not tampering. A missing file yields no completion
        evidence at read time — the chain is launched — but it must not
        be mistaken for a stamp that names the wrong file."""
        good = str(tmp_path / legacy_wave_state_name("alpha"))
        assert not os.path.exists(good)
        assert adopted_legacy_state(self._stamp(tmp_path, good)) == good


class TestResolveAdoptionDirectly:
    def test_it_refuses_a_legacy_path_outside_the_root(self, tmp_path):
        with pytest.raises(CampaignStampError):
            resolve_adoption(
                campaign_id="alpha",
                ws_root=str(tmp_path),
                wave_state=str(tmp_path / "alpha" / "queue_state" / "wave_state.jsonl"),
                legacy_wave_state="/etc/passwd",
            )
