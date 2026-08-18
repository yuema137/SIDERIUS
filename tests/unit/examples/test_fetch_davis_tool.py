"""DAVIS acquisition tool: pins, zip handling, layout check (D14-3 C1).

Offline by construction (tmp zips). What only this catches: the zip branch
of the shared extractor mishandling the official archive shape, the layout
check passing on a tree whose sequences are absent or empty, and the DAVIS
pin drifting from the value recorded in PROVENANCE.md.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from tools.example_packs._fetch_common import (
    ArchiveIntegrityError,
    ArchiveSpec,
    extract_archive,
    verify_or_fetch,
)
from tools.example_packs.fetch_davis import DAVIS_TRAINVAL_480P, check_layout, main

REPO_ROOT = Path(__file__).resolve().parents[3]
PROVENANCE = REPO_ROOT / "examples" / "davis_future_prediction" / "PROVENANCE.md"


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def _spec_for(payload: bytes) -> ArchiveSpec:
    return ArchiveSpec(
        name="DAVIS-2017-trainval-480p.zip",
        url="https://example.invalid/davis.zip",
        sha256=hashlib.sha256(payload).hexdigest(),
        extract_member_dir="DAVIS",
    )


class TestZipAcquisition:
    def test_verify_then_extract_official_shape(self, tmp_path):
        payload = _zip_bytes({"DAVIS/JPEGImages/480p/bear/00000.jpg": b"jpeg"})
        spec = _spec_for(payload)
        (tmp_path / spec.name).write_bytes(payload)
        verify_or_fetch(tmp_path, spec, allow_download=False)
        out = extract_archive(tmp_path, spec)
        assert (out / "JPEGImages" / "480p" / "bear" / "00000.jpg").read_bytes() == b"jpeg"
        assert extract_archive(tmp_path, spec) == out  # idempotent

    def test_corrupt_zip_fails_closed(self, tmp_path):
        payload = _zip_bytes({"DAVIS/x": b"y"})
        spec = _spec_for(payload)
        (tmp_path / spec.name).write_bytes(payload + b"tamper")
        with pytest.raises(ArchiveIntegrityError):
            verify_or_fetch(tmp_path, spec, allow_download=False)


class TestLayoutCheck:
    def test_passes_on_a_complete_tree(self, tmp_path):
        seq = tmp_path / "DAVIS" / "JPEGImages" / "480p" / "bear"
        seq.mkdir(parents=True)
        (seq / "00000.jpg").write_bytes(b"x")
        check_layout(tmp_path, ["bear"])  # no raise

    def test_missing_sequence_is_named(self, tmp_path):
        seq = tmp_path / "DAVIS" / "JPEGImages" / "480p" / "bear"
        seq.mkdir(parents=True)
        (seq / "00000.jpg").write_bytes(b"x")
        with pytest.raises(FileNotFoundError, match="dog"):
            check_layout(tmp_path, ["bear", "dog"])

    def test_empty_sequence_dir_is_refused(self, tmp_path):
        (tmp_path / "DAVIS" / "JPEGImages" / "480p" / "bear").mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="no frames"):
            check_layout(tmp_path, ["bear"])

    def test_absent_layout_root_is_refused(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="official layout"):
            check_layout(tmp_path, ["bear"])


class TestOperatorSurface:
    def test_in_tree_dest_is_refused(self):
        with pytest.raises(SystemExit):
            main(["--dest", str(REPO_ROOT / "examples"), "--no-download"])

    def test_pin_matches_the_provenance_record(self):
        """The tool's constant is the executable authority; PROVENANCE.md
        mirrors it. A drift between them is the defect this catches."""
        assert len(DAVIS_TRAINVAL_480P.sha256) == 64
        assert DAVIS_TRAINVAL_480P.sha256 in PROVENANCE.read_text(encoding="utf-8")
        assert DAVIS_TRAINVAL_480P.url.startswith("https://data.vision.ee.ethz.ch/")
