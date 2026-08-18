"""Fetch/verify the official Oxford-IIIT Pet archives (D14-2 C1).

The pack's committed lifecycle (`examples/oxford_iiit_pet/data/README.md`,
roadmap §22.23.10) is the authority: the archives and the extracted images
live in an OPERATOR-SUPPLIED machine-local directory OUTSIDE the tree; the
tracked tree carries only the pins. The machine-local root then reaches the
framework as the seam's existing ``data_dir`` (child design §2.1) — this
tool never writes inside the repository.

Pins are module constants — the executable authority; ``PROVENANCE.md``
documents the same values for a human reader. The images pin was recorded at
first fetch (2026-08-18T20:04:03Z, size 791 918 971 bytes) and is
independently corroborated: the archive's MD5 equals torchvision's official
``OxfordIIITPet`` resource pin (``5c4f3ee8e5d25df40f4fd59a7f44e54c``).

Usage::

    .venv/bin/python -m tools.example_packs.fetch_oxford_iiit_pet \
        --dest /home/klz/Data/OXFORD_IIIT_PET --extract

Idempotent: an existing archive is VERIFIED (never re-downloaded); a
mismatch FAILS CLOSED naming both digests; ``--no-download`` makes absence
an error instead of a fetch (offline verify mode).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.example_packs._fetch_common import (
    ArchiveIntegrityError,  # noqa: F401  (re-exported: tests import it from here)
    ArchiveSpec,
    extract_archive,
    require_out_of_tree,
    sha256_of_file,  # noqa: F401  (re-exported)
    verify_or_fetch,
)

_BASE_URL = "https://www.robots.ox.ac.uk/~vgg/data/pets/data"

ARCHIVES: tuple[ArchiveSpec, ...] = (
    ArchiveSpec(
        name="images.tar.gz",
        url=f"{_BASE_URL}/images.tar.gz",
        # First fetch 2026-08-18T20:04:03Z; md5 cross-matches torchvision's
        # official pin (5c4f3ee8e5d25df40f4fd59a7f44e54c).
        sha256="67195c5e1c01f1ab5f9b6a5d22b8c27a580d896ece458917e61d459337fa318d",
        extract_member_dir="images",
    ),
    ArchiveSpec(
        name="annotations.tar.gz",
        url=f"{_BASE_URL}/annotations.tar.gz",
        # Pinned at PR0 (PROVENANCE.md, fetched 2026-08-15T21:57:55Z).
        sha256="52425fb6de5c424942b7626b428656fcbd798db970a937df61750c0f1d358e91",
        extract_member_dir="annotations",
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dest",
        required=True,
        type=Path,
        help="Machine-local directory OUTSIDE the repository tree (the pack's "
        "committed data lifecycle forbids in-tree data).",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Offline verify mode: absent archives are an error, never a fetch.",
    )
    parser.add_argument(
        "--extract", action="store_true", help="Extract verified archives under --dest."
    )
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[2]
    dest = require_out_of_tree(args.dest, repo, parser.error)

    for spec in ARCHIVES:
        verify_or_fetch(dest, spec, allow_download=not args.no_download)
        if args.extract:
            extract_archive(dest, spec)
    return 0


if __name__ == "__main__":
    sys.exit(main())
