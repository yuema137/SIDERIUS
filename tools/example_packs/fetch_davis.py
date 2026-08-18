"""Fetch/verify the official DAVIS 2017 TrainVal-480p archive (D14-3 C1).

Same lifecycle as the Pets tool (`_fetch_common`): the archive and the
extracted frames live in an OPERATOR-SUPPLIED machine-local directory
OUTSIDE the tree; only pins are tracked; the root reaches the framework as
the data-path seam's ``data_dir``.

Licence (verified from primary sources 2026-08-18; child design §2.0, pinned
verbatim in the pack's PROVENANCE.md): the official toolkit repository
carries BSD 3-Clause; the challenge download page states no licence and
frames the data for research with a citation request; the CC BY 4.0
challenge ANNOTATIONS are not consumed by this task (RGB frames only).

Usage::

    .venv/bin/python -m tools.example_packs.fetch_davis \
        --dest /home/klz/Data/DAVIS_2017 --extract
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.example_packs._fetch_common import (
    ArchiveSpec,
    extract_archive,
    require_out_of_tree,
    verify_or_fetch,
)

#: The official link published on davischallenge.org/davis2017/code.html.
DAVIS_TRAINVAL_480P = ArchiveSpec(
    name="DAVIS-2017-trainval-480p.zip",
    url="https://data.vision.ee.ethz.ch/csergi/share/davis/DAVIS-2017-trainval-480p.zip",
    # Recorded at first fetch (D14-3 C1); see PROVENANCE.md for date/size.
    sha256="e3d0b5b77c3d031b000a19e0e25e3e2cac65d183755601bc2cf066df1a2aa492",
    extract_member_dir="DAVIS",
)

#: Where the frames land inside the extracted tree.
FRAMES_RELDIR = Path("DAVIS") / "JPEGImages" / "480p"


def check_layout(dest: Path, sequences: list[str]) -> None:
    """Every sequence the frozen manifest names must exist with frames."""
    frames_root = dest / FRAMES_RELDIR
    if not frames_root.is_dir():
        raise FileNotFoundError(
            f"expected official layout {frames_root} — the archive did not "
            "produce DAVIS/JPEGImages/480p/."
        )
    missing = [s for s in sequences if not (frames_root / s).is_dir()]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} sequence(s) named by the frozen manifest are absent "
            f"under {frames_root} (first: {missing[0]!r})."
        )
    empty = [s for s in sequences if not list((frames_root / s).glob("*.jpg"))]
    if empty:
        raise FileNotFoundError(f"sequence(s) with no frames (first: {empty[0]!r})")
    print(f"[layout] {len(sequences)} sequences present under {frames_root}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--extract", action="store_true")
    parser.add_argument(
        "--check-layout",
        action="store_true",
        help="verify every sequence in the frozen sequences.csv is present",
    )
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[2]
    dest = require_out_of_tree(args.dest, repo, parser.error)

    verify_or_fetch(dest, DAVIS_TRAINVAL_480P, allow_download=not args.no_download)
    if args.extract:
        extract_archive(dest, DAVIS_TRAINVAL_480P)
    if args.check_layout:
        from execute_tools.davis_data_path import load_davis_sequences

        manifest = repo / "examples" / "davis_future_prediction" / "data" / "manifests"
        check_layout(
            dest, [row.sequence_name for row in load_davis_sequences(manifest / "sequences.csv")]
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
