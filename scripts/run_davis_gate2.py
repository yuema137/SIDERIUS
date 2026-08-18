"""Bounded DAVIS Gate-2 runner (D14-3 C7).

The full Track-C loop at the COMMITTED gate subsets — real frames → the
DAVIS TaskDataPath window reader → the PRODUCTION training engine (real
R2+R3 through the 07a machinery, the D14-2 C5b explicit eval leg) →
inference → the npz deliverable → global MSE through the Step-06 handle.
Work is bounded BEFORE anything starts (§17.0.1): 60 train / 15 validation
/ 15 final clips, 2 epochs.

PASS is FUNCTIONAL: validated R2+R3 with ``comparability`` stamped, 15/15
predictions, a finite MSE >= 0 from the real handle. Model quality is NOT a
pass condition; MSE against the trivial last-frame-copy baseline is
recorded as an observation.

Usage::

    SIDERIUS_ALLOW_LAUNCH=1 .venv/bin/python scripts/run_davis_gate2.py \
        --data_dir /home/klz/Data/DAVIS_2017 \
        --workspace /home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_<date>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = REPO_ROOT / "examples" / "davis_future_prediction"
PLUGINS_DIR = PACK_ROOT / "plugins"
MANIFESTS = PACK_ROOT / "data" / "manifests"

_existing = os.environ.get("SIDERIUS_PLUGIN_DIRS")
os.environ["SIDERIUS_PLUGIN_DIRS"] = (
    f"{_existing}{os.pathsep}{PLUGINS_DIR}" if _existing else str(PLUGINS_DIR)
)

from agent.schemas.model_io_contract import load_model_io_contract  # noqa: E402
from execute_tools.davis_data_path import (  # noqa: E402
    DavisScope,
    DavisTaskDataPath,
    clip_key,
    deliverable_name,
    load_davis_clips,
    truth_windows,
)
from execute_tools.evaluation_metric import (  # noqa: E402
    GlobalMseMetric,
    MetricResult,
    metric_spec_from_declaration,
)
from execute_tools.task_data_path import (  # noqa: E402
    DeliverableWriteRequest,
    EvalMaterializationParams,
    EvaluationReadRequest,
    bind_task_data_path,
)

MODEL_TYPE = "davis_reference_predictor"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data_dir", required=True, help="machine-local DAVIS root")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--device", default=None)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch_size", type=int, default=4)
    args = parser.parse_args()

    import numpy as np
    import torch

    from execute_tools.train_engine_sandbox import run_experiment_streaming
    from ml_models.models_format_sandbox import LossConfig, TrainConfig, get_config_class
    from ml_models.models_sandbox import MODEL_REGISTRY

    assert MODEL_TYPE in MODEL_REGISTRY, f"{MODEL_TYPE} missing — plugin scan failed"

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    # The registry lookup returns `type | None` and the plugin's config
    # class is only known at runtime — resolve once at this boundary.
    config_cls: Any = get_config_class(MODEL_TYPE)
    assert config_cls is not None, f"no config class registered for {MODEL_TYPE}"
    workspace = Path(args.workspace)
    sandbox_dirs = {"models": str(workspace / "models"), "results": str(workspace / "results")}
    for d in sandbox_dirs.values():
        Path(d).mkdir(parents=True, exist_ok=True)

    train_clips = load_davis_clips(MANIFESTS / "gate2_train.csv")
    val_clips = load_davis_clips(MANIFESTS / "gate2_validation.csv")
    final_clips = load_davis_clips(MANIFESTS / "gate2_final.csv")
    impl = DavisTaskDataPath()
    contract = load_model_io_contract(str(PACK_ROOT / "declared" / "model_io_contract.json"))

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    exp_id = "davis_gate2_001"
    evidence: dict = {
        "gate": "d14-3 C7 davis gate2",
        "commit": head,
        "device": device,
        "subsets": {
            "train": len(train_clips),
            "validation": len(val_clips),
            "final": len(final_clips),
        },
        "epochs": args.epochs,
        "batch_size": args.batch_size,
    }

    torch.manual_seed(11)
    t0 = time.perf_counter()
    with bind_task_data_path(impl):
        results = run_experiment_streaming(
            config_cls(batch_size=args.batch_size),
            TrainConfig(
                lr=1e-3,
                epochs=args.epochs,
                batch_size=args.batch_size,
                optimizer_type="adam",
                device=device,
            ),
            # MAE-family objective (child design §2.5, amended at C7): the
            # frozen LossConfig validates beta in [0.1, 10.0], so 0.1 — the
            # schema's MINIMUM, the most L1-like admissible setting — is used.
            # A production constraint is never widened to fit a task.
            LossConfig(loss_type="smooth_l1", beta=0.1),
            sample_set={},
            data_dir=args.data_dir,
            sandbox_dirs=sandbox_dirs,
            exp_id=exp_id,
            train_base_seed=11,
            model_io=contract,
            task_scope=DavisScope(rows=train_clips),
            task_eval_scope=DavisScope(rows=val_clips),
            validation_requested_rows=len(val_clips),
        )
    train_seconds = time.perf_counter() - t0
    assert results is not None, "engine returned None unexpectedly"
    th = results["training_history"]
    assert len(th["train_objective"]) == args.epochs
    assert len(th["validation_objective"]) == args.epochs
    assert th["validation_requested_samples"] == len(val_clips) == th["validation_samples"]
    assert th["comparability"] == "established"
    evidence["training"] = {
        "seconds": round(train_seconds, 2),
        "objective_kind": th["objective_kind"],
        "r2": th["train_objective"],
        "r3": th["validation_objective"],
        "validation_seconds": th["validation_seconds"],
        "comparability": th["comparability"],
    }
    print(
        f"[gate2] training {train_seconds:.1f}s  R2={th['train_objective']}  R3={th['validation_objective']}"
    )

    model_files = sorted(Path(sandbox_dirs["models"]).glob("*.pth"))
    assert len(model_files) == 1, model_files
    model = MODEL_REGISTRY[MODEL_TYPE](config_cls())
    model.load_state_dict(torch.load(model_files[0], weights_only=True, map_location=device))
    model.to(device).eval()

    t1 = time.perf_counter()
    ds = impl.validation_dataset(
        DavisScope(rows=final_clips), EvalMaterializationParams(data_dir=args.data_dir)
    )
    outputs = []
    baseline_outputs = []
    with torch.no_grad():
        for idx, clip in enumerate(final_clips):
            context, _target = ds[idx]
            prediction = model(context.unsqueeze(0).to(device))[0].cpu()
            outputs.append((clip, prediction))
            # The trivial baseline: repeat the last context frame.
            baseline_outputs.append(
                (clip, context[:, -1:, :, :].expand(-1, prediction.shape[1], -1, -1).clone())
            )
    infer_seconds = time.perf_counter() - t1

    write_request = DeliverableWriteRequest(
        output_dir=str(workspace), exp_id=exp_id, run_name="d14d", model_type=MODEL_TYPE
    )
    impl.write_deliverable(outputs, write_request)
    deliverable = workspace / deliverable_name(write_request)
    read_back = impl.read_evaluation_payload(
        EvaluationReadRequest(
            deliverable_dir=str(workspace), exp_id=exp_id, run_name="d14d", model_type=MODEL_TYPE
        )
    )
    # The seam returns `object` by contract; this task's codec yields
    # {clip_key: float32 ndarray}.
    assert isinstance(read_back, dict), type(read_back)
    payload: dict[str, Any] = read_back
    evidence["inference"] = {
        "seconds": round(infer_seconds, 2),
        "deliverable": deliverable.name,
        "deliverable_sha256": hashlib.sha256(deliverable.read_bytes()).hexdigest(),
        "predictions": len(payload),
    }
    print(f"[gate2] inference {infer_seconds:.1f}s  deliverable={deliverable.name}")

    spec = metric_spec_from_declaration(
        json.loads((PACK_ROOT / "declared" / "metric_mse.json").read_text(encoding="utf-8"))
    )
    truth = truth_windows(args.data_dir, final_clips)
    outcome = GlobalMseMetric(spec).evaluate(
        {0: str(deliverable)}, predictions=payload, truth=truth
    )
    assert isinstance(outcome, MetricResult), outcome
    mse = outcome.scalar
    assert mse is not None and mse >= 0.0 and np.isfinite(mse)

    baseline_payload = {clip_key(c): p.numpy() for c, p in baseline_outputs}
    baseline_outcome = GlobalMseMetric(spec).evaluate(
        {0: str(deliverable)}, predictions=baseline_payload, truth=truth
    )
    assert isinstance(baseline_outcome, MetricResult)
    evidence["metric"] = {
        "id": outcome.metric_id,
        "direction": outcome.direction,
        "mse": mse,
        "last_frame_copy_baseline_mse": baseline_outcome.scalar,
    }
    evidence["verdict"] = "PASS"
    (workspace / "gate_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        f"[gate2] mse={mse:.6f} (last-frame-copy baseline "
        f"{baseline_outcome.scalar or float('nan'):.6f})  -> PASS"
    )
    print(f"[gate2] evidence: {workspace / 'gate_evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
