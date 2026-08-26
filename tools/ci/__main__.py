"""The canonical local CI-parity entrypoint.

Thin by design (kickoff §32): it sequences preflight → plan → execute → report
and owns no logic of its own. Selection stays with ``tools.ci_selection``,
planning with ``tools.ci.shards``, execution with ``tools.ci.execution``.

    python -m tools.ci preflight --root .
    python -m tools.ci bulk --root . --shards 8 --threads 2
    python -m tools.ci sensitive --root .
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from tools.ci.execution import _reject_workdir_inside, run_bulk, run_shard
from tools.ci.preflight import ExecutionRoot, run_preflight
from tools.ci.provenance import build_manifest
from tools.ci.selection import resolve_selection
from tools.ci.sensitive import SENSITIVE_FILES, sensitive_paths
from tools.ci.shards import plan_shards, verify_plan
from tools.ci.weights import DEFAULT_WEIGHT, load_weights


def _preflight_or_exit(
    root: Path, *, expect_clean: bool, strict_configs: bool, require_tmpdir: bool = True
) -> str:
    spec = ExecutionRoot(
        path=root,
        expect_clean=expect_clean,
        require_venv=True,
        require_tmpdir=require_tmpdir,
        expect_absent=()
        if not strict_configs
        else ExecutionRoot.model_fields["expect_absent"].default,
    )
    report = run_preflight(spec)
    print(report.render(), file=sys.stderr)
    if not report.satisfied:
        raise SystemExit(2)
    return report.sha or "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.ci")
    parser.add_argument("mode", choices=("preflight", "bulk", "sensitive", "plan"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    # 4 is the MEASURED local optimum: with weights the floor is one 460.3 s
    # file, which 4 shards reach on 8 threads / ~6.4 GB where 8 spend 16 /
    # ~12.8 GB for identical wall-clock. Higher counts are a diagnostic
    # override, not a normal path.
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument(
        "--allow-machine-configs",
        action="store_true",
        help="do not require the machine-local config files to be absent",
    )
    parser.add_argument("--dirty-ok", action="store_true")
    parser.add_argument(
        "--changed-from",
        type=Path,
        default=None,
        help=(
            "file of changed paths, as `git diff --name-only` emits. The file SET "
            "is then chosen by tools.ci_selection — the existing authority — not "
            "by this harness. Absent means the full suite."
        ),
    )
    parser.add_argument(
        "--by-count",
        action="store_true",
        help="ignore measured weights and balance by file count (diagnostic only)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    # OUTSIDE the source tree by default. A workdir inside the checkout puts
    # every shard's TMPDIR — and therefore every `tmp_path` — inside the
    # repository, where tests observe harness scratch as repository content.
    # run_bulk refuses such a workdir outright.
    workdir = (args.workdir or Path(tempfile.gettempdir()) / "siderius_ci_parity").resolve()

    if args.mode == "preflight":
        _preflight_or_exit(
            root, expect_clean=not args.dirty_ok, strict_configs=not args.allow_machine_configs
        )
        return 0

    changed = (
        [
            ln.strip()
            for ln in args.changed_from.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        if args.changed_from and args.changed_from.is_file()
        else None
    )
    chosen = resolve_selection(root, changed)
    print(f"selection: {chosen.reason}", file=sys.stderr)
    files = list(chosen.files)
    # Weighted by default: by-count balancing reported imbalance 1.004 and still
    # took 654 s, because it cannot see that one file is 460 s of the 1288.
    measured = {} if args.by_count else load_weights()
    weights = None
    if measured:
        weights = {f: measured.get(f, DEFAULT_WEIGHT) for f in files}
    plan = plan_shards(files, count=args.shards, sensitive=sensitive_paths(), weights=weights)
    problems = verify_plan(plan, files)
    if problems:
        print("SHARD PLAN INVALID:", *problems, sep="\n  ", file=sys.stderr)
        return 2

    if args.mode == "plan":
        print(
            json.dumps(
                {
                    "files": len(files),
                    "full_suite": chosen.full_suite,
                    "bulk": len(plan.bulk_files),
                    "sensitive": list(plan.sensitive),
                    "shards": [
                        {"index": s.index, "files": s.size, "weight": s.weight} for s in plan.shards
                    ],
                    "imbalance": round(plan.imbalance(), 4),
                    "weighted": weights is not None,
                },
                indent=2,
            )
        )
        return 0

    # The harness assigns each shard its own TMPDIR, so it does not require one
    # from the invoking shell.
    sha = _preflight_or_exit(
        root,
        expect_clean=not args.dirty_ok,
        strict_configs=not args.allow_machine_configs,
        require_tmpdir=False,
    )

    if args.mode == "sensitive":
        _reject_workdir_inside(root, workdir)
        # Sequential and alone: these assert that a mechanism fired within a
        # wall-clock bound, so they must not compete with anything.
        failures = 0
        for i, path in enumerate(sorted(SENSITIVE_FILES)):
            res = run_shard(
                root, 900 + i, [path], workdir=workdir / "sensitive", threads=args.threads
            )
            state = "invalid" if res.invalid_reason else ("ok" if res.passed else "FAILED")
            print(f"  {state:>7}  {path}  {res.duration_s:.1f}s", file=sys.stderr)
            if not res.passed:
                failures += 1
        return 1 if failures else 0

    manifest = build_manifest(
        root,
        mode="bulk",
        declared_shards=args.shards,
        declared_threads=args.threads,
        selection={
            "authority": "tools.ci_selection",
            "full_suite": chosen.full_suite,
            "reason": chosen.reason,
            "files": len(files),
        },
    )
    result = run_bulk(
        root,
        plan,
        sha=sha,
        workdir=workdir / "bulk",
        threads=args.threads,
        concurrency=args.concurrency or args.shards,
    )
    print(result.render(), file=sys.stderr)

    longest = result.longest()
    manifest.finished_at = result.finished_at
    manifest.shards = [
        {
            "index": s.index,
            "files": len(s.files),
            "duration_s": round(s.duration_s, 2),
            "returncode": s.returncode,
            "invalid_reason": s.invalid_reason,
            "junit_xml": s.junit_xml,
        }
        for s in result.shards
    ]
    manifest.totals = {
        "ok": result.ok,
        "wall_clock_s": round(result.wall_clock_s, 2),
        "heaviest_shard_index": longest.index if longest else None,
        "heaviest_shard_s": round(longest.duration_s, 2) if longest else None,
        "failed_shards": [s.index for s in result.failed],
        "invalid_shards": [s.index for s in result.invalid],
    }
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "bulk_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    (workdir / "run_manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
