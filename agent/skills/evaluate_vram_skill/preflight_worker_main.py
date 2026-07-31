"""Worker entry point for an isolated, memory-bounded VRAM pre-flight.

Run as
``python -m agent.skills.evaluate_vram_skill.preflight_worker_main <spec>``
in its own process group. Everything expensive happens here and nowhere
else: model construction, structural inspection, and the bounded CUDA
probe. The parent stays small so that it survives whatever this process
does.

Host memory is bounded by the PARENT, which samples this process tree's
resident memory. `RLIMIT_AS` is deliberately NOT used.

That was tried and measured on 2026-07-31 (SHA d83f397). `RLIMIT_AS`
bounds VIRTUAL ADDRESS SPACE, and importing torch plus touching CUDA
reserves ~19.0 GiB of address space while holding ~0.65 GiB resident:

    before torch : VmSize    38 MiB   VmRSS  13 MiB
    after torch  : VmSize  5.9 GiB    VmRSS 0.5 GiB
    after cuda   : VmSize 19.0 GiB    VmRSS 0.65 GiB

A 24 GiB address-space limit therefore left ~5 GiB for real work, and all
three validation candidates failed to allocate while their resident
memory was only 3.9-5.7 GiB. Reservation is not consumption; using one to
bound the other is the same error as using wall time to bound memory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _write(result_path: str, payload: dict) -> None:
    """Atomic, bounded result. Only metadata crosses the boundary."""
    target = Path(result_path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(target)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: preflight_worker_main <spec.json>", file=sys.stderr)
        return 2

    spec = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    result_path = spec["result_path"]

    limit_gib = int(spec["worker_memory_limit_bytes"]) / 1024**3
    print(
        f"[worker] host memory bounded by the parent RSS monitor at "
        f"{limit_gib:.1f} GiB (RLIMIT_AS deliberately not used)",
        flush=True,
    )

    try:
        from agent.skills.evaluate_vram_skill.wrapper import run_skill

        print(f"[worker] pre-flight for {spec['model_type']}", flush=True)
        outcome = run_skill(
            None,
            model_type=spec["model_type"],
            model_config=dict(spec.get("model_config_payload") or {}),
            train_config=dict(spec.get("train_config") or {}),
            loss_config=dict(spec.get("loss_config") or {}),
            vram_budget_gb=spec["vram_budget_gb"],
        )
    except BaseException as exc:
        from agent.skills.evaluate_vram_skill.probe_budgets import (
            classify_host_memory_exception,
        )

        # A CANDIDATE that cannot be allocated is a candidate-level fact,
        # not a broken measurement system. PyTorch reports CPU allocation
        # failure as a plain RuntimeError, which `except MemoryError`
        # missed — two candidates were filed as infrastructure failures
        # on 2026-07-31 for exactly that reason.
        memory_kind = classify_host_memory_exception(exc)
        if memory_kind == "host":
            _write(
                result_path,
                {
                    "outcome": "HOST_MEMORY_ALLOCATION_FAILURE",
                    "detail": f"{type(exc).__name__}: {exc}"[:800],
                    "phase": "worker_allocation",
                },
            )
            return 0
        if memory_kind == "cuda":
            _write(
                result_path,
                {
                    "outcome": "MEASURED_CUDA_OOM",
                    "detail": f"{type(exc).__name__}: {exc}"[:800],
                    "phase": "cuda_probe",
                },
            )
            return 0
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        _write(
            result_path,
            {
                "outcome": "PROBE_INFRASTRUCTURE_FAILURE",
                "detail": f"{type(exc).__name__}: {exc}"[:800],
                "phase": "worker_exception",
            },
        )
        return 1

    _write(result_path, _classify(outcome))
    return 0


def _classify(outcome: dict) -> dict:
    """Reduce the skill's dict to ONE typed disposition plus metadata.

    A schema rejection is terminal and is never "completed" — the
    validation harness previously reported exactly that, with a null
    parameter count, and a harness that mislabels its own failures cannot
    validate anything.
    """
    status = outcome.get("status")

    if status == "schema_violation":
        violations = outcome.get("violations") or []
        first = violations[0] if violations else {}
        return {
            "outcome": "SCHEMA_REJECTED",
            "detail": str(outcome.get("verdict") or outcome.get("message") or "")[:400],
            "schema_field": first.get("field") or first.get("loc"),
            "schema_message": str(first.get("message") or outcome.get("message") or "")[:300],
            "phase": "schema_validation",
        }
    if status == "host_memory":
        return {
            "outcome": "HOST_MEMORY_ALLOCATION_FAILURE",
            "detail": str(outcome.get("message") or "")[:400],
            "phase": "host_allocation",
        }
    if status == "cuda_oom":
        return {
            "outcome": "MEASURED_CUDA_OOM",
            "detail": str(outcome.get("message") or "")[:400],
            "phase": "cuda_probe",
        }
    if status == "inconclusive":
        return {
            "outcome": "MEASURED_HARD_TIMEOUT",
            "detail": str(outcome.get("message") or "")[:400],
            "phase": (outcome.get("timeout_record") or {}).get("operation") or "inspection",
        }
    if status == "error":
        from agent.skills.evaluate_vram_skill.probe_budgets import (
            classify_host_memory_exception,
        )

        message = str(outcome.get("message") or "")
        kind = classify_host_memory_exception(RuntimeError(message))
        if kind == "cuda":
            return {"outcome": "MEASURED_CUDA_OOM", "detail": message[:400], "phase": "cuda_probe"}
        if kind == "host":
            return {
                "outcome": "HOST_MEMORY_ALLOCATION_FAILURE",
                "detail": message[:400],
                "phase": "host_allocation",
            }
        return {
            "outcome": "PROBE_INFRASTRUCTURE_FAILURE",
            "detail": message[:400],
            "phase": "skill_error",
        }

    common = {
        "realized_parameter_count": outcome.get("num_params"),
        "estimated_gb": outcome.get("estimated_gb"),
        "inference_batch": outcome.get("inference_batch"),
    }
    if outcome.get("feasible") is False:
        return {
            "outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP",
            "detail": str(outcome.get("verdict") or "")[:400],
            "phase": "vram_gate",
            **common,
        }
    return {
        "outcome": "COMPLETED_MEASUREMENT",
        "detail": str(outcome.get("verdict") or "")[:400],
        "phase": "complete",
        **common,
    }


if __name__ == "__main__":
    raise SystemExit(main())
