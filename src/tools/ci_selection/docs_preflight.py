"""Dependency-free, conservative classification before CI installs the application.

Run as a file with the runner's Python. This bootstrap intentionally imports no
application packages. The normal affected-test selector remains authoritative
for every change outside these audited, ordinary documentation files.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

# These are operator guides, not runtime prompt/skill inputs. Keep this list
# explicit: docs/agent-reference contains payloads consumed by orchestration.
ORDINARY_DOCUMENTS = frozenset(
    {
        "README.md",
        "docs/getting-started/README.md",
        "docs/getting-started/first-run.md",
        "docs/getting-started/installation.md",
    }
)


def ordinary_docs_only(raw: bytes, root: Path) -> bool:
    """Accept only complete Git M/path records for audited regular documents.

    Deliberately reject additions, removals, copies, renames and type changes.
    This is a narrow proof, not a second general name-status parser; all other
    inputs go unchanged to the existing selector and execution harness.
    """
    if not raw or not raw.endswith(b"\0"):
        return False
    fields = raw[:-1].split(b"\0")
    if len(fields) % 2:
        return False
    for status, encoded in zip(fields[::2], fields[1::2], strict=True):
        name = os.fsdecode(encoded)
        if status != b"M" or name not in ORDINARY_DOCUMENTS:
            return False
        path = root / name
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changes", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        docs_only = ordinary_docs_only(args.changes.read_bytes(), args.root.resolve())
    except (OSError, ValueError) as exc:
        print(f"Documentation preflight unavailable: {exc}; retaining normal CI")
        docs_only = False
    print("Ordinary documentation checks only" if docs_only else "Retaining normal CI")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"docs_only={'true' if docs_only else 'false'}\n")


if __name__ == "__main__":
    main()
