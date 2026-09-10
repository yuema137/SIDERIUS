"""CI entry point: turn a changed-file list into a pytest invocation.

Reads changed paths on stdin (one per line, as `git diff --name-only` emits)
and writes two lines to `$GITHUB_OUTPUT` when it is set, plus a human-readable
justification to stderr:

    full_suite=true|false
    pytest_args=<args for the pytest step>

**Fail closed at every level.** Any exception, any unmapped path, any empty
selection for a non-empty diff resolves to the full suite. The wrapper below
catches `BaseException` for the same reason: a selector that crashes must make
CI run MORE, never less. A selector able to answer "run nothing" is the one
failure mode worse than having no selector at all, because it produces a
confident green.

Usage in CI:
    git diff --name-only "$BASE" "$HEAD" | uv run python -m tools.ci_selection
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

FULL_SUITE_ARGS = 'tests/unit/ -m "not real_run" -q'


def parse_name_status_z(data: bytes) -> list[str]:
    """Return both before/after paths from ``git diff --name-status -z``."""
    fields = data.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    changed: list[str] = []
    index = 0
    while index < len(fields):
        status = os.fsdecode(fields[index])
        index += 1
        if not status or status[0] not in "ACDMRTUXB":
            raise ValueError(f"invalid git name-status field: {status!r}")
        path_count = 2 if status[0] in "RC" else 1
        if index + path_count > len(fields):
            raise ValueError(f"truncated git name-status record: {status!r}")
        paths = [os.fsdecode(item) for item in fields[index : index + path_count]]
        if any(not path for path in paths):
            raise ValueError(f"empty path in git name-status record: {status!r}")
        changed.extend(paths)
        index += path_count
    return list(dict.fromkeys(changed))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m tools.ci_selection")
    parser.add_argument(
        "--name-status-z",
        action="store_true",
        help="read NUL-delimited `git diff --name-status -z` records from stdin",
    )
    parser.add_argument(
        "--write-paths-json",
        type=Path,
        default=None,
        help="write the normalized changed paths for the execution harness",
    )
    return parser.parse_args()


def _emit(full_suite: bool, pytest_args: str, why: str) -> None:
    print(why, file=sys.stderr)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"full_suite={'true' if full_suite else 'false'}\n")
            fh.write(f"pytest_args={pytest_args}\n")


def main() -> int:
    args = _arguments()
    try:
        if args.name_status_z:
            changed = parse_name_status_z(sys.stdin.buffer.read())
        else:
            changed = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
        if args.write_paths_json and changed:
            args.write_paths_json.write_text(json.dumps(changed), encoding="utf-8")
    except BaseException as exc:
        _emit(
            True,
            FULL_SUITE_ARGS,
            f"changed-path input raised {type(exc).__name__}: {exc} — failing closed",
        )
        return 0
    if not changed:
        # An empty diff is the ONLY case that legitimately runs nothing, and
        # even here the full suite is the safer answer on a PR.
        _emit(True, FULL_SUITE_ARGS, "empty diff — running the full suite anyway")
        return 0

    try:
        from tools.ci_selection.resolver import select

        result = select(changed)
    except BaseException as exc:  # deliberate: a crash must make CI run MORE
        _emit(
            True, FULL_SUITE_ARGS, f"selector raised {type(exc).__name__}: {exc} — failing closed"
        )
        return 0

    if result.full_suite or not result.modules:
        _emit(True, FULL_SUITE_ARGS, "FULL SUITE\n" + result.describe())
        return 0

    args = " ".join(sorted(result.modules)) + ' -m "not real_run" -q'
    _emit(False, args, result.describe())
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CI, not by pytest
    raise SystemExit(main())
