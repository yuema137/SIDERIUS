"""Bounded Pets Gate-2 runner (D14-2 C6; Health stage Step 08c C5).

The full Track-B loop at the COMMITTED gate subsets — real JPEGs → the Pets
TaskDataPath → the PRODUCTION training engine (real R2+R3 through the 07a
machinery) → inference → the classification deliverable → accuracy through
the Step-06 handle → the pack's Health family on that FRESH deliverable
(the ONE shared ``scripts/_gate2_health_stage.py``, bound EXPLICITLY to
``examples/oxford_iiit_pet/declared/task_health.yaml`` — state C, never
the omitted-binding TIDMAD default). Work is bounded BEFORE anything
starts (§17.0.1): the committed ``gate2_*.csv`` manifests fix 370 train /
74 validation / 370 final-eval images; 2 epochs.

PASS is FUNCTIONAL (roadmap §17.0.1): finite CE curves accepted by the
``TrainingHistory`` validators with ``comparability`` stamped, a finite
accuracy in [0, 1] from the real metric handle on the real deliverable,
and the Health stage evaluated with its evidence persisted. Model quality
is NOT a pass condition; accuracy is recorded as an observation, and a
FAILED Health verdict on a genuinely collapsed deliverable is the stage
WORKING, not a runner failure.

Evidence: ``gate_evidence.json`` keeps every pre-08c field unchanged and
gains ONE additive ``health`` block (binding path, pinned effective-config
sha, resolved plugin identities, per-gate check ids/configs/verdicts/
actions/metrics — every selected gate present, no cross-gate
short-circuit).

Usage::

    SIDERIUS_ALLOW_LAUNCH=1 .venv/bin/python scripts/run_pets_gate2.py \
        --data_dir /home/klz/Data/OXFORD_IIIT_PET/images \
        --workspace /home/klz/Data/SIDEREIS_DATA/d14_pets_gate2_<date>

ROLE, as of Step 10 / P5+P6 C7 (Q-10-5 = B discharge)
-----------------------------------------------------
This script is an **L3 REAL-EXECUTION EVIDENCE HARNESS**. It is NOT an
alternate way a Pets task "runs", and no document should describe it that
way any more.

Its ORCHESTRATION claims — that a binding resolves, that the direction is
correct, that secondaries are observational, that Health binds state C —
were TRANSFERRED to the generic-loop closure tests
(``tests/unit/workflows/test_step10_p56_c6_three_task_closure.py``), which
drive all three tasks through the ONE production ``run_workflow``.

What SURVIVES here is what nothing cheaper owns: a distinct real-execution
failure class — real JPEG decode to tensors, the production training
engine on real data, real inference, the real deliverable codec, the real
metric handle, and the pack's Health family evaluated on a FRESH real
deliverable.

RETIREMENT DISPOSITION — Step 12 / PR-12d D8b
----------------------------------------------
The paragraph that stood here said full retirement was BLOCKED ON
**CAP-SCOPE**, because a generic loop with no task-owned scope construction
could not execute real contrast-task training, leaving these claims no
owner to move to. Both halves are now false: CAP-SCOPE landed with PR-12bc,
and ``G-12d`` drove this pack's real training, inference and scoring
children through the ONE composed production chain. Every claim above now
has a surviving owner.

The runner is nonetheless **RETAINED, not retired** — a D8b decision, not
an unfinished transfer. "Retire only if every claim has a surviving owner"
is a NECESSARY condition for retirement, never an instruction to retire
once it holds. What it still buys: this is the only harness that executes
the pack's real data path WITHOUT the composed chain, so when a real run
fails it is what separates *the pack is broken* from *the composition is
broken*. Deleting it would spend that discrimination to save nothing.

It remains an L3 evidence harness, and never a way the task runs.

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
PACK_ROOT = REPO_ROOT / "examples" / "oxford_iiit_pet"
PLUGINS_DIR = PACK_ROOT / "plugins"
MANIFESTS = PACK_ROOT / "data" / "manifests"

# The plugin mechanism scans SIDERIUS_PLUGIN_DIRS at models_sandbox import —
# extend the environment BEFORE any framework import triggers the scan.
_existing = os.environ.get("SIDERIUS_PLUGIN_DIRS")
os.environ["SIDERIUS_PLUGIN_DIRS"] = (
    f"{_existing}{os.pathsep}{PLUGINS_DIR}" if _existing else str(PLUGINS_DIR)
)

from agent.schemas.model_io_contract import load_model_io_contract  # noqa: E402
from execute_tools.evaluation_metric import (  # noqa: E402
    AccuracyMetric,
    MetricResult,
    metric_spec_from_declaration,
)
from execute_tools.pets_data_path import (  # noqa: E402
    PetsItem,
    PetsScope,
    PetsTaskDataPath,
    deliverable_name,
    load_pets_manifest,
)
from execute_tools.task_data_path import (  # noqa: E402
    DeliverableWriteRequest,
    EvalMaterializationParams,
    EvaluationReadRequest,
    bind_task_data_path,
)
from scripts._gate2_health_stage import run_health_stage  # noqa: E402

MODEL_TYPE = "pets_reference_cnn"
TASK_HEALTH_BINDING = PACK_ROOT / "declared" / "task_health.yaml"


def _rows(name: str) -> tuple[PetsItem, ...]:
    return load_pets_manifest(MANIFESTS / name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data_dir", required=True, help="machine-local extracted images root")
    parser.add_argument("--workspace", required=True, help="evidence/output directory")
    parser.add_argument("--device", default=None, help="override (default: cuda if available)")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch_size", type=int, default=32)
    args = parser.parse_args()

    import torch

    from execute_tools.train_engine_sandbox import run_experiment_streaming
    from ml_models.models_format_sandbox import LossConfig, TrainConfig, get_config_class
    from ml_models.models_sandbox import MODEL_REGISTRY

    assert MODEL_TYPE in MODEL_REGISTRY, (
        f"{MODEL_TYPE} not in MODEL_REGISTRY — SIDERIUS_PLUGIN_DIRS scan failed"
    )

    # The registry lookup returns `type | None` and the plugin's config
    # class is only known at runtime — resolve once at this boundary.
    config_cls: Any = get_config_class(MODEL_TYPE)
    assert config_cls is not None, f"no config class registered for {MODEL_TYPE}"

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    workspace = Path(args.workspace)
    sandbox_dirs = {"models": str(workspace / "models"), "results": str(workspace / "results")}
    for d in sandbox_dirs.values():
        Path(d).mkdir(parents=True, exist_ok=True)

    train_rows, val_rows, final_rows = (
        _rows("gate2_train.csv"),
        _rows("gate2_validation.csv"),
        _rows("gate2_final.csv"),
    )
    impl = PetsTaskDataPath()
    contract = load_model_io_contract(str(PACK_ROOT / "declared" / "model_io_contract.json"))

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    evidence: dict = {
        "gate": "d14-2 C6 pets gate2",
        "commit": head,
        "device": device,
        "subsets": {
            "train": len(train_rows),
            "validation": len(val_rows),
            "final": len(final_rows),
        },
        "epochs": args.epochs,
        "batch_size": args.batch_size,
    }
    exp_id = "pets_gate2_001"

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
            LossConfig(loss_type="ce"),
            sample_set={},  # legacy TIDMAD argument; the seam path ignores it
            data_dir=args.data_dir,
            sandbox_dirs=sandbox_dirs,
            exp_id=exp_id,
            train_base_seed=11,
            model_io=contract,
            task_scope=PetsScope(rows=train_rows),
            task_eval_scope=PetsScope(rows=val_rows),
            validation_requested_rows=len(val_rows),
        )
    train_seconds = time.perf_counter() - t0
    assert results is not None, (
        "engine returned None (admission rejection) — unexpected: no runtime session"
    )
    th = results["training_history"]
    assert len(th["train_objective"]) == args.epochs
    assert len(th["validation_objective"]) == args.epochs
    assert th["validation_requested_samples"] == len(val_rows) == th["validation_samples"]
    assert th["comparability"] == "established"
    evidence["training"] = {
        "seconds": round(train_seconds, 2),
        "r2": th["train_objective"],
        "r3": th["validation_objective"],
        "validation_seconds": th["validation_seconds"],
        "comparability": th["comparability"],
    }
    print(
        f"[gate2] training done in {train_seconds:.1f}s  R2={th['train_objective']}  R3={th['validation_objective']}"
    )

    # Inference over the final-eval subset through the SEAM reader.
    model_files = sorted(Path(sandbox_dirs["models"]).glob("*.pth"))
    assert len(model_files) == 1, model_files
    model = MODEL_REGISTRY[MODEL_TYPE](config_cls())
    model.load_state_dict(torch.load(model_files[0], weights_only=True, map_location=device))
    model.to(device).eval()

    t1 = time.perf_counter()
    final_scope = PetsScope(rows=final_rows)
    ds = impl.validation_dataset(final_scope, EvalMaterializationParams(data_dir=args.data_dir))
    loader = torch.utils.data.DataLoader(ds, batch_size=64, shuffle=False)
    predictions: list[tuple[str, int]] = []
    with torch.no_grad():
        offset = 0
        for batch, _targets in loader:
            logits = model(batch.to(device))
            for j, pred in enumerate(logits.argmax(dim=1).tolist()):
                predictions.append((final_rows[offset + j].image_id, int(pred)))
            offset += batch.shape[0]
    infer_seconds = time.perf_counter() - t1

    write_request = DeliverableWriteRequest(
        output_dir=str(workspace), exp_id=exp_id, run_name="d14p", model_type=MODEL_TYPE
    )
    impl.write_deliverable(predictions, write_request)
    deliverable = workspace / deliverable_name(write_request)
    read_back = impl.read_evaluation_payload(
        EvaluationReadRequest(
            deliverable_dir=str(workspace), exp_id=exp_id, run_name="d14p", model_type=MODEL_TYPE
        )
    )
    # The seam returns `object` by contract (the payload shape is task-owned);
    # this task's codec yields {image_id: class_index}.
    assert isinstance(read_back, dict), type(read_back)
    payload: dict[str, int] = read_back
    evidence["inference"] = {
        "seconds": round(infer_seconds, 2),
        "deliverable": deliverable.name,
        "deliverable_sha256": hashlib.sha256(deliverable.read_bytes()).hexdigest(),
        "predictions": len(payload),
    }
    print(f"[gate2] inference done in {infer_seconds:.1f}s  deliverable={deliverable.name}")

    # Accuracy THROUGH the Step-06 handle, spec = the pack's declaration.
    spec = metric_spec_from_declaration(
        json.loads((PACK_ROOT / "declared" / "metric_accuracy.json").read_text(encoding="utf-8"))
    )
    truth = {row.image_id: row.class_index for row in final_rows}
    outcome = AccuracyMetric(spec).evaluate({0: str(deliverable)}, predictions=payload, truth=truth)
    assert isinstance(outcome, MetricResult), outcome
    accuracy = outcome.scalar
    assert accuracy is not None and 0.0 <= accuracy <= 1.0
    evidence["metric"] = {
        "id": outcome.metric_id,
        "direction": outcome.direction,
        "accuracy": accuracy,
        "chance": 1.0 / 37.0,
    }

    # Step 08c C5: the pack's Health family on the FRESH deliverable, bound
    # EXPLICITLY (state C). A FAILED verdict on a genuinely collapsed
    # deliverable is the stage WORKING — the runner still exits 0; the Gate
    # claim is that Health classified the artifact CORRECTLY.
    evidence["health"] = run_health_stage(
        workspace=workspace,
        task_health_binding=TASK_HEALTH_BINDING,
        deliverable_path=deliverable,
        model_name=MODEL_TYPE,
        run_name="d14p",
    )
    for gate_entry in evidence["health"]["gates"]:
        print(
            f"[gate2] health {gate_entry['gate_id']}: "
            f"verdicts={gate_entry['check_verdicts']} action={gate_entry['resolved_action']}"
        )

    evidence["verdict"] = "PASS"
    (workspace / "gate_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"[gate2] accuracy={accuracy:.4f} (chance {1 / 37:.4f})  -> PASS")
    print(f"[gate2] evidence: {workspace / 'gate_evidence.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
