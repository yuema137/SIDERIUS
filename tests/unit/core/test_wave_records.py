"""The wave record: canonical evidence, derived view, and the order.

V20 PR E, D-E-3 and D-E-3a.

One record goes to two places, so three things have to be true and none
of them is checkable by reading the code:

- the canonical JSONL is written and made durable **first**, so a failure
  between the steps loses the convenience and never the evidence;
- a derived write that fails is reported as *itself*, not as a lost
  record, because "the summary is missing" and "the evidence is missing"
  call for different operator responses;
- a retried wave produces a **different** ``record_id``, so the one
  mutable per-wave file can always be tied back to the append-only
  history it came from.
"""

from __future__ import annotations

import json
import os

import pytest

from core.wave_records import (
    CanonicalWriteError,
    ChainRecord,
    DerivedWriteError,
    WaveSummaryRecord,
    build_record_id,
    derived_filename,
    next_attempt,
    write_wave_summary,
)

ARCH = ChainRecord(run_name="v20a_arch_15_19", role="arch", pid="111", exit=0)
LOSS = ChainRecord(run_name="v20a_loss_15_19", role="loss", pid="222", exit=137)


def _write(tmp_path, chains=None, wave=1, disposition="complete", campaign_id="v20a"):
    return write_wave_summary(
        canonical_path=str(tmp_path / "queue_state" / "wave_state.jsonl"),
        derived_dir=str(tmp_path / "pair_summaries"),
        campaign_id=campaign_id,
        wave=wave,
        band="15-19",
        band_tag="15_19",
        chains=chains if chains is not None else [ARCH, LOSS],
        start="2026-08-04T00:00:00",
        end="2026-08-04T05:00:00",
        disposition=disposition,
    )


def _canonical_records(tmp_path) -> list[dict]:
    path = tmp_path / "queue_state" / "wave_state.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestTheCanonicalRecordIsWrittenFirst:
    def test_both_destinations_receive_the_same_record(self, tmp_path):
        record = _write(tmp_path)
        canonical = _canonical_records(tmp_path)[0]
        derived = json.loads(
            (tmp_path / "pair_summaries" / derived_filename(1, "15_19")).read_text()
        )
        assert canonical == derived
        assert canonical["record_id"] == record.record_id

    def test_a_failed_derived_write_keeps_the_canonical_record(self, tmp_path):
        """THE ORDER, observed. `pair_summaries` is a FILE here, so the
        derived write cannot succeed — and the evidence must survive it."""
        (tmp_path / "queue_state").mkdir()
        (tmp_path / "pair_summaries").write_text("not a directory")

        with pytest.raises(DerivedWriteError):
            _write(tmp_path)

        records = _canonical_records(tmp_path)
        assert len(records) == 1
        assert records[0]["disposition"] == "complete"

    def test_a_derived_failure_is_not_reported_as_a_lost_record(self, tmp_path):
        """The two errors are distinct types on purpose: collapsing them
        would report a missing convenience file as missing evidence, and
        invite a retry that duplicates the canonical record."""
        (tmp_path / "queue_state").mkdir()
        (tmp_path / "pair_summaries").write_text("not a directory")
        with pytest.raises(DerivedWriteError) as exc:
            _write(tmp_path)
        assert not isinstance(exc.value, CanonicalWriteError)
        assert "canonical record is written" in str(exc.value)

    def test_an_unwritable_canonical_path_writes_nothing_anywhere(self, tmp_path):
        (tmp_path / "queue_state").write_text("not a directory")
        with pytest.raises(CanonicalWriteError):
            _write(tmp_path)
        assert not (tmp_path / "pair_summaries").exists(), (
            "the derived view was written without its canonical record"
        )

    def test_no_temp_file_survives_either_outcome(self, tmp_path):
        _write(tmp_path)
        _write(tmp_path, wave=2)
        leftovers = [p.name for p in (tmp_path / "pair_summaries").iterdir()]
        assert all(not name.endswith(".tmp") for name in leftovers), leftovers

    def test_the_derived_file_is_valid_json_after_an_overwrite(self, tmp_path):
        """`os.replace` means a reader sees the old file or the new one,
        never a torn one."""
        _write(tmp_path, disposition="failed")
        _write(tmp_path, disposition="complete")
        derived = json.loads(
            (tmp_path / "pair_summaries" / derived_filename(1, "15_19")).read_text()
        )
        assert derived["disposition"] == "complete"


