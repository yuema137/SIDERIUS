#!/usr/bin/env python
"""One-pass linter for ``token_usage.jsonl`` audit logs.

Validates the §1.4.1 / §1.7 invariants of the design doc:

1. **Schema**: every line parses as JSON and validates against
   ``TokenUsageRow``.
2. **run_id consistency**: every row's ``run_id`` matches the file's
   first-row ``run_id``.
3. **Iter-flush leak detection**: once an ``_iter_flush`` row appears
   for ``iter=N``, no subsequent row may carry ``iter=N``.
4. **Monotonic timestamps**: ``ts`` strings are non-decreasing across
   the file (clock skew is reported as a warning, not a hard error).

Exit codes:
    0 — file is clean.
    1 — at least one anomaly detected. Errors are printed to stderr
        prefixed with ``[LEAK]`` / ``[RUN_ID_MISMATCH]`` /
        ``[BAD_JSON]`` / ``[BAD_SCHEMA]``; warnings with ``[WARN]``.

Usage::

    .venv/bin/python tools/validate_token_usage_jsonl.py <path>

Used by Commit 5's Top-3 Bloat Report (§1.9) as a pre-flight gate
before computing aggregate metrics on a JSONL file. A nonzero exit
code from this linter blocks the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Repo-relative import — script is run from project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pydantic import ValidationError

from agent.schemas.telemetry import TokenUsageRow


def lint(path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the given JSONL file.

    Errors signify audit-log corruption (mismatched run_id, post-flush
    leak, schema violation, malformed JSON). Warnings flag soft issues
    (non-monotonic ts) that don't invalidate the file but should be
    surfaced.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        return [f"[FILE_MISSING] {path} does not exist"], []
    if path.stat().st_size == 0:
        return [], [f"[WARN] {path} is empty"]

    first_run_id: str | None = None
    flushed_iters: set[int] = set()
    last_ts: str | None = None

    with open(path) as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as je:
                errors.append(f"[BAD_JSON] {path}:{lineno}: {je}")
                continue
            try:
                row = TokenUsageRow.model_validate(obj)
            except ValidationError as ve:
                # Compact the validation error to one line per row.
                errors.append(
                    f"[BAD_SCHEMA] {path}:{lineno}: "
                    f"{ve.error_count()} schema error(s) — "
                    f"{ve.errors()[0]['msg']}"
                )
                continue

            # --- run_id consistency ---
            if first_run_id is None:
                first_run_id = row.run_id
            elif row.run_id != first_run_id:
                errors.append(
                    f"[RUN_ID_MISMATCH] {path}:{lineno}: row run_id="
                    f"{row.run_id!r} but file owner={first_run_id!r}"
                )

            # --- iter-flush leak detection ---
            if row.label == "_iter_flush":
                if row.iter is not None:
                    if row.iter in flushed_iters:
                        errors.append(
                            f"[DUPLICATE_FLUSH] {path}:{lineno}: "
                            f"iter={row.iter} flushed more than once"
                        )
                    flushed_iters.add(row.iter)
            else:
                if row.iter is not None and row.iter in flushed_iters:
                    errors.append(
                        f"[LEAK] {path}:{lineno}: row with iter="
                        f"{row.iter} appeared *after* the iter_flush "
                        f"marker for iter={row.iter} (label={row.label!r})"
                    )

            # --- ts monotonic (soft) ---
            if last_ts is not None and row.ts < last_ts:
                warnings.append(
                    f"[WARN] {path}:{lineno}: non-monotonic ts ({row.ts} < previous {last_ts})"
                )
            last_ts = row.ts

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint a SIDERIUS token_usage.jsonl audit log.")
    parser.add_argument(
        "path",
        type=Path,
        help="Path to the token_usage.jsonl file to validate.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress 'OK' line on clean files; only print errors/warnings.",
    )
    args = parser.parse_args(argv)

    errors, warnings = lint(args.path)
    for w in warnings:
        print(w, file=sys.stderr)
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        print(
            f"[FAIL] {args.path}: {len(errors)} error(s), {len(warnings)} warning(s)",
            file=sys.stderr,
        )
        return 1
    if not args.quiet:
        print(f"[OK] {args.path}: clean ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
