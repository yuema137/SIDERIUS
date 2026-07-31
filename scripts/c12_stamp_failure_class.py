#!/usr/bin/env python
"""Stamp `failure_class` onto C12 cells recorded before the field existed.

The coverage rule added in `evaluate_campaign` asks a typed question —
did this cell hit the device/quota ceiling? — of records written before
anything could answer it. This backfills the answer from each record's
own PRESERVED evidence, prints exactly what it inferred and from what,
and never invents a measurement: only `failure_class` (and, for the one
cell below, `status`) is touched.

Every rule here reads evidence the record already contains, except for
`transformer@8M-ceiling`, whose attribution comes from an EXTERNAL
source that the probe could not see at the time — this host runs a
root-level per-user VRAM quota watchdog, and its log names the exact PID:

    2026-07-30 22:04:50 WARNING User [yuema137] exceeded quota:
                                31266MB / 30000MB
    2026-07-30 22:04:50 INFO    Terminating PID 1127384
                                (Usage: 31266MB on GPU 0)

That is 31.27 GiB on a 31.34 GiB card: the candidate was reaped sitting
at the ceiling. The probe parent now samples worker VRAM and would
classify this live, but that fix landed after the run, and the operator
directed that the cell not be re-run. The stand-in is recorded with its
source so the provenance is never mistaken for a live measurement.

    .venv/bin/python scripts/c12_stamp_failure_class.py            # dry run
    .venv/bin/python scripts/c12_stamp_failure_class.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ROOT = Path("/home/klz/Data/SIDEREIS_DATA/runtime_validation/c12")

WATCHDOG_LOG = "/var/log/vram_watchdog.log"
WATCHDOG_EVIDENCE = (
    f"External capacity evidence ({WATCHDOG_LOG}): the host's per-user VRAM "
    "quota watchdog recorded 'User [yuema137] exceeded quota: 31266MB / "
    "30000MB' and 'Terminating PID 1127384 (Usage: 31266MB on GPU 0)' at "
    "the exact second this worker received SIGTERM — 31.27 GiB held on a "
    "31.34 GiB device. The candidate was reaped while sitting at the "
    "capacity bound; the probe could not observe this at run time because "
    "parent-side VRAM sampling landed afterwards."
)


def classify(record: dict) -> tuple[str | None, str | None, str | None]:
    """-> (failure_class, source, new_status). All None = leave alone."""
    detail = record.get("failure_detail") or ""
    status = record.get("status")

    if record["cell_id"] == "transformer@8M-ceiling":
        return "capacity", WATCHDOG_EVIDENCE, "measured_failure"
    if status != "measured_failure":
        return None, None, None
    if "out of memory" in detail.lower() or "status=oom" in detail:
        return (
            "capacity",
            "derived from the preserved probe status (CUDA OOM) in this record",
            None,
        )
    if "wall cap" in detail.lower():
        return "wall_cap", "derived from the preserved wall-cap detail in this record", None
    return "other", "no capacity or wall-cap evidence in the preserved detail", None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--write", action="store_true", help="Apply (default: dry run).")
    args = parser.parse_args(argv)

    changed = 0
    for path in sorted((args.output_root / "A_matrix").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "ok" or record.get("failure_class"):
            continue
        failure_class, source, new_status = classify(record)
        if failure_class is None:
            continue
        print(f"{record['cell_id']:24} {record['status']:22} -> failure_class={failure_class}")
        if new_status and new_status != record["status"]:
            print(f"{'':24} status {record['status']} -> {new_status}")
        print(f"{'':24} source: {source}\n")
        record["failure_class"] = failure_class
        record["failure_class_source"] = source
        if new_status:
            record["status"] = new_status
            record["failure_detail"] = f"{record.get('failure_detail', '')}\n\n{source}"
        changed += 1
        if args.write:
            path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    print(f"{changed} cell(s) {'updated' if args.write else 'would be updated (dry run)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
