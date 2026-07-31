#!/usr/bin/env python
"""Bootstrap a NEW environment for SIDERIUS runtime control (C10).

Answers one question: can this machine produce measured runtime evidence,
and is it therefore safe to launch on? Inspects the environment, builds
the hardware and execution profiles, validates the dataset, samples the
contention window, runs a BOUNDED training + inference probe on a real
registered model, records the observations through the versioned
calibration registry, verifies them by hash-checked read-back, runs the
same self-test the launch guard runs, and prints READY or NOT READY with
actionable reasons.

No LLM calls. No manual source or JSON editing. Nothing is written except
through the registry.

Usage (repo root, project venv):

    .venv/bin/python scripts/runtime_bootstrap.py

    # inspect only — no probe, no writes
    .venv/bin/python scripts/runtime_bootstrap.py --dry-run

    # isolate the registry (recommended for a first run)
    .venv/bin/python scripts/runtime_bootstrap.py \
        --registry-dir /tmp/siderius_bootstrap

Exit codes: 0 = READY, 1 = NOT READY, 2 = usage error.

C10 proves an environment can bootstrap. It does NOT validate estimator
accuracy across model families, scales and concurrency regimes — that is
the C12 campaign.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

#: A small, registered, real model. Bootstrap measures the ENVIRONMENT,
#: not the architecture, so the default is deliberately cheap.
DEFAULT_MODEL = "punet_ce_loss_control_nano"
DEFAULT_SEGMENTATION_SIZE = 40_000
DEFAULT_BATCH_SIZE = 8


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap and readiness self-test for SIDERIUS runtime control.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Registered model to probe (default: {DEFAULT_MODEL}). Bootstrap "
        "measures the environment, so a small model is correct here.",
    )
    parser.add_argument("--segmentation-size", type=int, default=DEFAULT_SEGMENTATION_SIZE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--data-dir",
        default=None,
        help="TIDMAD directory. Default: the canonical resolution in "
        "execute_tools/data_paths.py — never a second convention.",
    )
    parser.add_argument(
        "--registry-dir",
        default=None,
        help="Isolate the calibration registry here (sets SIDERIUS_CALIBRATION_DIR "
        "for this process). Default: the standard per-user registry.",
    )
    parser.add_argument(
        "--max-wall-seconds",
        type=float,
        default=90.0,
        help="Hard cap for the probe (default: 90).",
    )
    parser.add_argument("--warmup-steps", type=int, default=3)
    parser.add_argument("--timed-train-steps", type=int, default=7)
    parser.add_argument("--timed-inference-batches", type=int, default=5)
    parser.add_argument(
        "--expected-peer-pid",
        type=int,
        action="append",
        default=[],
        help="Explicitly registered peer PID (repeatable). Any OTHER process on "
        "the device makes the window contended — peers are never inferred.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect the environment and report what WOULD run. No probe, no writes.",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.registry_dir:
        # The registry resolves its root from this variable; setting it here
        # is what makes --registry-dir work without any file editing.
        os.environ["SIDERIUS_CALIBRATION_DIR"] = args.registry_dir

    from core.runtime_control.bootstrap import (
        BootstrapDependencies,
        production_dependencies,
        run_bootstrap,
    )

    caps = {
        "max_wall_seconds": args.max_wall_seconds,
        "n_warmup_steps": args.warmup_steps,
        "n_timed_train_steps": args.timed_train_steps,
        "n_timed_inference_batches": args.timed_inference_batches,
    }
    model_config = {"segmentation_size": args.segmentation_size}
    train_config = {
        "lr": 1e-4,
        "batch_size": args.batch_size,
        "epochs": 1,
        "optimizer_type": "adamw",
        "weight_decay": 1e-5,
        "device": "cuda",
    }

    if args.dry_run:
        return _dry_run(args, caps, model_config)

    deps: BootstrapDependencies = production_dependencies()
    report = run_bootstrap(
        model_type=args.model,
        model_config=model_config,
        train_config=train_config,
        loss_config={"loss_type": "ce"},
        deps=deps,
        caps=caps,
        data_dir=args.data_dir,
        expected_peer_pids=tuple(args.expected_peer_pid),
    )
    if args.as_json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(report.render())
    return 0 if report.ready else 1


def _dry_run(args, caps: dict, model_config: dict) -> int:
    """Report what a real run would do, touching nothing."""
    from core.runtime_control.estimator import shared_runtime_components
    from core.runtime_control.probe_wiring import probe_runner_availability

    estimator, policy = shared_runtime_components()
    available, detail = probe_runner_availability()
    plan = {
        "model": args.model,
        "model_config": model_config,
        "batch_size": args.batch_size,
        "caps": caps,
        "data_dir": args.data_dir or "<canonical TIDMAD_DATA_DIR>",
        "registry_dir": os.environ.get("SIDERIUS_CALIBRATION_DIR", "<default per-user>"),
        "expected_peer_pids": args.expected_peer_pid,
        "probe_runner_available": available,
        "probe_runner_detail": detail,
        "estimator_identity": estimator.identity,
        "policy_identity": policy.identity,
        "writes": "calibration registry only (2 observations: training + inference)",
        "llm_calls": 0,
    }
    if args.as_json:
        print(json.dumps(plan, indent=2))
    else:
        print("\n  DRY RUN — nothing was executed or written\n")
        for key, value in plan.items():
            print(f"    {key:24} : {value}")
        print()
    return 0 if available else 1


if __name__ == "__main__":
    raise SystemExit(main())