class TestRetryProducesADistinguishableRecord:
    def test_a_retried_wave_gets_a_new_record_id(self, tmp_path):
        """The JSONL appends and the per-wave file overwrites, so without
        this the file could not be tied to an attempt."""
        first = _write(tmp_path, disposition="failed")
        second = _write(tmp_path, disposition="complete")

        assert first.record_id == "v20a:1:15_19:1"
        assert second.record_id == "v20a:1:15_19:2"
        assert first.record_id != second.record_id

    def test_both_attempts_survive_in_the_canonical_history(self, tmp_path):
        _write(tmp_path, disposition="failed")
        _write(tmp_path, disposition="complete")
        records = _canonical_records(tmp_path)
        assert [r["disposition"] for r in records] == ["failed", "complete"]
        assert [r["record_id"] for r in records] == ["v20a:1:15_19:1", "v20a:1:15_19:2"]

    def test_the_derived_file_holds_the_latest_attempt(self, tmp_path):
        _write(tmp_path, disposition="failed")
        second = _write(tmp_path, disposition="complete")
        derived = json.loads(
            (tmp_path / "pair_summaries" / derived_filename(1, "15_19")).read_text()
        )
        assert derived["record_id"] == second.record_id

    def test_the_attempt_count_survives_a_restart(self, tmp_path):
        """Counted from the file, not from launcher state — a queue
        restart must not reset it back to attempt 1 and produce two
        records claiming to be the first."""
        _write(tmp_path)
        assert (
            next_attempt(
                str(tmp_path / "queue_state" / "wave_state.jsonl"),
                campaign_id="v20a",
                wave=1,
                band_tag="15_19",
            )
            == 2
        )

    def test_different_waves_and_campaigns_count_separately(self, tmp_path):
        _write(tmp_path, wave=1)
        _write(tmp_path, wave=2)
        _write(tmp_path, wave=1, campaign_id="v20b")
        ids = [r["record_id"] for r in _canonical_records(tmp_path)]
        assert ids == ["v20a:1:15_19:1", "v20a:2:15_19:1", "v20b:1:15_19:1"]

    def test_unparseable_and_foreign_lines_are_not_counted_as_attempts(self, tmp_path):
        """The JSONL holds several record types and may hold pre-PR-E
        lines. A line that cannot be read is not evidence of an attempt."""
        path = tmp_path / "queue_state" / "wave_state.jsonl"
        path.parent.mkdir()
        path.write_text('not json at all\n{"run": "v20a_arch_15_19", "wave": 1, "exit": 0}\n[]\n\n')
        assert next_attempt(str(path), campaign_id="v20a", wave=1, band_tag="15_19") == 1

    def test_a_missing_canonical_file_is_attempt_one(self, tmp_path):
        assert (
            next_attempt(
                str(tmp_path / "nothing.jsonl"),
                campaign_id="v20a",
                wave=1,
                band_tag="15_19",
            )
            == 1
        )

    def test_the_record_id_shape_is_fixed(self):
        assert (
            build_record_id(campaign_id="v20a", wave=3, band_tag="04_09", attempt=2)
            == "v20a:3:04_09:2"
        )


