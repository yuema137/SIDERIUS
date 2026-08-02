"""Bounded, attributable GPU memory holder for B-G2b. VALIDATION ONLY.

Occupies a controlled amount of a named GPU so that admission's
`other_mib` is a known quantity rather than incidental load. Without
that, a refusal is *observed* but not *attributable* — and the whole
point of B-G2b is attributing it.

**Not production.** Nothing in `run_chain.sh` or a real campaign may
invoke this, and production code must never kill it: only the
validation script that started it may.

Two things it refuses to guess:

1. **Occupancy is measured, never assumed.** A requested 4 GiB tensor
   does not occupy 4 GiB — CUDA context and the caching allocator add
   several hundred MiB. The holder allocates in small steps and reads
   the driver's own figure after each one.
2. **The device is named by UUID, never by index.** "GPU 0" is a
   position that `CUDA_VISIBLE_DEVICES` can move; a UUID is an identity.

It self-terminates on a deadline, on a signal, and on any exception, so
a crashed validation run cannot leave memory pinned.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: Recomputed from B-G0's real measurement, 2026-08-02.
#:
#: B-G2b must refuse **before the training child starts**, so the figure
#: that matters is the TRAINING requirement — 1,476 MiB measured on this
#: UUID, not A5's 3,076 and not the 2,716 measured for inference:
#:
#:     ceiling 6,144 - training 1,476 = 4,668
#:
#: Below that the pair no longer exceeds the ceiling and the scenario
#: cannot conclude, so the holder refuses to signal ready there rather
#: than leaving the caller to discover it.
DEFAULT_MIN_VALID_MIB = 4_668
#: A bounded holder is the point; a large one is a different experiment.
DEFAULT_MAX_MIB = 8_000
DEFAULT_TARGET_MIB = 5_200
DEFAULT_MAX_LIFETIME_S = 600
#: Allocation granularity. Small enough that the maximum cannot be
#: overshot badly between measurements.
STEP_MIB = 256


def measured_mib(device_uuid: str, pid: int) -> int | None:
    """This process's driver-visible occupancy on that device.

    Returns `None` when the driver cannot be queried or the process is
    not listed — which is not the same as zero, and callers must not
    treat it as such.
    """
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory,gpu_uuid",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            row_pid = int(parts[0])
            used = int(parts[1])
        except ValueError:
            continue
        if row_pid == pid and parts[2] == device_uuid:
            return used
    return None


def resolve_visible_index(device_uuid: str) -> int | None:
    """The index this UUID currently occupies, for CUDA_VISIBLE_DEVICES.

    Resolved fresh rather than assumed: the whole reason the holder takes
    a UUID is that indices move.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[1] == device_uuid:
            try:
                return int(parts[0])
            except ValueError:
                return None
    return None


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="VALIDATION-ONLY bounded GPU memory holder")
    p.add_argument("--device_uuid", required=True, help="GPU UUID (not an index)")
    p.add_argument("--target_mib", type=int, default=DEFAULT_TARGET_MIB)
    p.add_argument("--min_valid_mib", type=int, default=DEFAULT_MIN_VALID_MIB)
    p.add_argument("--max_mib", type=int, default=DEFAULT_MAX_MIB)
    p.add_argument("--max_lifetime_s", type=int, default=DEFAULT_MAX_LIFETIME_S)
    p.add_argument("--evidence_dir", required=True)
    return p


