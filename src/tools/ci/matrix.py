"""Split one shard plan across parallel CI jobs, and prove the split was whole.

The bulk lane's shard plan (``tools.ci.shards``) is computed for a TOTAL shard
count. On CI that plan no longer fits one runner: a 2-CPU runner executing four
shards was 2x oversubscribed and the full suite reached the job timeout
(issue #990). Each matrix job therefore recomputes the same deterministic plan
and executes only its own subset of shard indices, so every job runs one shard
per CPU.

Splitting the work across jobs adds two silent-loss risks that a single job
did not have:

* a matrix entry is missing (the job list and ``job_count`` drift apart), so
  some shard indices are never executed by anyone;
* two jobs compute DIFFERENT plans (different changed-file input, a stale
  weight split dropped on one runner only), so the union of what they ran is
  not the selection — some files twice, others never.

Each job writes a :func:`job_report`; the aggregate job runs :func:`verify_reports`
over all of them. Both checks are pure functions of those reports.

Standard library only, by design: the aggregate job runs this file directly
(``python -I src/tools/ci/matrix.py verify ...``) without installing the
project, exactly as ``tools/ci_selection/docs_preflight.py`` does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

#: Version of the report shape below; bumped on any incompatible change.
REPORT_SCHEMA_VERSION = 1
#: File name each bulk job writes into its workdir.
REPORT_NAME = "matrix_report.json"


def job_shard_indices(shard_count: int, job_count: int, job_index: int) -> tuple[int, ...]:
    """Shard indices executed by matrix job ``job_index`` of ``job_count``.

    Strided assignment (``index % job_count == job_index``). The planner's
    longest-processing-time-first packing already balances the shards, so the
    jobs need no further weighting; a job's wall time is its slowest shard.

    Raises:
        ValueError: on a non-positive count, an out-of-range index, or more
            jobs than shards (a job with no shard would report green while
            executing nothing).
    """
    if shard_count < 1 or job_count < 1:
        raise ValueError(f"shard_count and job_count must be >= 1, got {shard_count}, {job_count}")
    if job_count > shard_count:
        raise ValueError(f"job_count {job_count} exceeds shard_count {shard_count}")
    if not 0 <= job_index < job_count:
        raise ValueError(f"job_index {job_index} outside [0, {job_count})")
    return tuple(range(job_index, shard_count, job_count))


def plan_digest(shards: Iterable[tuple[int, Sequence[str]]], sensitive: Iterable[str]) -> str:
    """Canonical SHA-256 of a complete shard plan.

    Every job hashes the WHOLE plan it computed, not only its own subset, so
    two jobs that disagree about any shard's contents produce different
    digests even when their own subsets look plausible.
    """
    canonical = {
        "shards": sorted([int(index), list(files)] for index, files in shards),
        "sensitive": sorted(sensitive),
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def job_report(
    *,
    job_index: int,
    job_count: int,
    shard_count: int,
    digest: str,
    shards_run: Sequence[int],
    ok: bool,
    full_suite: bool,
    files: int,
) -> dict[str, object]:
    """The record one bulk job leaves for the aggregate check."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "job_index": job_index,
        "job_count": job_count,
        "shard_count": shard_count,
        "plan_digest": digest,
        "shards_run": sorted(shards_run),
        "ok": ok,
        "full_suite": full_suite,
        "files": files,
    }


def _int(report: Mapping[str, object], name: str) -> int:
    value = report.get(name)
    # bool is an int subclass; an index or count must not accept True/False.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"field {name!r} is {value!r}, expected an int")
    return value


def _int_list(report: Mapping[str, object], name: str) -> list[int]:
    value = report.get(name)
    if not isinstance(value, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) for i in value
    ):
        raise ValueError(f"field {name!r} is {value!r}, expected a list of ints")
    return list(value)


def _str(report: Mapping[str, object], name: str) -> str:
    value = report.get(name)
    if not isinstance(value, str):
        raise ValueError(f"field {name!r} is {value!r}, expected a string")
    return value


def _bool(report: Mapping[str, object], name: str) -> bool:
    value = report.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"field {name!r} is {value!r}, expected a bool")
    return value


def verify_reports(reports: Sequence[Mapping[str, object]]) -> list[str]:
    """Reasons the set of job reports is NOT one whole, green execution.

    An empty list means: every job of one matrix reported, all computed the
    same plan, each ran exactly its assigned shard indices, together they ran
    every shard index exactly once, and every job was green.
    """
    if not reports:
        return ["no matrix job reports were found — the bulk lane produced no evidence"]
    problems: list[str] = []
    parsed: list[tuple[int, int, int, str, list[int], bool]] = []
    for position, report in enumerate(reports):
        try:
            if report.get("schema_version") != REPORT_SCHEMA_VERSION:
                raise ValueError(f"schema_version {report.get('schema_version')!r}")
            parsed.append(
                (
                    _int(report, "job_index"),
                    _int(report, "job_count"),
                    _int(report, "shard_count"),
                    _str(report, "plan_digest"),
                    _int_list(report, "shards_run"),
                    _bool(report, "ok"),
                )
            )
        except ValueError as exc:
            problems.append(f"report #{position} is malformed: {exc}")
    if problems:
        return problems

    for label, values in (
        ("job_count", {p[1] for p in parsed}),
        ("shard_count", {p[2] for p in parsed}),
        ("plan_digest", {p[3] for p in parsed}),
    ):
        if len(values) != 1:
            problems.append(f"jobs disagree on {label}: {sorted(values)}")
    if problems:
        return problems

    job_count, shard_count = parsed[0][1], parsed[0][2]
    job_indices = sorted(p[0] for p in parsed)
    if job_indices != list(range(job_count)):
        problems.append(
            f"expected one report per job 0..{job_count - 1}, got job indices {job_indices}"
        )

    executed: list[int] = []
    for job_index, _, _, _, shards_run, ok in sorted(parsed):
        try:
            expected = list(job_shard_indices(shard_count, job_count, job_index))
        except ValueError as exc:
            problems.append(f"job {job_index}: {exc}")
            continue
        if sorted(shards_run) != expected:
            problems.append(f"job {job_index} ran shards {sorted(shards_run)}, assigned {expected}")
        if not ok:
            problems.append(f"job {job_index} reported a RED or invalid shard")
        executed.extend(shards_run)

    duplicated = sorted({i for i in executed if executed.count(i) > 1})
    if duplicated:
        problems.append(f"shard indices executed by more than one job: {duplicated}")
    missing = sorted(set(range(shard_count)) - set(executed))
    if missing:
        problems.append(f"shard indices executed by no job: {missing}")
    return problems


def _load(paths: Sequence[Path]) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"{path} does not hold a JSON object")
        reports.append(value)
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python src/tools/ci/matrix.py")
    sub = parser.add_subparsers(dest="mode", required=True)
    verify = sub.add_parser("verify", help="check that the job reports form one whole run")
    verify.add_argument(
        "--reports-dir",
        type=Path,
        required=True,
        help=f"directory searched recursively for {REPORT_NAME}",
    )
    args = parser.parse_args(argv)

    paths = sorted(args.reports_dir.rglob(REPORT_NAME))
    try:
        problems = verify_reports(_load(paths))
    except (OSError, ValueError) as exc:
        problems = [f"could not read job reports: {type(exc).__name__}: {exc}"]
    if problems:
        print("BULK MATRIX INCOMPLETE OR RED:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    print(f"bulk matrix whole and green: {len(paths)} job report(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