class TestTheCompatibilityMirror:
    """Six `arch_*`/`loss_*` keys, emitted ONLY for a two-chain wave whose
    roles are exactly arch and loss. FU-E-1 removes them once the operator
    report tooling reads `chains`."""

    def _record(self, chains) -> dict:
        return WaveSummaryRecord(
            record_id="c:1:t:1",
            campaign_id="c",
            wave=1,
            band="15-19",
            band_tag="15_19",
            chains=chains,
            start="s",
            end="e",
            disposition="complete",
        ).to_record()

    def test_a_two_role_wave_gets_the_mirror(self):
        record = self._record([ARCH, LOSS])
        assert record["arch_run"] == ARCH.run_name
        assert record["loss_exit"] == 137
        assert record["arch_pid"] == "111"

    @pytest.mark.parametrize(
        ("chains", "why"),
        [
            ([ARCH], "a single-chain wave"),
            (
                [ARCH, LOSS, ChainRecord(run_name="c", role="probe", exit=0)],
                "a three-chain wave",
            ),
            (
                [
                    ChainRecord(run_name="a", role="alpha", exit=0),
                    ChainRecord(run_name="b", role="beta", exit=0),
                ],
                "two chains with other roles",
            ),
            (
                [ARCH, ChainRecord(run_name="b", role=None, exit=0)],
                "an unresolved role",
            ),
        ],
    )
    def test_a_non_standard_wave_gets_no_fabricated_mirror(self, chains, why):
        """An invented `arch_exit` is worse than an absent one, because a
        report would show it."""
        record = self._record(chains)
        for key in ("arch_run", "loss_run", "arch_exit", "loss_exit", "arch_pid", "loss_pid"):
            assert key not in record, f"{why} produced a fabricated {key}"

    def test_the_chains_array_is_always_correct(self):
        chains = [ARCH, LOSS, ChainRecord(run_name="c", role="probe", pid="3", exit=1)]
        record = self._record(chains)
        assert [c["run_name"] for c in record["chains"]] == [
            "v20a_arch_15_19",
            "v20a_loss_15_19",
            "c",
        ]
        assert [c["role"] for c in record["chains"]] == ["arch", "loss", "probe"]

    def test_an_unresolved_role_is_null_not_a_guess(self):
        record = self._record([ChainRecord(run_name="x", exit=0)])
        assert record["chains"][0]["role"] is None

    def test_an_unresolved_role_is_stated_not_merely_left_null(self):
        """E-C4b. `"role": null` with no mirror is ambiguous: it could be
        a wave with unusual roles by design, or a ROSTER lookup that
        failed. Those call for opposite operator responses, so the record
        says which."""
        record = self._record([ARCH, ChainRecord(run_name="mystery", exit=0)])
        assert record["role_resolution_failed"] is True
        assert record["unresolved_roles"] == ["mystery"]

    def test_a_fully_resolved_record_carries_no_failure_marker(self):
        """Absent, not `false` — a normal record stays byte-identical to
        the pre-E-C4b shape."""
        record = self._record([ARCH, LOSS])
        assert "role_resolution_failed" not in record
        assert "unresolved_roles" not in record

    def test_the_marker_does_not_overload_disposition(self):
        """`disposition` describes what happened to the CHAINS. A
        recording gap is not a chain outcome, and an operator filtering
        on `disposition == "complete"` must not lose the wave."""
        record = self._record([ARCH, ChainRecord(run_name="mystery", exit=0)])
        assert record["disposition"] == "complete"


class TestTheChainsArrayCannotForgeCompletion:
    def test_the_field_is_run_name_not_run(self, tmp_path):
        """THE REGRESSION. `chain_completed` greps the whole line for
        `"run": "<X>"` then for `"exit": 0`, so a chains array spelled
        `run` would let one chain's success mark every chain in the wave
        complete. Asserted on the serialised bytes, because that is what
        the grep sees."""
        _write(tmp_path, chains=[ARCH, LOSS])
        line = (tmp_path / "queue_state" / "wave_state.jsonl").read_text()
        assert '"run_name":' in line
        assert '"run":' not in line, (
            "the wave summary emits a bare `run` key; a failed chain in "
            "this wave now reads as complete to chain_completed"
        )


# A `TestTheRecordIsValidated` class was drafted here and deleted before
# commit. Its three cases — an empty `chains` list, a non-integer exit, a
# `-1` round-tripping — asserted `Field(min_length=1)`, a declared `int`,
# and a hardcoded value against itself. All three are enforced by the
# Pydantic declaration, so by CLAUDE.md's rule they were decoration:
# deleting them leaves no defect uncaught. The behaviour that IS
# reachable-and-testable — a chainless invocation writing NOTHING, and a
# missing marker recording `-1` rather than `0` — is asserted end to end
# in `test_campaign_admission.py`, through the real launcher.


class TestDerivedFilename:
    def test_it_carries_the_wave_and_band(self):
        assert derived_filename(3, "04_09") == "wave_3_04_09.json"

    def test_two_waves_never_share_a_file(self, tmp_path):
        _write(tmp_path, wave=1)
        _write(tmp_path, wave=2)
        names = sorted(p.name for p in (tmp_path / "pair_summaries").iterdir())
        assert names == ["wave_1_15_19.json", "wave_2_15_19.json"]


class TestFsyncOrdering:
    def test_the_canonical_file_is_fsynced_before_the_derived_write(self, tmp_path, monkeypatch):
        """Reachability for the durability claim: without the fsync, a
        crash between the two writes could leave the derived file on disk
        and the canonical line still in the page cache."""
        events: list[str] = []
        real_fsync = os.fsync
        real_replace = os.replace

        def spy_fsync(fd):
            events.append("fsync")
            return real_fsync(fd)

        def spy_replace(src, dst):
            events.append("replace")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "fsync", spy_fsync)
        monkeypatch.setattr(os, "replace", spy_replace)

        _write(tmp_path)

        assert events[0] == "fsync", events
        assert events.index("replace") > events.index("fsync"), events
