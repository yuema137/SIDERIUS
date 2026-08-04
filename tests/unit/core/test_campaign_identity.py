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
    read_campaign_stamp,
    stamp_path_for,
    validate_campaign_id,
)


def _admit(home: Path, campaign_id: str = "alpha", ws_root: Path | None = None):
    return admit_campaign(
        campaign_id=campaign_id,
        ws_root=str(ws_root or home.parent),
        campaign_home=str(home),
        runner="v19_queue_runner.sh",
        runner_pid=4242,
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
