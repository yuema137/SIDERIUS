#!/usr/bin/env python
"""C12 validation campaign driver (tracks A and C).

    # what would run — no GPU, no writes
    .venv/bin/python scripts/runtime_campaign.py plan

    # one cell (operator-gated GPU)
    .venv/bin/python scripts/runtime_campaign.py run --cell punet@50K --run

    # aggregate whatever has been recorded and apply the FROZEN thresholds
    .venv/bin/python scripts/runtime_campaign.py verdict

Design points that matter:

* every cell is written the moment it completes, so a failure at cell 9
  never erases cells 1-8, and `verdict` works on a partial campaign;
* a failed cell is CLASSIFIED (measured_failure vs infrastructure
  failure) and never silently re-run with different settings;
* thresholds live in `CampaignThresholds` and carry an identity hash, so
  a post-hoc edit is visible in the report rather than invisible in a
  diff.

Track B (official legacy FCNet) has its own driver,
`scripts/legacy_fcnet_timing.py`, because its read-only constraints
around /home/tidmad/TIDMAD are stricter than anything here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.runtime_control.campaign import (  # noqa: E402
    MATRIX,
    PAIRWISE_PAIRS,
    CampaignCell,
    CampaignThresholds,
    CellMeasurement,
    evaluate_campaign,
    load_cells,
    matrix_cell_id,
    write_cell,
)

DEFAULT_OUTPUT_ROOT = Path("/home/klz/Data/SIDEREIS_DATA/runtime_validation/c12")
DEFAULT_CELL_WALL_SECONDS = 120.0


def cell_id(entry: dict) -> str:
    """One source of truth for cell ids — the matrix helper."""
    return matrix_cell_id(entry)


def build_plan(args) -> dict:
    cells = []
    for entry in MATRIX:
        cells.append(
            {
                "cell_id": cell_id(entry),
                "family": entry["family"],
                "target_parameter_count": entry["target"],
                "expected_realized_parameter_count": entry["realized"],
                "at_family_ceiling": entry.get("at_family_ceiling", False),
                "replacement_for": entry.get("replacement_for"),
                "replacement_reason": entry.get("replacement_reason"),
                "config": entry["config"],
                "registered_implementation": True,
                "source": "built-in MODEL_REGISTRY family (no novel model created)",
            }
        )
    return {
        "track_A_cells": cells,
        "track_C_pairs": [dict(p) for p in PAIRWISE_PAIRS],
        "probe_caps": {
            "max_wall_seconds": args.probe_wall_seconds,
            "n_warmup_steps": args.warmup_steps,
            "n_timed_train_steps": args.timed_steps,
            "n_timed_inference_batches": args.inference_batches,
        },
        "per_cell_execution_wall_seconds": args.cell_wall_seconds,
        "output_root": str(args.output_root),
        "thresholds": CampaignThresholds().model_dump(mode="json"),
        "thresholds_identity": CampaignThresholds().identity,
        "llm_calls": 0,
    }


def _resolve(entry_id: str) -> dict:
    for entry in MATRIX:
        if cell_id(entry) == entry_id:
            return entry
    raise SystemExit(f"unknown cell {entry_id!r}; see `plan` for the matrix")


def run_cell(entry_id: str, args) -> CampaignCell:
    """Probe -> project -> bounded real execution -> compare."""
    import torch

    from core.runtime_control.calibration_policy import sample_contention_window
    from core.runtime_control.probe_production import (
        probe_device_vram_gb,
        production_probe_executors,
    )
    from core.runtime_control.probe_subprocess import (
        ProbeInfrastructureFailure,
        ProbeWorkerSpec,
        run_worker,
    )

    entry = _resolve(entry_id)
    train_config = {
        "lr": 1e-4,
        "batch_size": args.batch_size,
        "epochs": 1,
        "optimizer_type": "adamw",
        "weight_decay": 1e-5,
        "device": "cuda",
    }

    def _cell(**fields) -> CampaignCell:
        """Build a cell with the shared identity fields.

        Explicit keywords rather than `**base` expansion: strict pyright
        cannot match a heterogeneous dict against the model's parameter
        types, and silencing that would hide real mismatches.
        """
        return CampaignCell(
            track="A_matrix",
            cell_id=entry_id,
            family=str(entry["family"]),
            target_parameter_count=int(entry["target"]),
            at_family_ceiling=bool(entry.get("at_family_ceiling", False)),
            replacement_for=entry.get("replacement_for"),
            replacement_reason=entry.get("replacement_reason"),
            wall_cap_seconds=args.cell_wall_seconds,
            **fields,
        )

    window = sample_contention_window(device_vram_gb=probe_device_vram_gb())
    if window.classification != "single_candidate_idle":
        return _cell(
            status="infrastructure_failure",
            failure_detail=f"GPU not idle: {window.classification}",
        )

    # C12 fix: the probe runs behind a PROCESS boundary so the wall cap is
    # a hard bound. A single stalled CUDA operation can no longer hang the
    # campaign (transformer@8M-ceiling did exactly that, twice).
    try:
        outcome = run_worker(
            ProbeWorkerSpec(
                model_type=entry["family"],
                model_config_payload=entry["config"],
                train_config=train_config,
                loss_config={"loss_type": "ce"},
                data_dir=args.data_dir,
                device="cuda",
                caps={
                    "max_wall_seconds": args.probe_wall_seconds,
                    "n_warmup_steps": args.warmup_steps,
                    "n_timed_train_steps": args.timed_steps,
                    "n_timed_inference_batches": args.inference_batches,
                },
                device_vram_gb=probe_device_vram_gb(),
                result_path=str(args.output_root / "workers" / f"{entry_id}.json"),
            ),
            hard_cap_seconds=args.probe_hard_cap_seconds,
        )
    except ProbeInfrastructureFailure as exc:
        # Our channel failed, not the candidate — record it, do not crash
        # the campaign and lose the cell.
        return _cell(status="infrastructure_failure", failure_detail=str(exc)[:2000])
    if outcome.classification == "measured_failure":
        return _cell(
            status="measured_failure",
            failure_class=outcome.failure_kind,
            failure_class_source="recorded live by the probe parent",
            failure_detail=(
                f"{outcome.detail} | termination={outcome.termination.model_dump(mode='json')}"
            ),
        )
    if outcome.classification == "infrastructure_failure":
        return _cell(status="infrastructure_failure", failure_detail=outcome.detail)

    worker = outcome.result
    assert worker is not None

    # The bounded EXECUTION segment still runs here, in-process, using the
    # rate the worker measured.
    try:
        executors = production_probe_executors(
            model_type=entry["family"],
            model_config=entry["config"],
            train_config=train_config,
            loss_config={"loss_type": "ce"},
            data_dir=args.data_dir,
        )
        executors.setup()
        result = worker
    except Exception as exc:
        # An OOM is a MEASURED statement about the candidate, not about our
        # infrastructure — classifying it as the latter would both mislabel
        # the evidence and (via the C9b resolver) halt a chain for a model
        # that merely does not fit.
        from core.runtime_control.probe import is_out_of_memory

        if is_out_of_memory(exc):
            return _cell(
                status="measured_failure",
                failure_class="capacity",
                failure_class_source="recorded live by the probe parent",
                failure_detail=f"probe OOM: {exc}",
            )
        return _cell(
            status="infrastructure_failure",
            failure_detail=f"probe could not be built or run: {exc!r}",
        )

    realized = result.realized or {}
    probe = CellMeasurement(
        provenance="bounded_live_probe",
        setup_seconds=result.setup_seconds,
        train_ms_per_step=result.train_ms_per_step,
        inference_ms_per_unit=result.inference_ms_per_batch,
        inference_work_unit="inference_batch",
        peak_vram_allocated_gb=result.peak_vram_gb,
        realized_parameter_count=realized.get("parameter_count"),
        trainable_parameter_count=realized.get("trainable_parameter_count"),
        parameter_memory_gb=realized.get("parameter_memory_gb"),
        dtype=realized.get("dtype"),
        concurrency_identity=result.concurrency_identity,
    )

    # Project onto the number of steps the wall cap allows, then execute
    # exactly that many — projection and execution describe the SAME work.
    assert probe.train_ms_per_step
    planned_steps = max(1, int(args.cell_wall_seconds * 1000.0 / probe.train_ms_per_step))
    projected = probe.train_ms_per_step * planned_steps / 1000.0

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    executed = 0
    for _ in range(planned_steps):
        if time.perf_counter() - started >= args.cell_wall_seconds * 1.5:
            break
        executors.train_step()
        executed += 1
    torch.cuda.synchronize()
    actual = time.perf_counter() - started

    return _cell(
        status="ok",
        probe=probe,
        projected_seconds=projected,
        actual_seconds=actual,
        actual_steps=executed,
        actual_ms_per_step=(actual * 1000.0 / executed) if executed else None,
        predicted_peak_vram_gb=result.peak_vram_gb,
        actual_peak_vram_gb=torch.cuda.max_memory_allocated() / 2**30 or None,
    )


def _pair_entry(label: str) -> dict:
    for pair in PAIRWISE_PAIRS:
        if pair["label"] == label:
            return dict(pair)
    raise SystemExit(f"unknown pair {label!r}; see `plan` for track C")


def _probe_member(member: str, args, *, tag: str, peer_pids: tuple[int, ...] = ()):
    """One member's bounded probe, alone or with a registered peer."""
    from core.runtime_control.probe_production import probe_device_vram_gb
    from core.runtime_control.probe_subprocess import ProbeWorkerSpec, run_worker

    entry = _resolve(member)
    return run_worker(
        ProbeWorkerSpec(
            model_type=entry["family"],
            model_config_payload=entry["config"],
            train_config={
                "lr": 1e-4,
                "batch_size": args.batch_size,
                "epochs": 1,
                "optimizer_type": "adamw",
                "weight_decay": 1e-5,
                "device": "cuda",
            },
            loss_config={"loss_type": "ce"},
            data_dir=args.data_dir,
            device="cuda",
            caps={
                "max_wall_seconds": args.probe_wall_seconds,
                "n_warmup_steps": args.warmup_steps,
                "n_timed_train_steps": args.timed_steps,
                "n_timed_inference_batches": args.inference_batches,
            },
            device_vram_gb=probe_device_vram_gb(),
            expected_peer_pids=peer_pids,
            result_path=str(args.output_root / "workers" / f"pair_{tag}.json"),
        ),
        hard_cap_seconds=args.probe_hard_cap_seconds,
    )


