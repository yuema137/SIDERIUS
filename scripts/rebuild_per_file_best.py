#!/usr/bin/env python
"""V19 PR 1 (P1-C5) — rebuild the per-file best table from committed artifacts.

Deterministic backfill / recovery tool. Uses the SAME
:func:`execute_tools.per_file_best.build_table` computation as the
chain runner's incremental writer (design doc §3.7 A5 — byte-equality
is guaranteed by the shared build path + canonical serialization).

Typical usages:

    # Regenerate the table in a chain workspace (after a WARN'd
    # incremental failure, or as first-time backfill on a legacy V17
    # workspace).
    python scripts/rebuild_per_file_best.py --workspace /path/to/ws

    # Compute + print the table (JSON on stdout) without touching disk.
    python scripts/rebuild_per_file_best.py --workspace /path/to/ws \
        --print-only

Exits non-zero on ``ReplayIntegrityError`` (a committed artifact's
hash no longer matches its manifest) — same fail-closed behavior as
the incumbent walker.
"""

from __future__ import annotations

import argparse
import os
import sys

from execute_tools.per_file_best import (
    TABLE_BASENAME,
    build_table,
    canonical_bytes,
    write_table,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        required=True,
        help="Chain workspace root (the directory holding iter_NNN/).",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Compute and print the canonical JSON on stdout; do not "
        "write to disk. Useful for backfill smoke and diffing against "
        "an existing table.",
    )
    args = parser.parse_args(argv)

    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(workspace):
        print(f"error: workspace does not exist: {workspace}", file=sys.stderr)
        return 2

    if args.print_only:
        table = build_table(workspace)
        sys.stdout.buffer.write(canonical_bytes(table))
        return 0

    path = write_table(workspace)
    print(f"[per_file_best] wrote {path}")
    print(f"[per_file_best] basename: {TABLE_BASENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
