"""S2 / U5 (#257, #258) — ``LocalRecorder`` over the canonical record log.

The defect class: the summary WAS the history, rewritten in place; a torn
summary read as ``[]`` and the next save rewrote the run's history as one
record. Each test below names the specific way that comes back.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.record_log import (
    RECORD_LOG_BASENAME,
    RecordHistoryUnreadable,
    project_latest_by_exp_id,
)
from core.sandbox_executor import LocalRecorder

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN = "run"


def _recorder(ws: Path) -> LocalRecorder:
    return LocalRecorder(str(ws / "records"), str(ws / f"summary_{RUN}.json"), RUN)


def _summary_path(ws: Path) -> Path:
    return ws / f"summary_{RUN}.json"


def _log_path(ws: Path) -> Path:
    return ws / "records" / RUN / RECORD_LOG_BASENAME


def _rec(exp_id: str, **extra) -> dict:
    return {"exp_id": exp_id, "status": "success", "denoising_score": 1.0, **extra}


class TestAppendOnlyCase:
    def test_summary_bytes_are_identical_to_the_legacy_writer(self, tmp_path):
        """DEFECT: a projection/format drift changes the bytes of the view
        every reader in U5's list consumes (tuner, dashboard, scripts,
        REC-3). Expected bytes come from ``json.dump``'s documented
        arguments on the SAME input, never from the recorder."""
        rec = _recorder(tmp_path)
        records = [_rec("e1"), _rec("e2", note="ü"), _rec("e3")]
        for r in records:
            rec.save_record(r)
        assert _summary_path(tmp_path).read_bytes() == json.dumps(
            records, indent=4, ensure_ascii=False
        ).encode("utf-8")
        lines = _log_path(tmp_path).read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == records
        assert rec.get_summary() == records

    def test_every_record_gets_an_atomic_detail_file(self, tmp_path):
        rec = _recorder(tmp_path)
        rec.save_record(_rec("e1"))
        detail = tmp_path / "records" / RUN / "e1.json"
        assert json.loads(detail.read_text(encoding="utf-8")) == _rec("e1")
        assert not [n for n in os.listdir(detail.parent) if n.endswith(".tmp")]


class TestUpsertContract:
    def test_latest_wins_by_exp_id_in_first_insertion_order(self, tmp_path):
        """DEFECT: the upsert dependents (resumed baseline, recovered
        diagnostic round, ``MongoRecorder`` parity) need ONE row per exp_id
        in first-insertion order. A plain append yields three rows; a
        latest-position projection reorders. Fails on either."""
        rec = _recorder(tmp_path)
        rec.save_record(_rec("A", version=1))
        rec.save_record(_rec("B"))
        rec.save_record(_rec("A", version=2))

        assert rec.get_summary() == [_rec("A", version=2), _rec("B")]
        assert json.loads(_summary_path(tmp_path).read_text()) == [_rec("A", version=2), _rec("B")]
        # The history is append-only: the superseded version is still evidence.
        assert len(_log_path(tmp_path).read_text().splitlines()) == 3

    def test_projection_keeps_id_less_records_apart(self):
        """DEFECT: keying on ``exp_id`` alone collapses every id-less record
        under ``None``. Fails if two such records become one."""
        assert project_latest_by_exp_id([{"a": 1}, {"a": 2}]) == [{"a": 1}, {"a": 2}]


class TestCrashRecovery:
    def test_a_torn_summary_is_rebuilt_from_the_log_never_empty(self, tmp_path):
        """THE AMPLIFIER (#257): ``get_summary`` mapped a torn summary to
        ``[]`` and the next save rewrote history as one record. Fails if
        the torn view is trusted, or if the next save loses a record."""
        rec = _recorder(tmp_path)
        rec.save_record(_rec("e1"))
        rec.save_record(_rec("e2"))
        healthy = _summary_path(tmp_path).read_bytes()
        _summary_path(tmp_path).write_bytes(healthy[: len(healthy) // 2])

        assert rec.get_summary() == [_rec("e1"), _rec("e2")]
        # The view was repaired in place from the canonical log.
        assert json.loads(_summary_path(tmp_path).read_text()) == [_rec("e1"), _rec("e2")]

        rec.save_record(_rec("e3"))
        assert json.loads(_summary_path(tmp_path).read_text()) == [
            _rec("e1"),
            _rec("e2"),
            _rec("e3"),
        ]

    def test_a_crash_between_canonical_append_and_view_publish_loses_nothing(
        self, tmp_path, monkeypatch
    ):
        """DEFECT: the record is durable in the log before the view is
        published; a crash between the two must not lose it. Fails if the
        view publish is not the LAST step, or if the log is not read on
        the next open."""
        rec = _recorder(tmp_path)
        rec.save_record(_rec("e1"))
        summary_file = str(_summary_path(tmp_path))
        real_replace = os.replace

        def crash_on_view(src, dst):
            if os.path.abspath(dst) == os.path.abspath(summary_file):
                raise OSError("simulated crash publishing the derived view")
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", crash_on_view)
        with pytest.raises(OSError, match="derived view"):
            rec.save_record(_rec("e2"))
        monkeypatch.setattr(os, "replace", real_replace)

        # The view on disk is the OLD, intact one (never torn) ...
        assert json.loads(_summary_path(tmp_path).read_text()) == [_rec("e1")]
        # ... and a fresh open sees the full history and repairs the view.
        assert _recorder(tmp_path).get_summary() == [_rec("e1"), _rec("e2")]
        assert json.loads(_summary_path(tmp_path).read_text()) == [_rec("e1"), _rec("e2")]

    def test_a_crash_before_the_detail_file_leaves_history_untouched(self, tmp_path, monkeypatch):
        """ORDER: detail file, then log, then view. Fails if the log gains
        a record whose detail file was never published."""
        rec = _recorder(tmp_path)
        rec.save_record(_rec("e1"))
        real_replace = os.replace

        def crash_on_detail(src, dst):
            if dst.endswith(os.path.join("records", RUN, "e2.json")):
                raise OSError("simulated crash publishing the detail file")
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", crash_on_detail)
        with pytest.raises(OSError, match="detail file"):
            rec.save_record(_rec("e2"))
        assert len(_log_path(tmp_path).read_text().splitlines()) == 1
        assert json.loads(_summary_path(tmp_path).read_text()) == [_rec("e1")]

    def test_a_torn_log_tail_is_skipped_and_the_next_append_recovers(self, tmp_path):
        """DEFECT: a crash mid-append leaves a partial last line; refusing
        the whole log, or gluing the next record onto the fragment, both
        lose the run. Fails if the good record is not returned or the new
        record does not land on its own line."""
        log = _log_path(tmp_path)
        log.parent.mkdir(parents=True)
        log.write_text(json.dumps(_rec("e1")) + "\n" + '{"exp_id": "e2", "status": "succ')
        rec = _recorder(tmp_path)
        assert rec.get_summary() == [_rec("e1")]
        rec.save_record(_rec("e3"))
        assert rec.get_summary() == [_rec("e1"), _rec("e3")]
        lines = log.read_text().split("\n")
        assert len(lines) == 4 and lines[-1] == ""


_KILLED_WRITER = r"""
import sys
from core.sandbox_executor import LocalRecorder

ws = sys.argv[1]
recorder = LocalRecorder(ws + "/records", ws + "/summary_run.json", "run")
for i in range(1_000_000):
    recorder.save_record({"exp_id": f"e{i:05d}", "i": i, "payload": "x" * 4096})
"""


class TestKilledWriter:
    def test_a_sigkilled_writer_leaves_every_completed_record_readable(self, tmp_path):
        """CRASH INJECTION (real process, SIGKILL mid-loop): every record the
        child completed must be readable, in order, with intact content,
        through the same recorder; the view must be rebuildable; nothing
        may read as ``[]``. Fails if any completed record is lost, any
        detail file is missing, or the history collapses."""
        proc = subprocess.Popen(
            [sys.executable, "-c", _KILLED_WRITER, str(tmp_path)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        log = _log_path(tmp_path)
        deadline = time.monotonic() + 180.0
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    _out, err = proc.communicate()
                    pytest.fail(
                        f"writer exited early (rc={proc.returncode}): {err.decode()[-2000:]}"
                    )
                if log.exists() and log.read_bytes().count(b"\n") >= 8:
                    break
                time.sleep(0.02)
            else:
                pytest.fail("the writer never produced 8 records within the deadline")
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=30)

        records = _recorder(tmp_path).get_summary()
        assert len(records) >= 8
        for position, record in enumerate(records):
            assert record == {"exp_id": f"e{position:05d}", "i": position, "payload": "x" * 4096}
            detail = tmp_path / "records" / RUN / f"{record['exp_id']}.json"
            assert json.loads(detail.read_text(encoding="utf-8")) == record
        # The derived view was rebuilt from the log and is complete.
        assert json.loads(_summary_path(tmp_path).read_text(encoding="utf-8")) == records
        # At most the LAST line of the log may be torn; every other parses.
        lines = log.read_text(encoding="utf-8").split("\n")
        for line in lines[:-2]:
            json.loads(line)


class TestLegacyWorkspaces:
    def test_a_pre_s2_summary_is_bootstrapped_without_losing_history(self, tmp_path):
        """DEFECT: the first save on a workspace written before the log
        existed must carry the legacy rounds into the canonical log; an
        empty log would make the next projection drop them. Fails if the
        legacy records are missing from the log or the view, or if a plain
        read already wrote a log."""
        legacy = [_rec("old1"), _rec("old2")]
        _summary_path(tmp_path).write_text(json.dumps(legacy, indent=4))
        rec = _recorder(tmp_path)
        assert rec.get_summary() == legacy
        assert not _log_path(tmp_path).exists(), "a read must not write the log"

        rec.save_record(_rec("new"))
        lines = _log_path(tmp_path).read_text().splitlines()
        assert [json.loads(line) for line in lines] == [*legacy, _rec("new")]
        assert json.loads(_summary_path(tmp_path).read_text()) == [*legacy, _rec("new")]

    def test_an_unreadable_summary_without_a_log_raises_instead_of_reading_empty(self, tmp_path):
        """THE AMPLIFIER, legacy shape: with no log to rebuild from, a torn
        summary must be a loud refusal — ``[]`` would make the next save
        rewrite the run as one record. Fails if either call returns."""
        _summary_path(tmp_path).write_text('[{"exp_id": "old1"}, {"exp_id": ')
        before = _summary_path(tmp_path).read_bytes()
        rec = _recorder(tmp_path)
        with pytest.raises(RecordHistoryUnreadable):
            rec.get_summary()
        with pytest.raises(RecordHistoryUnreadable):
            rec.save_record(_rec("new"))
        assert _summary_path(tmp_path).read_bytes() == before
        assert not _log_path(tmp_path).exists()

    def test_a_fresh_workspace_is_empty_and_untouched(self, tmp_path):
        """Absent is not unreadable: a new run starts from ``[]`` without
        raising and without creating files. Fails if the refusal above is
        over-broad."""
        rec = _recorder(tmp_path)
        assert rec.get_summary() == []
        assert not _summary_path(tmp_path).exists()
        assert not _log_path(tmp_path).exists()
