"""Worker entry point for an isolated, memory-bounded VRAM pre-flight.

Run as
``python -m agent.skills.evaluate_vram_skill.preflight_worker_main <spec>``
in its own process group. Everything expensive happens here and nowhere
else: model construction, structural inspection, and the bounded CUDA
probe. The parent stays small so that it survives whatever this process
does.

Ordering inside this file is load-bearing. `RLIMIT_AS` is applied
BEFORE torch is imported and before anything is constructed, because a
limit set after allocation protects nothing. That is the mistake the
2026-07-31 host OOM made structurally possible: the pre-flight ran in the
long-lived process, so by the time memory grew there was no boundary left
to enforce.
"""

from __future__ import annotations

import json
import resource
import sys
from pathlib import Path


def _apply_memory_limit(limit_bytes: int) -> None:
    """Bound this process's address space, before importing torch.

    Uses the soft limit only, and never raises the hard limit, so the
    worker can be bounded further by an outer mechanism but never loosen
    itself.
    """
    _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    ceiling = limit_bytes if hard == resource.RLIM_INFINITY else min(limit_bytes, hard)
    resource.setrlimit(resource.RLIMIT_AS, (ceiling, hard))
    print(f"[worker] RLIMIT_AS soft limit set to {ceiling / 1024**3:.2f} GiB", flush=True)


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

    # FIRST, before torch exists in this process.
    _apply_memory_limit(int(spec["worker_memory_limit_bytes"]))

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
    except MemoryError as exc:
        # RLIMIT_AS refused an allocation. The candidate exceeded its host
        # allowance, which is a real measured fact — and a different fact
        # from "it does not fit the GPU".
        _write(
            result_path,
            {
                "outcome": "MEASURED_HOST_MEMORY_EXCEEDED",
                "detail": f"allocation refused by RLIMIT_AS: {exc}",
                "phase": "worker_allocation",
            },
        )
        return 0
    except Exception as exc:
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
    if status == "inconclusive":
        return {
            "outcome": "MEASURED_HARD_TIMEOUT",
            "detail": str(outcome.get("message") or "")[:400],
            "phase": (outcome.get("timeout_record") or {}).get("operation") or "inspection",
        }
    if status == "error":
        message = str(outcome.get("message") or "")
        if "out of memory" in message.lower() or "OutOfMemoryError" in message:
            return {
                "outcome": "MEASURED_CUDA_OOM",
                "detail": message[:400],
                "phase": "cuda_probe",
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
