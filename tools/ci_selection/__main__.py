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

import os
import sys

FULL_SUITE_ARGS = 'tests/unit/ -m "not real_run" -q'


def _emit(full_suite: bool, pytest_args: str, why: str) -> None:
    print(why, file=sys.stderr)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"full_suite={'true' if full_suite else 'false'}\n")
            fh.write(f"pytest_args={pytest_args}\n")


def main() -> int:
    changed = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
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
