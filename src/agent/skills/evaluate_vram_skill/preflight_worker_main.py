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
from typing import Any, cast

from core.local_code.failure import raise_if_code_package_failure

#: Combined ceiling for the three rich diagnostic fields (PR A, D-A2).
#: They exist so an agent can act on a rejection; they must never become a
#: channel for tensors, state dicts or whole tracebacks.
RICH_FIELD_BUDGET_BYTES = 8 * 1024
#: Free text is truncated before structure, because a violating field name
#: with a clipped message is still actionable and the reverse is not.
_MAX_TEXT_CHARS = 400


def _clip_text(value: object, limit: int = _MAX_TEXT_CHARS) -> object:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…[clipped]"
    return value


def _shrink(payload: Any) -> Any:
    """Clip free text in place, leaving structure intact."""
    if isinstance(payload, dict):
        return {k: _shrink(_clip_text(v)) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_shrink(_clip_text(v)) for v in payload]
    return _clip_text(payload)


def _bounded_rich_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Fit the rich diagnostic fields inside ``RICH_FIELD_BUDGET_BYTES``.

    Truncation preserves JSON validity and the structured core: text is
    clipped first, and only if that is still too large is the largest
    field dropped — with ``truncated: true`` so a reader never mistakes a
    clipped record for a complete one.
    """
    present = {k: v for k, v in fields.items() if v not in (None, {}, [])}
    if not present:
        return {}

    def size(obj: dict[str, Any]) -> int:
        return len(json.dumps(obj, default=str).encode("utf-8"))

    if size(present) <= RICH_FIELD_BUDGET_BYTES:
        return present

    shrunk: dict[str, Any] = {k: _shrink(v) for k, v in present.items()}
    shrunk["truncated"] = True
    #: Original list lengths, so the omitted count below is against what
    #: the worker actually measured rather than against an already-
    #: shrunk intermediate.
    original_lengths = {k: len(v) for k, v in present.items() if isinstance(v, list)}

    # Shorten lists before discarding fields: ten violations with their
    # field names beat zero violations, and a schema rejection the agent
    # cannot act on is the same as no rejection detail at all.
    while size(shrunk) > RICH_FIELD_BUDGET_BYTES:
        lists = {k: v for k, v in shrunk.items() if isinstance(v, list) and len(v) > 1}
        if not lists:
            break
        longest = max(lists, key=lambda k: len(lists[k]))
        keep = max(1, len(shrunk[longest]) // 2)
        omitted = len(shrunk[longest]) - keep
        shrunk[longest] = shrunk[longest][:keep]
        shrunk[f"{longest}_omitted_count"] = shrunk.get(f"{longest}_omitted_count", 0) + omitted

    # Only if trimming lists was not enough does a whole field go, and it
    # is replaced by a marker rather than removed, so its absence is
    # explicit in the record.
    while size(shrunk) > RICH_FIELD_BUDGET_BYTES:
        droppable = [
            k
            for k, v in shrunk.items()
            if k != "truncated" and not k.endswith("_omitted_count") and not isinstance(v, str)
        ]
        if not droppable:
            break
        largest = max(droppable, key=lambda k: size({k: shrunk[k]}))
        shrunk[largest] = "[dropped: exceeded the rich-field budget]"

    # A5 repair, operator decision 2: ``truncated: true`` must never
    # appear without the omitted count. Three truncation modes reach
    # here — text shrinking alone, list trimming, and whole-field
    # dropping — and only the middle one used to record a count. A
    # record that says "something was cut" but not how much cannot tell
    # a reader whether one violation or forty were lost, which is the
    # measured part.
    for key, original in original_lengths.items():
        kept = len(shrunk[key]) if isinstance(shrunk.get(key), list) else 0
        shrunk[f"{key}_omitted_count"] = original - kept
    return shrunk


def _write(result_path: str, payload: dict) -> None:
    """Atomic, bounded result. Only metadata crosses the boundary."""
    target = Path(result_path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    tmp.replace(target)


def _task_probe_batch(raw: dict[str, Any], batch_size: int) -> tuple[Any, Any]:
    """Materialize one full batch through the run's existing task contract."""
    from execute_tools.task_probe_batch import load_task_probe_batch

    return load_task_probe_batch(raw, batch_size)


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

    # PR A / D-A3, D-A4. The parent resolves the hardware once and freezes
    # it here; the worker never discovers for itself, because a parent and
    # a worker that discover independently can disagree about the cap, the
    # device or the fingerprint, and that disagreement is invisible.
    #
    # ``HardwareSnapshot`` carries exactly the six attributes ``run_skill``
    # reads — usable_cap_bytes, usable_cap_gb, total_memory_bytes,
    # total_memory_gb, device_name, device_available — so it is passed
    # directly rather than reconstructed. See FU-A-3 for making that
    # contract a Protocol instead of a structural coincidence.
    snapshot = spec.get("hardware")
    if snapshot is not None:
        from agent.skills.evaluate_vram_skill.isolated_probe import HardwareSnapshot

        hardware = HardwareSnapshot(**snapshot)
        if snapshot.get("device_index") is not None:
            print(
                f"[worker] device {snapshot['device_index']} "
                f"({snapshot.get('device_name')}), "
                f"CUDA_VISIBLE_DEVICES={snapshot.get('cuda_visible_devices')!r}",
                flush=True,
            )
    else:
        hardware = None

    # Step 05b — the run's Model-I/O declaration, rebuilt from the parent's
    # value. Absence is legal and selects the legacy no-contract path; a
    # PRESENT-but-unrebuildable field is a transport failure and is reported
    # as one, naming the field. It must never degrade to ``None``: the child
    # would then silently probe the legacy shape and report a capacity number
    # for a different tensor than the parent asked about.
    raw_contract = spec.get("model_io_contract")
    model_io_contract = None
    if raw_contract is not None:
        from agent.schemas.model_io_contract import ModelIOContract

        try:
            model_io_contract = ModelIOContract(**raw_contract)
        except Exception as exc:
            _write(
                result_path,
                {
                    "outcome": "PROBE_INFRASTRUCTURE_FAILURE",
                    "detail": (
                        "the pre-flight spec carries a 'model_io_contract' the "
                        f"worker could not rebuild: {type(exc).__name__}: {exc}"
                    )[:800],
                    "phase": "spec_model_io_contract",
                },
            )
            return 0

    raw_loss_snapshot = spec.get("expected_custom_loss_snapshot")
    expected_custom_loss_snapshot = None
    if raw_loss_snapshot is not None:
        from core.capability_registry import CapabilityContractSnapshot

        try:
            expected_custom_loss_snapshot = CapabilityContractSnapshot.model_validate(
                raw_loss_snapshot
            )
        except Exception as exc:
            _write(
                result_path,
                {
                    "outcome": "PROBE_INFRASTRUCTURE_FAILURE",
                    "detail": (
                        "the pre-flight spec carries an 'expected_custom_loss_snapshot' "
                        f"the worker could not rebuild: {type(exc).__name__}: {exc}"
                    )[:800],
                    "phase": "spec_custom_loss_contract",
                },
            )
            return 0

    # ``None`` is "no operator ceiling", not "unset". The effective cap was
    # already resolved by the parent; the worker must not invent one.
    budget = spec.get("vram_budget_gb")
    if budget is None and hardware is not None:
        budget = hardware.usable_cap_gb
    limit_source = (
        "operator_vram_budget"
        if spec.get("vram_budget_gb") is not None
        else "hardware_snapshot_defensive_cap"
        if hardware is not None
        else "unbounded_no_snapshot"
    )
    print(f"[worker] effective VRAM limit {budget} GB (source: {limit_source})", flush=True)

    try:
        from agent.skills.evaluate_vram_skill.probe_budgets import ProbeBudgets
        from agent.skills.evaluate_vram_skill.wrapper import run_skill

        print(f"[worker] pre-flight for {spec['model_type']}", flush=True)
        probe_input_sample = None
        probe_target_sample = None
        inference_probe_input = None
        if spec.get("task_probe_data") is not None and (
            hardware is None or hardware.device_available
        ):
            probe_input_sample, probe_target_sample = _task_probe_batch(
                spec["task_probe_data"],
                int((spec.get("train_config") or {}).get("batch_size", 1)),
            )
        if (spec.get("task_probe_data") or {}).get("evaluation_scope_payload") is not None:
            from execute_tools.task_probe_batch import load_task_inference_probe_input

            inference_probe_input = load_task_inference_probe_input(spec["task_probe_data"])
        outcome = run_skill(
            None,
            model_type=spec["model_type"],
            model_config=dict(spec.get("model_config_payload") or {}),
            train_config=dict(spec.get("train_config") or {}),
            loss_config=dict(spec.get("loss_config") or {}),
            expected_custom_loss_snapshot=expected_custom_loss_snapshot,
            vram_budget_gb=budget,
            model_io_contract=model_io_contract,
            # HardwareSnapshot intentionally satisfies the audited
            # read-only HardwareContext surface used by run_skill:
            # usable_cap_bytes, usable_cap_gb, total_memory_bytes,
            # total_memory_gb, device_name, and device_available.
            # This is audited structural compatibility, not a blanket
            # escape from type checking — the cast is deliberately local
            # and must not spread to the adapter or the production caller.
            # test_hardware_snapshot_satisfies_run_skill_surface locks the
            # six attributes, so a seventh read by run_skill fails a test
            # rather than running silently. Widening the shared wrapper
            # type to a Protocol belongs to FU-A-3.
            hardware_context=cast("Any", hardware),
            probe_input_sample=probe_input_sample,
            probe_target_sample=probe_target_sample,
            inference_probe_input=inference_probe_input,
            max_inference_batch_size=(
                (spec.get("task_probe_data") or {}).get("max_inference_batch_size")
            ),
            probe_budgets=ProbeBudgets.model_validate(spec.get("probe_budgets") or {}),
        )
    except BaseException as exc:
        raise_if_code_package_failure(exc)
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
            # PR A / D-A2. The full violation list and the offending values
            # are what let an agent repair its config; a first-field
            # summary is not actionable. Bounded, never re-derived in the
            # parent — that would mean building the candidate there.
            **_bounded_rich_fields(
                {
                    "violations": violations,
                    "offending_config": outcome.get("offending_config"),
                }
            ),
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
    if status == "timeout":
        # A named deadline actually elapsed. The record carries which
        # operation and which budget, so the claim is checkable.
        record = outcome.get("timeout_record") or {}
        return {
            "outcome": "MEASURED_HARD_TIMEOUT",
            "detail": str(outcome.get("message") or "")[:400],
            "phase": record.get("operation") or "inspection",
            "timeout_operation": record.get("operation"),
            "timeout_budget_seconds": record.get("budget_seconds"),
            "timeout_elapsed_seconds": record.get("elapsed_seconds"),
        }
    if status == "inconclusive":
        # The inspection ended before any deadline without producing an
        # authoritative measurement. That is not a timeout, and it is not
        # a defect in the measurement system either — it establishes
        # nothing about the candidate, which is precisely what makes it
        # its own outcome rather than a borrowed one.
        return {
            "outcome": "INCONCLUSIVE_MEASUREMENT",
            "detail": str(outcome.get("message") or "")[:400],
            "phase": (outcome.get("timeout_record") or {}).get("phase") or "model_inspection",
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
        # Carried so the parent can rebuild the legacy contract without
        # recomputing anything (PR A §6).
        "limit_gb": outcome.get("limit_gb"),
        "dominant_phase": outcome.get("dominant_phase"),
        # PR A / review point 16.1-A. The agent-facing text is FORWARDED,
        # not regenerated in the parent. The skill already builds it once
        # (KillerReport.verdict / .suggestion); a second generator on the
        # parent side would drift from this one, and it would drift where
        # nobody reads — in the feedback the agent acts on.
        "verdict": str(outcome.get("verdict") or "")[:_MAX_TEXT_CHARS],
        "suggestion": str(outcome.get("suggestion") or "")[:_MAX_TEXT_CHARS],
    }
    if outcome.get("feasible") is False:
        return {
            "outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP",
            "detail": str(outcome.get("verdict") or "")[:400],
            "phase": "vram_gate",
            **common,
            # PR A / D-A2 — the killer report is the actionable part of an
            # infeasible verdict.
            **_bounded_rich_fields({"memory_killer": outcome.get("memory_killer")}),
        }
    return {
        "outcome": "COMPLETED_MEASUREMENT",
        "detail": str(outcome.get("verdict") or "")[:400],
        "phase": "complete",
        **common,
    }


if __name__ == "__main__":
    raise SystemExit(main())
