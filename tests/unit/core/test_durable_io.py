"""S2 / U5 — the durable publication primitives (``core/durable_io.py``).

Every test names the defect only it can catch and how it fails when the
behaviour breaks. Nothing here re-tests what pyright or a schema enforces.
"""

from __future__ import annotations

import glob
import json
import os

import pytest

from core.durable_io import (
    append_line_durably,
    publish_bytes_atomically,
    publish_bytes_write_once,
    publish_json_atomically,
)


class TestAtomicReplace:
    def test_a_crash_at_publish_leaves_the_previous_file_intact_and_no_temp(
        self, tmp_path, monkeypatch
    ):
        """DEFECT: ``open(path, "w")`` truncates the target BEFORE the new
        bytes exist, so a crash mid-write leaves a torn file. Fails if the
        publish writes into the target directly (old bytes gone) or leaks
        its temp file after the failure."""
        target = tmp_path / "view.json"
        target.write_bytes(b'{"v": 1}')

        def crash(_src, _dst):
            raise OSError("simulated crash at publish")

        monkeypatch.setattr(os, "replace", crash)
        with pytest.raises(OSError, match="simulated crash"):
            publish_bytes_atomically(str(target), b'{"v": 2}')

        assert target.read_bytes() == b'{"v": 1}'
        assert os.listdir(tmp_path) == ["view.json"], "temp file leaked after the failed publish"

    def test_a_serialisation_failure_touches_nothing(self, tmp_path):
        """DEFECT: ``json.dump`` into an already-opened ``"w"`` handle
        truncates first and raises on the first non-serialisable value.
        Fails if serialisation happens after the target is opened."""
        target = tmp_path / "out.json"
        target.write_text('{"old": true}')
        with pytest.raises(TypeError):
            publish_json_atomically(str(target), {"bad": object()})
        assert target.read_text() == '{"old": true}'
        assert os.listdir(tmp_path) == ["out.json"]

    def test_bytes_equal_the_json_dump_call_they_replace(self, tmp_path):
        """DEFECT: format drift (indent / ensure_ascii / trailing newline)
        would change the bytes every existing reader consumes. The expected
        bytes are computed independently from the same input, never read
        back from the function under test."""
        obj = {"exp_id": "é-1", "v": [1, None, 2.5]}
        publish_json_atomically(str(tmp_path / "a.json"), obj, indent=4, ensure_ascii=False)
        assert (tmp_path / "a.json").read_bytes() == json.dumps(
            obj, indent=4, ensure_ascii=False
        ).encode("utf-8")

    def test_the_temp_file_is_invisible_to_the_repository_json_globs(self, tmp_path, monkeypatch):
        """DEFECT: a temp named ``summary_x.json<rand>`` matches the
        ``summary_*.json`` globs in run_comparison / v18_wave_summary and a
        reader could open a half-written view. Observed at the instant the
        temp exists (inside the failing replace)."""
        target = tmp_path / "summary_x.json"
        seen: list[str] = []

        def crash(_src, _dst):
            seen.extend(os.listdir(tmp_path))
            raise OSError("stop here")

        monkeypatch.setattr(os, "replace", crash)
        with pytest.raises(OSError):
            publish_bytes_atomically(str(target), b"{}")
        assert seen, "the temp file did not exist at publish time"
        assert all(name.startswith(".") and name.endswith(".tmp") for name in seen), seen
        assert glob.glob(str(tmp_path / "summary_*.json")) == []


class TestWriteOnce:
    def test_a_second_publish_is_refused_and_changes_nothing(self, tmp_path):
        """DEFECT: a "write-once" publish implemented with ``os.replace``
        silently overwrites. Fails if the second payload lands, or if the
        refusal leaks its temp file."""
        target = str(tmp_path / "manifest.json")
        publish_bytes_write_once(target, b"first")
        with pytest.raises(FileExistsError):
            publish_bytes_write_once(target, b"second")
        assert open(target, "rb").read() == b"first"
        assert os.listdir(tmp_path) == ["manifest.json"]


class TestDurableAppend:
    def test_a_torn_tail_gets_its_own_line(self, tmp_path):
        """DEFECT: appending straight after a newline-less fragment (a crash
        mid-append) glues the fragment onto the NEW record, making both
        unparseable. Fails if the repairing newline is dropped."""
        log = tmp_path / "log.jsonl"
        log.write_text('{"a": 1}\n{"b": 2')
        append_line_durably(str(log), '{"c": 3}')
        assert log.read_text().split("\n") == ['{"a": 1}', '{"b": 2', '{"c": 3}', ""]

    def test_an_embedded_newline_is_refused(self, tmp_path):
        """DEFECT: one logical record spanning two lines would be read as
        two broken lines by every JSONL reader; this refusal is the only
        thing that stops it at the writer."""
        with pytest.raises(ValueError, match="newline"):
            append_line_durably(str(tmp_path / "log.jsonl"), "a\nb")
