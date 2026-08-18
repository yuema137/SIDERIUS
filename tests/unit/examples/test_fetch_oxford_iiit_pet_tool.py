"""The Pets fetch tool's verify/fail-closed semantics (D14-2 C1).

Offline by construction: every case runs against tmp fixtures — the network
path is never exercised here (the tool's real fetch is operator-run; its
evidence lives in PROVENANCE.md). What only these tests catch: a silent
re-download over a corrupt archive, a tolerated digest mismatch, extraction
"succeeding" without the official layout, or the tool agreeing to write
inside the repository tree.
"""

from __future__ import annotations

import hashlib
import io
import tarfile

import pytest

from tools.example_packs.fetch_oxford_iiit_pet import (
    ARCHIVES,
    ArchiveIntegrityError,
    ArchiveSpec,
    extract_archive,
    main,
    verify_or_fetch,
)


def _tar_gz_bytes(member_dir: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, payload in files.items():
            info = tarfile.TarInfo(f"{member_dir}/{name}")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _spec_for(payload: bytes, name: str = "images.tar.gz") -> ArchiveSpec:
    return ArchiveSpec(
        name=name,
        url=f"https://example.invalid/{name}",  # never fetched: these cases are offline
        sha256=hashlib.sha256(payload).hexdigest(),
        extract_member_dir="images",
    )


class TestVerifyOrFetch:
    def test_existing_archive_with_matching_pin_is_verified_not_refetched(self, tmp_path):
        payload = _tar_gz_bytes("images", {"a.jpg": b"x"})
        (tmp_path / "images.tar.gz").write_bytes(payload)
        out = verify_or_fetch(tmp_path, _spec_for(payload), allow_download=False)
        assert out == tmp_path / "images.tar.gz"

    def test_digest_mismatch_fails_closed_naming_both_digests(self, tmp_path):
        payload = _tar_gz_bytes("images", {"a.jpg": b"x"})
        (tmp_path / "images.tar.gz").write_bytes(payload + b"corruption")
        spec = _spec_for(payload)
        with pytest.raises(ArchiveIntegrityError) as err:
            verify_or_fetch(tmp_path, spec, allow_download=False)
        assert spec.sha256 in str(err.value)
        assert hashlib.sha256(payload + b"corruption").hexdigest() in str(err.value)

    def test_absent_archive_offline_is_an_error_never_a_fetch(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="official source"):
            verify_or_fetch(tmp_path, _spec_for(b"whatever"), allow_download=False)


class TestExtraction:
    def test_extracts_official_layout_and_is_idempotent(self, tmp_path):
        payload = _tar_gz_bytes("images", {"Abyssinian_1.jpg": b"jpegbytes"})
        spec = _spec_for(payload)
        (tmp_path / spec.name).write_bytes(payload)
        out = extract_archive(tmp_path, spec)
        assert (out / "Abyssinian_1.jpg").read_bytes() == b"jpegbytes"
        # Second call: skip, not re-extract (the marker is the member dir).
        assert extract_archive(tmp_path, spec) == out

    def test_wrong_layout_fails_closed(self, tmp_path):
        payload = _tar_gz_bytes("not_images", {"a.jpg": b"x"})
        spec = _spec_for(payload)  # expects member dir "images"
        (tmp_path / spec.name).write_bytes(payload)
        with pytest.raises(ArchiveIntegrityError, match="layout"):
            extract_archive(tmp_path, spec)


class TestOperatorSurface:
    def test_dest_inside_the_repository_is_refused(self):
        from pathlib import Path

        import tools.example_packs.fetch_oxford_iiit_pet as fetch_mod

        in_tree = Path(fetch_mod.__file__).resolve().parents[2] / "examples" / "oxford_iiit_pet"
        with pytest.raises(SystemExit):
            main(["--dest", str(in_tree), "--no-download"])

    def test_the_committed_pins_are_wellformed(self):
        """Both archive pins present, hex-64, distinct — the executable
        authority PROVENANCE.md mirrors."""
        assert {spec.name for spec in ARCHIVES} == {"images.tar.gz", "annotations.tar.gz"}
        for spec in ARCHIVES:
            assert len(spec.sha256) == 64 and int(spec.sha256, 16) >= 0
        assert len({spec.sha256 for spec in ARCHIVES}) == 2
