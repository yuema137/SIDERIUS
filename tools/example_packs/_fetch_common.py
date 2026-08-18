"""Shared fetch/verify/extract machinery for example-pack acquisition tools.

Extracted from `fetch_oxford_iiit_pet.py` at D14-3 C1 (two consumers — the
gradual-genericization rule): pins-as-constants, verify-before-anything, an
existing archive is NEVER silently re-downloaded, extraction is
layout-checked, and every tool refuses an in-tree destination (the packs'
committed data lifecycle).
"""

from __future__ import annotations

import hashlib
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArchiveSpec:
    """One official artifact: where it comes from and what its bytes ARE."""

    name: str
    url: str
    sha256: str
    extract_member_dir: str  # top-level dir the archive must yield


class ArchiveIntegrityError(RuntimeError):
    """An on-disk archive's digest differs from the pin (fail closed)."""


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_or_fetch(dest: Path, spec: ArchiveSpec, *, allow_download: bool = True) -> Path:
    """Return the verified archive path under ``dest``.

    Existing file → verify against the pin (mismatch raises, naming both
    digests — never silently re-download over evidence). Missing file →
    download from the official URL when allowed, then verify the SAME way.
    """
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / spec.name
    if not target.exists():
        if not allow_download:
            raise FileNotFoundError(
                f"{target} is absent and --no-download was given; fetch it from "
                f"{spec.url} (official source) or drop the flag."
            )
        print(f"[fetch] {spec.url} -> {target}")
        with urllib.request.urlopen(spec.url) as response, target.open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
    actual = sha256_of_file(target)
    if actual != spec.sha256:
        raise ArchiveIntegrityError(
            f"{target.name}: sha256 {actual} does not match the pinned "
            f"{spec.sha256}. Refusing to proceed — delete the file and re-fetch "
            f"from the official source ({spec.url}) if it is corrupt."
        )
    print(f"[verified] {target.name} sha256={actual}")
    return target


def extract_archive(dest: Path, spec: ArchiveSpec) -> Path:
    """Extract ``dest/<name>`` into ``dest`` (idempotent by member dir).

    tar.gz and zip supported — the two formats the official distributions
    use (Pets: tar.gz; DAVIS: zip).
    """
    member_dir = dest / spec.extract_member_dir
    if member_dir.is_dir():
        print(f"[skip-extract] {member_dir} already exists")
        return member_dir
    archive = dest / spec.name
    print(f"[extract] {archive.name} -> {member_dir}")
    if spec.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(dest, filter="data")
    if not member_dir.is_dir():
        raise ArchiveIntegrityError(
            f"extraction of {archive.name} did not produce {member_dir} — the "
            "archive layout differs from the official distribution."
        )
    return member_dir


def require_out_of_tree(dest: Path, repo_root: Path, error) -> Path:
    """Refuse a destination inside the repository (packs never hold data)."""
    resolved = dest.resolve()
    if resolved.is_relative_to(repo_root):
        error(
            f"--dest {resolved} is inside the repository; the pack lifecycle "
            "requires a machine-local directory outside the tree."
        )
    return resolved
