"""Manual, CPU-only installed-package witness; run from a neutral working directory.

This is real child execution through TidmadSandbox, with the shipped synthetic
pack and preauthored model/loss files staged as workspace plugins. It makes no
LLM, GPU, campaign, or scientific-quality claim. Bound the invocation with
``timeout 120``, use Python ``-I`` to exclude the test driver's directory,
and pin OMP/OPENBLAS/MKL threads to at most two.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

PACKAGES = (
    "agent",
    "nodes",
    "workflows",
    "core",
    "execute_tools",
    "ml_models",
    "dashboard",
    "tools",
)


def installed_origins(expected_root: Path) -> dict[str, list[str]]:
    """Refuse a missing package or an import from a different installation."""
    origins = {}
    for name in PACKAGES:
        locations = list(importlib.import_module(name).__path__)
        assert locations and all(
            Path(p).resolve().is_relative_to(expected_root) for p in locations
        ), (name, locations, expected_root)
        origins[name] = locations
    return origins


def read_resources(workspace: Path) -> dict[str, str]:
    """Exercise actual resource readers, including the ASGI static-file route."""
    from fastapi.testclient import TestClient

    from agent.prompt_templates import literature_review, proposal
    from agent.tools_schema import load_skills_from_library
    from core.layout import package_root
    from dashboard.main import create_app
    from dashboard.settings import DashboardSettings
    from ml_models.model_descriptions import get_model_description
    from tools.ci.weights import load_weights
    from tools.claude_hooks.context_state import template_path
    from workflows.model_exploration import _load_vocab_seed

    root = package_root()
    resources = {}
    for family, reader in (("proposal", proposal), ("literature_review", literature_review)):
        for path in (root / "agent/prompt_templates" / family).glob("*.md"):
            resources[path.relative_to(root).as_posix()] = reader.load_prompt(path.name)
    assert len(resources) == 12, "prompt templates missing from the installation"
    assert len(_load_vocab_seed()) == 21, "vocabulary seed missing or unreadable"
    assert len(load_skills_from_library(str(root / "agent/skills"))) == 7
    for model in ("fcnet", "gated_fno", "punet", "transformer", "wavenet"):
        resources[f"ml_models/{model}/description.md"] = get_model_description(model)
    assert load_weights(), "CI weights silently fell back to an empty inventory"
    resources[template_path().relative_to(root).as_posix()] = template_path().read_text()
    settings = DashboardSettings.model_validate(
        {"data_source": {"local": {"root_data_dir": str(workspace)}}}
    )
    with TestClient(create_app(settings)) as client:
        for name in ("index.html", "app.js", "style.css"):
            response = client.get(f"/static/{name}")
            assert response.status_code == 200, (name, response.status_code)
            resources[f"dashboard/static/{name}"] = response.text
    return {name: hashlib.sha256(text.encode()).hexdigest() for name, text in resources.items()}


def prepare_inputs(checkout: Path, workspace: Path) -> Path:
    """Copy only declared synthetic inputs; keep every run artifact external."""
    import yaml

    inputs = workspace / "inputs"
    pack = inputs / "examples/synthetic_masked_regression"
    shutil.copytree(
        checkout / "examples/synthetic_masked_regression",
        pack,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    manifest = inputs / "configs/task_composition/synthetic_masked_regression.yaml"
    manifest.parent.mkdir(parents=True)
    config = yaml.safe_load((checkout / "configs/task_composition" / manifest.name).read_text())
    for kind, filename in (
        ("plugins", "masked_reference_mlp.py"),
        ("losses", "masked_mse_loss.py"),
    ):
        directory = workspace / kind / "installed"
        directory.mkdir(parents=True)
        shutil.copyfile(pack / "plugins" / filename, directory / filename)
    config["model_plugins"]["dir"] = str(workspace / "plugins/installed")
    config["loss_plugins"]["dir"] = str(workspace / "losses/installed")
    config["objective"]["implementation"]["file"] = str(
        workspace / "losses/installed/masked_mse_loss.py"
    )
    manifest.write_text(yaml.safe_dump(config))
    shutil.copyfile(checkout / "configs/health_checks.yaml", inputs / "health_policy.yaml")
    return manifest


def execute_lifecycle(manifest: Path, workspace: Path) -> dict:
    """Run the installed trainer, inferencer, scorer, Health adapter and recorder."""
    from agent.schemas.hyperparam_tuning import ExperimentRecord
    from core.sandbox_executor import TidmadSandbox
    from execute_tools.health_checks.config import materialize_effective_config
    from execute_tools.health_checks.evaluation import evaluate_and_persist_health_gates
    from execute_tools.health_checks.schemas import HealthCheckContext
    from execute_tools.task_data_path import (
        EvaluationReadRequest,
        ScopeBuildRequest,
        resolve_task_scope_capability,
    )
    from ml_models.loss_models_sandbox import register_loss_in_memory
    from ml_models.plugin_loader import register_model_in_memory
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    model = "masked_reference_mlp"
    assert (
        register_model_in_memory(str(workspace / "plugins/installed/masked_reference_mlp.py"))
        == model
    )
    assert (
        register_loss_in_memory(str(workspace / "losses/installed/masked_mse_loss.py"))
        == "synthetic_masked_mse"
    )
    composition = compose_run_task_bindings(str(manifest))
    task = composition.task_data_path
    # The declared task's own generator, not a test transcription of its data.
    task_module = sys.modules[type(task).__module__]
    bundle = task_module.materialize_run_bundle(workspace / "synthetic")
    capability = resolve_task_scope_capability(task)
    request = ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
    scopes = SimpleNamespace(
        training=capability.build_training_scope(request),
        evaluation=capability.build_eval_scope(request),
    )
    m_cfg = {"model_type": model, "segmentation_size": 3, "hidden_dim": 8}
    t_cfg = {"lr": 1e-3, "epochs": 1, "batch_size": 48, "optimizer_type": "adam", "device": "cpu"}
    l_cfg = {"loss_type": "custom", "loss_name": "synthetic_masked_mse"}
    with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
        sandbox = TidmadSandbox(
            workspace=str(workspace), run_name="installed", file_index=0, progress_bar=True
        )
        trained = sandbox.execute_training(
            "one_step",
            "installed",
            model,
            m_cfg,
            t_cfg,
            l_cfg,
            train_base_seed=17,
            task_scopes=scopes,
        )
        assert trained["status"] == "success", trained
        assert len(trained["results"]["loss_history"]) == 1, trained
        inferred = sandbox.execute_inference(
            "one_step", "installed", model, m_cfg, l_cfg, inference_batch=8, task_scopes=scopes
        )
        assert inferred["status"] == "success", inferred
        scored = sandbox.execute_scoring(
            "one_step", "installed", model, m_cfg, t_cfg, l_cfg, task_scopes=scopes
        )
        assert scored["status"] == "success", scored
        results = scored["results"]
        assert results["metric_result"]["metric_id"] == "masked_mse", results
        assert composition.metric.spec.direction == "lower"
        evaluation_request = EvaluationReadRequest(
            deliverable_dir=str(workspace),
            model_type=model,
            run_name="installed",
            exp_id="one_step",
        )
        payload = task.read_evaluation_payload(evaluation_request)
        assert isinstance(payload, dict) and len(payload) == 24
        valid = [r for r in payload.values() if r["valid"]]
        assert len(valid) == 18
        expected = sum((r["prediction"] - r["target"]) ** 2 for r in valid) / 18
        assert math.isclose(results["metric_result"]["scalar"], expected, rel_tol=1e-6)
        (checkpoint,) = Path(sandbox.dirs["models"]).glob("*.pth")
        effective, health_hash = materialize_effective_config(
            str(workspace / "inputs/health_policy.yaml"),
            None,
            str(workspace),
            task_health_binding=str(
                workspace / "inputs/examples/synthetic_masked_regression/declared/task_health.yaml"
            ),
        )
        _, persisted, action = evaluate_and_persist_health_gates(
            HealthCheckContext(
                model_name=model,
                run_name="installed",
                round_index=1,
                checkpoint_path=str(checkpoint),
                evaluation_payload_fn=lambda: task.read_evaluation_payload(evaluation_request),
            ),
            config_path=effective,
        )
        assert (
            len(persisted) == 1
            and persisted[0].gate_name == "synthetic_masked_prediction_dispersion"
        )
        assert persisted[0].execution_status in {"passed", "failed"}, persisted
        mean = math.fsum(row["prediction"] for row in valid) / 18
        dispersion = math.sqrt(math.fsum((row["prediction"] - mean) ** 2 for row in valid) / 18)
        assert persisted[0].check_passed == (dispersion >= 0.1), persisted
        record = ExperimentRecord(
            exp_id="one_step",
            model_type=model,
            timestamp=datetime.now(UTC).isoformat(),
            file_index=0,
            status="success" if action.value == "continue" else "failed_mode_collapse",
            params={"model_config": m_cfg, "train_config": t_cfg, "loss_config": l_cfg},
            denoising_score=results["metric_result"]["scalar"],
            metric_result=results["metric_result"],
            file_vector=results["file_vector"],
            health_gate_results=persisted,
        )
        sandbox.save_record(record.model_dump(mode="json"))
        restored = ExperimentRecord.model_validate(sandbox.get_summary()[0])
        assert restored.health_gate_results == persisted
        return {
            "metric": results["metric_result"],
            "independent_mse": expected,
            "health": [r.model_dump(mode="json") for r in persisted],
            "health_config_sha256": health_hash,
            "checkpoint": str(checkpoint),
            "record_status": restored.status,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-root", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--resources-only", action="store_true")
    args = parser.parse_args()
    assert "PYTHONPATH" not in os.environ
    assert not Path.cwd().is_relative_to(args.checkout)
    args.workspace.mkdir(parents=True, exist_ok=False)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(str(args.workspace))
    sys.dont_write_bytecode = True
    started = time.monotonic()
    origins = installed_origins(args.expected_root.resolve())
    from core.layout import checkout_root

    checkout = checkout_root()
    assert checkout == (args.checkout if args.expected_root == args.checkout / "src" else None)
    resources = read_resources(args.workspace)
    commands = []

    def observe(event, values):
        if event == "subprocess.Popen":
            executable, argv, cwd, env = values
            if len(argv) > 1 and str(argv[1]).endswith(".py"):
                assert Path(argv[1]).resolve().is_relative_to(args.expected_root)
                assert executable == sys.executable
                assert env is not None and "PYTHONPATH" not in env
                commands.append(
                    {
                        "argv": argv,
                        "cwd": cwd,
                        "plugins": {
                            key: env.get(key)
                            for key in ("SIDERIUS_PLUGIN_DIRS", "SIDERIUS_LOSS_DIRS")
                        },
                    }
                )

    sys.addaudithook(observe)
    result = (
        {}
        if args.resources_only
        else execute_lifecycle(prepare_inputs(args.checkout, args.workspace), args.workspace)
    )
    if not args.resources_only:
        assert [Path(c["argv"][1]).name for c in commands] == [
            "train_engine_sandbox.py",
            "inference_single.py",
            "denoising_score_single.py",
        ]
    receipt = {
        "interpreter": sys.executable,
        "checkout": str(checkout) if checkout else None,
        "origins": origins,
        "resources": resources,
        "commands": commands,
        "result": result,
        "seconds": time.monotonic() - started,
    }
    (args.workspace / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