def _spawn_load(member: str, args, *, tag: str, seconds: float):
    """A partner that genuinely computes for the whole measured window."""
    from core.runtime_control.probe_production import probe_device_vram_gb
    from core.runtime_control.probe_subprocess import ProbeWorkerSpec, spawn_worker

    entry = _resolve(member)
    return spawn_worker(
        ProbeWorkerSpec(
            model_type=entry["family"],
            model_config_payload=entry["config"],
            train_config={
                "lr": 1e-4,
                "batch_size": args.batch_size,
                "epochs": 1,
                "optimizer_type": "adamw",
                "weight_decay": 1e-5,
                "device": "cuda",
            },
            loss_config={"loss_type": "ce"},
            data_dir=args.data_dir,
            device="cuda",
            device_vram_gb=probe_device_vram_gb(),
            sustained_seconds=seconds,
            result_path=str(args.output_root / "workers" / f"load_{tag}.json"),
        )
    )


def run_pair(label: str, args) -> dict:
    """C12-C: each member ALONE, then the same member with the other
    registered as an explicit peer and genuinely computing.

    An idle baseline must exist before a contention multiplier can mean
    anything, so the alone stages run first and a non-idle alone stage
    invalidates the cell rather than being quietly accepted.
    """
    from core.runtime_control.probe_subprocess import ProbeInfrastructureFailure, stop_worker

    pair = _pair_entry(label)
    members: tuple[str, str] = tuple(pair["members"])  # type: ignore[assignment]
    record: dict = {
        "track": "C_pairwise",
        "label": label,
        "members": list(members),
        "stagger_seconds": args.stagger_seconds,
        "load_seconds": args.load_seconds,
        "stages": {},
    }

    alone: dict[str, dict] = {}
    for member in members:
        try:
            outcome = _probe_member(member, args, tag=f"{label}_{member}_alone")
        except ProbeInfrastructureFailure as exc:
            record["status"] = "infrastructure_failure"
            record["failure_detail"] = f"{member} alone: {str(exc)[:1500]}"
            return record
        if outcome.classification != "ok" or outcome.result is None:
            record["status"] = outcome.classification
            record["failure_detail"] = f"{member} alone: {outcome.detail[:1500]}"
            return record
        alone[member] = {
            "ms_per_step": outcome.result.train_ms_per_step,
            "concurrency_identity": outcome.result.concurrency_identity,
            "peak_vram_gb": outcome.result.peak_vram_gb,
        }
        record["stages"][f"{member}_alone"] = alone[member]

    # Each member measured while the OTHER trains continuously.
    for measured, partner in (members, tuple(reversed(members))):
        tag = f"{label}_{measured}_paired"
        process, handle, log_path = _spawn_load(partner, args, tag=tag, seconds=args.load_seconds)
        try:
            time.sleep(args.stagger_seconds)  # let the partner reach steady state
            if process.poll() is not None:
                record["status"] = "infrastructure_failure"
                record["failure_detail"] = (
                    f"background load {partner} exited early "
                    f"(rc={process.returncode}); log={log_path}"
                )
                return record
            outcome = _probe_member(measured, args, tag=tag, peer_pids=(process.pid,))
        except ProbeInfrastructureFailure as exc:
            record["status"] = "infrastructure_failure"
            record["failure_detail"] = f"{measured} paired: {str(exc)[:1500]}"
            return record
        finally:
            stop_worker(process)
            handle.close()

        if outcome.classification != "ok" or outcome.result is None:
            record["status"] = outcome.classification
            record["failure_detail"] = f"{measured} paired: {outcome.detail[:1500]}"
            return record
        paired_ms = outcome.result.train_ms_per_step
        alone_ms = alone[measured]["ms_per_step"]
        record["stages"][f"{measured}_paired_with_{partner}"] = {
            "ms_per_step": paired_ms,
            "concurrency_identity": outcome.result.concurrency_identity,
            "registered_peer_pid": process.pid,
            "peak_vram_gb": outcome.result.peak_vram_gb,
            "contention_multiplier": (
                round(paired_ms / alone_ms, 4) if paired_ms and alone_ms else None
            ),
        }

    record["status"] = "ok"
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="C12 validation campaign (tracks A and C).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "pair", "verdict"):
        p = sub.add_parser(name)
        p.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
        p.add_argument("--data-dir", default=None)
        p.add_argument("--batch-size", type=int, default=8)
        p.add_argument("--probe-wall-seconds", type=float, default=90.0)
        p.add_argument("--warmup-steps", type=int, default=3)
        p.add_argument("--timed-steps", type=int, default=7)
        p.add_argument("--inference-batches", type=int, default=5)
        p.add_argument("--cell-wall-seconds", type=float, default=DEFAULT_CELL_WALL_SECONDS)
        p.add_argument(
            "--probe-hard-cap-seconds",
            type=float,
            default=300.0,
            help="HARD process-level bound on the probe worker (C12 fix).",
        )
        if name == "run":
            p.add_argument("--cell", required=True)
        if name == "pair":
            p.add_argument("--pair", required=True)
            p.add_argument(
                "--stagger-seconds",
                type=float,
                default=25.0,
                help="How long the background partner trains before the measured probe starts.",
            )
            p.add_argument(
                "--load-seconds",
                type=float,
                default=240.0,
                help="How long the background partner keeps training.",
            )
        if name in ("run", "pair"):
            p.add_argument("--run", action="store_true", help="Execute on the GPU.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "plan":
        print(json.dumps(build_plan(args), indent=2))
        return 0

    if args.command == "verdict":
        cells = load_cells(args.output_root)
        report = evaluate_campaign(cells, CampaignThresholds())
        print(json.dumps(report.model_dump(mode="json"), indent=2))
        return 0 if report.verdict == "C12 PASS" else 1

    if args.command == "pair":
        if not args.run:
            print(
                json.dumps({"would_run_pair": args.pair, "pair": _pair_entry(args.pair)}, indent=2)
            )
            return 0
        record = run_pair(args.pair, args)
        path = args.output_root / "pairs" / f"{args.pair}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps(record, indent=2))
        print(f"\n  pair -> {path}")
        return 0 if record.get("status") == "ok" else 1

    if not args.run:
        print(json.dumps({"would_run": args.cell, **build_plan(args)}, indent=2))
        return 0
    cell = run_cell(args.cell, args)
    path = write_cell(args.output_root, cell)  # persisted IMMEDIATELY
    print(json.dumps(cell.model_dump(mode="json"), indent=2))
    print(f"\n  cell -> {path}")
    return 0 if cell.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
