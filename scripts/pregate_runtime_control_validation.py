"""
Pre-Gate real-GPU validation driver for the runtime-control system.

Design: docs/design/runtime_estimation_and_watchdog.md §8 + the
operator's pre-Gate validation plan (2026-07-23). Deterministic,
NO LLM calls: drives the PRODUCTION executor path directly —
`TidmadSandbox.execute_training` / `execute_inference` with a real
`RuntimeControlPolicy`, real TIDMAD data, real sandbox subprocesses,
the real sidecar event log and observation store — exactly the calls
the tuner makes, minus the planner.

Scenarios (run one per invocation; each uses its own run_name):

  1  normal admitted end-to-end   (~2-4 min)
  2  in-subprocess over-budget rejection, incident-shaped (~1-2 min)
  3  real watchdog kill of the inference subprocess (~3 min)
  4  historical-prior round trip: 3 sub-runs (match / early-exit /
     changed-key)  (~6-9 min)

Usage (from the repo root, project venv):

  .venv/bin/python scripts/pregate_runtime_control_validation.py \
      --scenario 1 --workspace /tmp/pregate_rc

Artifacts land under {workspace}/: per-run records, the
runtime_verification sidecars (configs/), the observation store
(runtime_observations/), and a JSON report at
{workspace}/report_scenario{N}.json.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.runtime_control.observation_store import ObservationStore
from core.runtime_control.records import RuntimeObservation
from core.sandbox_executor import TidmadSandbox
from execute_tools.dataset_config import DataScope

WAVENET_SMALL = {
    "model_type": "wavenet",
    "segmentation_size": 10_000,
    "batch_size": 1,
    "input_channels": 16,
    "residual_channels": 32,
    "gate_channels": 64,
    "skip_channels": 32,
    "kernel_size": 12,
    "num_blocks": 10,
}
LOSS_FOCAL = {"loss_type": "focal"}


def _gpu_snapshot() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {"memory_used_mib": int(out.stdout.strip().splitlines()[0])}
    except Exception as exc:
        return {"error": str(exc)}


def _process_residue() -> list[str]:
    """Any surviving sandbox engine processes (should be empty)."""
    try:
        out = subprocess.run(["ps", "-eo", "pid,cmd"], capture_output=True, text=True, timeout=10)
        return [
            line.strip()
            for line in out.stdout.splitlines()
            if ("train_engine_sandbox" in line or "inference_single" in line)
            and "grep" not in line
            and "bash -c" not in line  # the driver's own wrapper shell mentions the names
        ]
    except Exception as exc:
        return [f"ps failed: {exc}"]


class SidecarWatcher(threading.Thread):
    """Samples the live sidecar to evidence the stage PROGRESSION
    (the final file alone only shows the last state)."""

    def __init__(self, path: str):
        super().__init__(daemon=True)
        self.path = path
        self.stages: list[str] = []
        # NOTE: must not be named ``_stop`` — that shadows
        # threading.Thread._stop(), which the interpreter calls on
        # join/fork (found live in scenario 1).
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                with open(self.path, encoding="utf-8") as f:
                    status = json.load(f).get("final_status")
                if status and (not self.stages or self.stages[-1] != status):
                    self.stages.append(status)
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(0.2)

    def stop(self) -> None:
        self._halt.set()


def _component_table(observation: dict) -> dict:
    table = {}
    for phase, component in (observation.get("components") or {}).items():
        prediction = component.get("prediction") or {}
        error = component.get("prediction_error") or {}
        table[phase] = {
            "predicted_s": prediction.get("predicted_seconds"),
            "source": prediction.get("source"),
            "actual_s": component.get("actual_seconds"),
            "ratio_actual_over_predicted": error.get("ratio"),
        }
    return table


def _run_attempt(
    sandbox: TidmadSandbox,
    *,
    exp_id: str,
    run_name: str,
    model_cfg: dict,
    train_cfg: dict,
    train_ss: dict,
    eval_ss: dict,
    policy: dict,
    run_inference: bool,
    report: dict,
) -> dict:
    """One production attempt: training (+inference) + store append."""
    sidecar = os.path.join(sandbox.dirs["configs"], f"runtime_verification_{exp_id}.json")
    watcher = SidecarWatcher(sidecar)
    watcher.start()
    t0 = time.perf_counter()
    train_status = sandbox.execute_training(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_cfg["model_type"],
        m_cfg=model_cfg,
        t_cfg=train_cfg,
        l_cfg=LOSS_FOCAL,
        sample_set=train_ss,
        train_portion=1.0,
        train_base_seed=42,
        runtime_policy=policy,
    )
    train_wall = time.perf_counter() - t0
    inf_status = None
    inf_wall = None
    if run_inference and train_status.get("status") == "success":
        t1 = time.perf_counter()
        inf_status = sandbox.execute_inference(
            exp_id=exp_id,
            run_name=run_name,
            model_type=model_cfg["model_type"],
            m_cfg=model_cfg,
            l_cfg=LOSS_FOCAL,
            sample_set=eval_ss,
            runtime_policy=policy,
        )
        inf_wall = time.perf_counter() - t1
    watcher.stop()
    watcher.join(timeout=2)

    final_block = None
    for status in (inf_status, train_status):
        if status and status.get("runtime_verification"):
            final_block = status["runtime_verification"]
            break
    if final_block:
        try:
            ObservationStore(os.path.join(sandbox.base_dir, "runtime_observations")).append(
                RuntimeObservation.model_validate(final_block), writer_id=run_name
            )
        except Exception as exc:
            report.setdefault("issues", []).append(f"store append failed: {exc}")

    return {
        "train_status": train_status.get("status"),
        "train_message": train_status.get("message"),
        "train_wall_s": round(train_wall, 2),
        "train_watchdog": train_status.get("watchdog"),
        "inference_status": (inf_status or {}).get("status"),
        "inference_wall_s": round(inf_wall, 2) if inf_wall is not None else None,
        "inference_watchdog": (inf_status or {}).get("watchdog"),
        "sidecar_stage_progression": watcher.stages,
        "observation": final_block,
        "component_table": _component_table(final_block or {}),
        "admission": (final_block or {}).get("admission"),
    }


def _artifact_state(sandbox: TidmadSandbox, run_name: str, exp_id: str, model_type: str) -> dict:
    models = sandbox.dirs["models"]
    denoised = glob.glob(
        os.path.join(
            sandbox.base_dir, f"abra_validation_denoised_{model_type}_{run_name}_{exp_id}_*.h5"
        )
    )
    return {
        "checkpoint_exists": os.path.exists(
            os.path.join(models, f"model_{model_type}_{exp_id}_agent.pth")
        ),
        "sentinel_exists": os.path.exists(os.path.join(models, f"_OK_{exp_id}")),
        "denoised_files": [os.path.basename(p) for p in denoised],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument("--workspace", type=str, required=True)
    args = parser.parse_args()

    scenario = args.scenario
    run_name = f"pregate_s{scenario}"
    store_root = os.path.join(os.path.abspath(args.workspace), "runtime_observations")
    report: dict = {
        "scenario": scenario,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "gpu_before": _gpu_snapshot(),
    }

    sandbox = TidmadSandbox(
        run_name=run_name,
        workspace=args.workspace,
        progress_bar=False,
        data_scope=DataScope.from_cli("0-1"),
    )
    base_policy = {"observation_store_root": store_root}

    if scenario == 1:
        # Normal admitted end-to-end: 750 steps, 80 inference batches.
        report["attempt"] = _run_attempt(
            sandbox,
            exp_id="s1_admitted",
            run_name=run_name,
            model_cfg={**WAVENET_SMALL},
            train_cfg={"epochs": 1, "batch_size": 8, "optimizer_type": "adam", "lr": 5e-4},
            train_ss={"0": list(range(6))},
            eval_ss={"0": [0, 1]},
            policy={**base_policy, "operator_budget_seconds": 1800.0},
            run_inference=True,
            report=report,
        )
        report["artifacts"] = _artifact_state(sandbox, run_name, "s1_admitted", "wavenet")

    elif scenario == 2:
        # Incident-shaped rejection: seg 1250 / batch 2 / 80,000 steps
        # vs a 300 s budget — must be REJECTED at live verification.
        report["attempt"] = _run_attempt(
            sandbox,
            exp_id="s2_reject",
            run_name=run_name,
            model_cfg={**WAVENET_SMALL, "segmentation_size": 1250},
            train_cfg={"epochs": 1, "batch_size": 2, "optimizer_type": "adam", "lr": 5e-4},
            train_ss={"0": list(range(10)), "1": list(range(10))},
            eval_ss={"0": [0]},
            policy={**base_policy, "operator_budget_seconds": 300.0},
            run_inference=False,
            report=report,
        )
        report["artifacts"] = _artifact_state(sandbox, run_name, "s2_reject", "wavenet")

    elif scenario == 3:
        # Watchdog: tiny training admitted under the 90 s budget; the
        # inference outlasts the deadline and is KILLED. Eval scope
        # resized after S1/S2 measured ~19.4 ms/batch on this H100
        # (2x faster than the sizing guess): 80 PSD → 3200 batches
        # ≈ 65-75 s, above the 60 s floor / sub-90 s tightened deadline.
        policy = {
            **base_policy,
            "operator_budget_seconds": 90.0,
            "watchdog": {
                "enabled": True,
                "grace_seconds": 10.0,
                "poll_seconds": 1.0,
                "floor_seconds": 60.0,
            },
        }
        report["attempt"] = _run_attempt(
            sandbox,
            exp_id="s3_watchdog",
            run_name=run_name,
            model_cfg={**WAVENET_SMALL},
            train_cfg={"epochs": 1, "batch_size": 8, "optimizer_type": "adam", "lr": 5e-4},
            train_ss={"0": [0, 1]},
            eval_ss={"0": list(range(40)), "1": list(range(40))},
            policy=policy,
            run_inference=True,
            report=report,
        )
        report["artifacts"] = _artifact_state(sandbox, run_name, "s3_watchdog", "wavenet")

    elif scenario == 4:
        # Prior round trip: identical run twice (2nd should find a valid
        # prior and reach verified_match), then a changed key (batch 16
        # → new_configuration; the old prior must not cross-apply).
        runs = {}
        for tag, batch in (("first", 8), ("second", 8), ("changed_key", 16)):
            runs[tag] = _run_attempt(
                sandbox,
                exp_id=f"s4_{tag}",
                run_name=run_name,
                model_cfg={**WAVENET_SMALL},
                train_cfg={"epochs": 1, "batch_size": batch, "optimizer_type": "adam", "lr": 5e-4},
                train_ss={"0": list(range(6))},
                eval_ss={"0": [0]},
                policy={**base_policy, "operator_budget_seconds": 1800.0},
                run_inference=False,
                report=report,
            )
            training = (runs[tag]["observation"] or {}).get("components", {}).get("training", {})
            detail = (training.get("measurement") or {}).get("detail") or {}
            runs[tag]["prior_agreement"] = detail.get("prior_agreement")
            runs[tag]["prior_expected_unit_ms"] = detail.get("prior_expected_unit_ms")
            runs[tag]["verification_seconds"] = (training.get("measurement") or {}).get(
                "total_measurement_seconds"
            )
        report["runs"] = runs

    report["gpu_after"] = _gpu_snapshot()
    report["process_residue"] = _process_residue()
    store = ObservationStore(store_root)
    report["store_observation_count"] = len(store.read_all())
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    out_path = os.path.join(os.path.abspath(args.workspace), f"report_scenario{scenario}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n=== Scenario {scenario} report: {out_path} ===")
    print(
        json.dumps({k: v for k, v in report.items() if k != "attempt"}, indent=2, default=str)[
            :2000
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