def validate_bounds(args: argparse.Namespace) -> str | None:
    """Why these bounds cannot produce a verdict, or None if they can."""
    if args.min_valid_mib >= args.max_mib:
        return f"min_valid_mib {args.min_valid_mib} must be below max_mib {args.max_mib}"
    if not (args.min_valid_mib <= args.target_mib <= args.max_mib):
        return (
            f"target_mib {args.target_mib} must lie within [{args.min_valid_mib}, {args.max_mib}]"
        )
    if args.max_lifetime_s <= 0 or args.max_lifetime_s > DEFAULT_MAX_LIFETIME_S:
        return f"max_lifetime_s must be in (0, {DEFAULT_MAX_LIFETIME_S}]"
    return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = Path(args.evidence_dir)
    ready = evidence / "holder_ready.json"
    result = evidence / "holder_result.json"
    pid = os.getpid()

    problem = validate_bounds(args)
    if problem is not None:
        _write(result, {"status": "INCONCLUSIVE", "reason": problem, "pid": pid})
        print(f"[holder] refusing to start: {problem}", file=sys.stderr)
        return 2

    # Register the PID so the sampler labels this process HOLDER rather
    # than FOREIGN (FU-B-15). B-G2b's proof is "no *candidate* child",
    # and the holder is legitimately on the card at the same time — the
    # two must be distinguishable by identity, not by a command-line
    # guess. Written after the bounds check so a holder that refused to
    # start never claims the role.
    for target in (evidence / "samples", evidence):
        try:
            target.mkdir(parents=True, exist_ok=True)
            (target / "holder.pid").write_text(str(pid))
        except OSError:
            pass

    index = resolve_visible_index(args.device_uuid)
    if index is None:
        reason = f"GPU UUID {args.device_uuid} not present on this host"
        _write(result, {"status": "INCONCLUSIVE", "reason": reason, "pid": pid})
        print(f"[holder] {reason}", file=sys.stderr)
        return 2
    os.environ["CUDA_VISIBLE_DEVICES"] = str(index)

    import torch  # imported late so the module is importable without CUDA

    blocks: list[Any] = []
    started = time.time()
    stop = {"now": False}

    def _handle(signum, _frame):
        stop["now"] = True
        print(f"[holder] signal {signum} — releasing", file=sys.stderr)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    status, reason, observed = "INCONCLUSIVE", "did not reach the target window", None
    try:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable after pinning the UUID")
        elements = STEP_MIB * 1024 * 1024 // 4
        while not stop["now"]:
            if time.time() - started > args.max_lifetime_s:
                reason = "lifetime expired before reaching the target"
                break
            blocks.append(torch.empty(elements, dtype=torch.float32, device="cuda"))
            torch.cuda.synchronize()
            observed = measured_mib(args.device_uuid, pid)
            if observed is None:
                reason = "driver did not report this process's occupancy"
                break
            if observed > args.max_mib:
                status, reason = "FAILED", f"exceeded max_mib: {observed} > {args.max_mib}"
                break
            if observed >= args.target_mib:
                status, reason = "READY", "target window reached"
                break

        if status == "READY" and observed is not None and observed < args.min_valid_mib:
            # Defensive: the window is [min_valid, max], and a target
            # below the floor would produce an unusable scenario.
            status, reason = (
                "INCONCLUSIVE",
                (f"measured {observed} MiB is below the conclusive floor {args.min_valid_mib}"),
            )

        if status == "READY":
            _write(
                ready,
                {
                    "status": "READY",
                    "pid": pid,
                    "device_uuid": args.device_uuid,
                    "measured_mib": observed,
                    "target_mib": args.target_mib,
                    "min_valid_mib": args.min_valid_mib,
                    "max_mib": args.max_mib,
                    "validation_only": True,
                },
            )
            print(f"[holder] READY pid={pid} measured={observed} MiB", flush=True)
            while not stop["now"] and time.time() - started < args.max_lifetime_s:
                time.sleep(1)
            reason = "released on deadline or signal"
    except Exception as exc:
        status, reason = "FAILED", f"{type(exc).__name__}: {exc}"
    finally:
        blocks.clear()
        try:
            import torch as _t

            _t.cuda.empty_cache()
        except Exception:
            pass
        _write(
            result,
            {
                "status": status,
                "reason": reason,
                "pid": pid,
                "device_uuid": args.device_uuid,
                "measured_mib": observed,
                "held_seconds": round(time.time() - started, 1),
                "validation_only": True,
            },
        )
        print(f"[holder] {status}: {reason}", flush=True)
    return 0 if status in {"READY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
