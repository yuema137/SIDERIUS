"""Focused contract witnesses for the synthetic masked-regression example."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from agent.skills.evaluate_vram_skill.isolated_probe import TaskProbeDataSpec
from execute_tools.task_data_path import (
    DeliverableSourceContext,
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvaluationReadRequest,
    ScopeBuildRequest,
)
from execute_tools.task_registration_scope import run_registration_scope
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "synthetic_masked_regression"
MANIFEST = REPO_ROOT / "configs" / "task_composition" / "synthetic_masked_regression.yaml"
TASK_HEALTH = PACK / "declared" / "task_health.yaml"


@pytest.fixture(autouse=True)
def _restore_health_plugin_globals():
    """Keep this multi-contract pack from selecting the next test's task."""
    from execute_tools.health_checks import _plugin_binding
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY

    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _load(name: str, relative_path: str) -> Any:
    path = PACK / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_masked_objective_uses_semantic_mask_and_refuses_shape_surrogate() -> None:
    """Defect caught: training treats ``[truth, mask]`` as an ordinary target.

    The invalid row carries a deliberately huge error but must contribute
    nothing. Removing mask selection changes the external expectation 1.0;
    accepting a zero-shaped surrogate would make the second assertion fail.
    """
    import torch

    loss_module = _load("masked_loss_under_test", "plugins/masked_mse_loss.py")
    criterion = loss_module.MaskedMseLoss(loss_module.MaskedMseConfig())
    output = torch.tensor([[2.0], [1000.0]])
    target = torch.tensor([[1.0, 1.0], [-1000.0, 0.0]])
    assert criterion(output, target).item() == 1.0
    with pytest.raises(ValueError, match=r"\[truth, mask\]"):
        criterion(output, torch.zeros(2, 1))


def test_masked_objective_declares_supported_mean_comparability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect caught: a descriptive reduction token is loader-undeclared.

    The H100 preflight exposed this distinction: the objective computes a
    masked mean, but the plugin contract must use the framework's supported
    `mean` normalization vocabulary for cross-epoch comparability.
    """
    from execute_tools.training_history import stamp_comparability
    from ml_models.loss_models_sandbox import _load_custom_loss
    from ml_models.loss_plugin_loader import LOSS_REDUCTION_REGISTRY
    from ml_models.models_format_sandbox import LossConfig

    monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(PACK / "plugins"))
    monkeypatch.delitem(LOSS_REDUCTION_REGISTRY, "synthetic_masked_mse", raising=False)
    _load_custom_loss("synthetic_masked_mse")
    assert LOSS_REDUCTION_REGISTRY["synthetic_masked_mse"] == "mean"
    assert stamp_comparability(
        LossConfig(loss_type="custom", loss_name="synthetic_masked_mse")
    ) == ("established", None)


def test_production_training_engine_consumes_masked_supervision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Defect caught: the production trainer bypasses the task objective.

    One bounded CPU optimizer step must consume the task's real ``[truth,
    mask]`` supervision through ``run_experiment_streaming``. A shape-only
    target, a built-in loss fallback, or a bypass of the composed data path
    makes the engine raise before it can persist the trained model.
    """
    import math
    from types import SimpleNamespace

    import torch

    import execute_tools.train_engine_sandbox as train_engine
    from ml_models.loss_models_sandbox import (
        LOSS_CONFIG_REGISTRY,
        LOSS_REGISTRY,
        register_loss_in_memory,
    )
    from ml_models.loss_plugin_loader import (
        LOSS_REDUCTION_REGISTRY,
        LOSS_TARGET_DTYPE_REGISTRY,
    )
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY, LossConfig, TrainConfig
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY, register_model_in_memory

    task_module = _load("masked_task_training", "plugins/_masked_task.py")
    bundle = task_module.materialize_run_bundle(tmp_path / "bundle")
    model_registry = dict(MODEL_REGISTRY)
    loss_registry = dict(LOSS_REGISTRY)
    loss_config_registry = dict(LOSS_CONFIG_REGISTRY)
    loss_dtype_registry = dict(LOSS_TARGET_DTYPE_REGISTRY)
    loss_reduction_registry = dict(LOSS_REDUCTION_REGISTRY)
    plugin_config_registry = dict(PLUGIN_CONFIG_REGISTRY)
    plugin_output_registry = dict(PLUGIN_OUTPUT_TYPE_REGISTRY)
    try:
        assert (
            register_model_in_memory(str(PACK / "plugins" / "masked_reference_mlp.py"))
            == "masked_reference_mlp"
        )
        assert (
            register_loss_in_memory(str(PACK / "plugins" / "masked_mse_loss.py"))
            == "synthetic_masked_mse"
        )
        with run_registration_scope():
            composition = compose_run_task_bindings(str(MANIFEST))
            scope = composition.task_data_path.build_training_scope(
                ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
            )
            sandbox_dirs = {
                "models": str(tmp_path / "models"),
                "results": str(tmp_path / "results"),
            }
            for directory in sandbox_dirs.values():
                Path(directory).mkdir()
            torch.manual_seed(17)
            with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
                result = train_engine.run_experiment_streaming(
                    SimpleNamespace(
                        model_type="masked_reference_mlp",
                        segmentation_size=3,
                        hidden_dim=8,
                    ),
                    TrainConfig(
                        lr=1e-3,
                        epochs=1,
                        batch_size=len(scope.rows),
                        optimizer_type="adam",
                        device="cpu",
                    ),
                    LossConfig(loss_type="custom", loss_name="synthetic_masked_mse"),
                    sample_set={},
                    data_dir=bundle["data_dir"],
                    sandbox_dirs=sandbox_dirs,
                    exp_id="masked_training_witness",
                    train_base_seed=17,
                    model_io=composition.forward_contract.model_io,
                    profile=composition.dataset_profile,
                    task_scope=scope,
                )
        assert result is not None
        assert len(result["loss_history"]) == 1
        assert math.isfinite(result["loss_history"][0])
        assert result["training_history"]["objective_kind"] == "custom"
        assert len(list(Path(sandbox_dirs["models"]).glob("*.pth"))) == 1
    finally:
        MODEL_REGISTRY.clear()
        MODEL_REGISTRY.update(model_registry)
        LOSS_REGISTRY.clear()
        LOSS_REGISTRY.update(loss_registry)
        LOSS_CONFIG_REGISTRY.clear()
        LOSS_CONFIG_REGISTRY.update(loss_config_registry)
        LOSS_TARGET_DTYPE_REGISTRY.clear()
        LOSS_TARGET_DTYPE_REGISTRY.update(loss_dtype_registry)
        LOSS_REDUCTION_REGISTRY.clear()
        LOSS_REDUCTION_REGISTRY.update(loss_reduction_registry)
        PLUGIN_CONFIG_REGISTRY.clear()
        PLUGIN_CONFIG_REGISTRY.update(plugin_config_registry)
        PLUGIN_OUTPUT_TYPE_REGISTRY.clear()
        PLUGIN_OUTPUT_TYPE_REGISTRY.update(plugin_output_registry)


def test_composed_inference_persists_source_aligned_masked_scores(tmp_path: Path) -> None:
    """Defect caught: source context, masks, or secondary metrics are dropped.

    A zero regressor has externally pinned scores on the seeded evaluation
    shard. Missing source transport refuses at the writer; ordering drift,
    including invalid rows, or selecting the secondary changes a literal.
    """
    import torch

    from execute_tools.generic_inference import run_generic_inference

    task_module = _load("masked_task_materializer", "plugins/_masked_task.py")
    bundle = task_module.materialize_run_bundle(tmp_path / "bundle")

    class ZeroRegressor(torch.nn.Module):
        def forward(self, inputs: torch.Tensor) -> torch.Tensor:
            return torch.zeros((len(inputs), 1), dtype=inputs.dtype)

    with run_registration_scope():
        composition = compose_run_task_bindings(str(MANIFEST))
        assert composition.metric.spec.id == "masked_mse"
        assert composition.metric.spec.direction == "lower"
        assert [metric.spec.id for metric in composition.secondary_metrics] == ["masked_mae"]
        assert composition.objective is not None
        assert composition.objective.loss_type == "custom"
        assert composition.objective.loss_name == "synthetic_masked_mse"
        with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
            scope = composition.task_data_path.build_eval_scope(
                ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
            )
            output_dir = tmp_path / "outputs"
            identity = {
                "exp_id": "exp1",
                "run_name": "masked",
                "model_type": "zero_regressor",
            }
            outcome = run_generic_inference(
                data_path=composition.task_data_path,
                task_scope=scope,
                model=ZeroRegressor(),
                device=torch.device("cpu"),
                data_dir=bundle["data_dir"],
                batch_size=5,
                write_request=DeliverableWriteRequest(output_dir=str(output_dir), **identity),
            )
            artifact = output_dir / outcome.deliverable_name
            payload = composition.task_data_path.read_evaluation_payload(
                task_module.EvaluationReadRequest(deliverable_dir=str(output_dir), **identity)
            )
            primary = composition.metric.evaluate(
                {0: str(artifact)},
                evaluation_payload=payload,
                task_scope=scope,
                data_dir=bundle["data_dir"],
            )
            secondary = composition.secondary_metrics[0].evaluate(
                {0: str(artifact)},
                evaluation_payload=payload,
                task_scope=scope,
                data_dir=bundle["data_dir"],
            )
            assert outcome.samples == 24
            assert outcome.batches == 5
            assert artifact.is_file()
            assert sum(bool(row["valid"]) for row in payload.values()) == 18
            assert primary.scalar == pytest.approx(1.2241640090942383)
            assert secondary.scalar == pytest.approx(0.8717526793479919)


def test_training_and_evaluation_scopes_are_disjoint(tmp_path: Path) -> None:
    """Defect caught: the held-out shard is accidentally admitted to training."""
    task_module = _load("masked_task_split", "plugins/_masked_task.py")
    implementation = task_module.SyntheticMaskedTaskDataPath()
    request = ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
    train = implementation.build_training_scope(request)
    evaluation = implementation.build_eval_scope(request)
    train_ids = {row.sample_id for row in train.rows}
    evaluation_ids = {row.sample_id for row in evaluation.rows}
    assert len(train_ids) == 48
    assert len(evaluation_ids) == 24
    assert train_ids.isdisjoint(evaluation_ids)


def test_task_health_fails_constant_and_passes_varied_task_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Defect caught: Health is detached from the task codec or mask view.

    Both controls are written by the task's production codec. A constant
    valid prediction stream must invalidate the round; a fixed varied stream
    must pass. Reading invalid rows or another artifact changes the verdict.
    """
    import torch

    from execute_tools.health_checks import _plugin_binding, runner
    from execute_tools.health_checks.config import load_composed_health_config
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
    from execute_tools.health_checks.schemas import CheckVerdict, HealthCheckContext

    task_module = _load("masked_task_health", "plugins/_masked_task.py")
    bundle = task_module.materialize_run_bundle(tmp_path / "bundle")
    registry_snapshot = dict(_REGISTRY)
    provider_snapshot = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        health_config, _task_config, _plugins = load_composed_health_config(None, str(TASK_HEALTH))
        monkeypatch.setattr(
            runner, "load_health_gates_config", lambda *args, **kwargs: health_config
        )
        with run_registration_scope():
            composition = compose_run_task_bindings(str(MANIFEST))
            scope = composition.task_data_path.build_eval_scope(
                ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
            )
            source = DeliverableSourceContext(
                data_dir=bundle["data_dir"], sample_count=len(scope.rows)
            )

            def write(control: str, outputs: list[torch.Tensor]) -> Path:
                output_dir = tmp_path / control
                request = DeliverableWriteRequest(
                    output_dir=str(output_dir),
                    exp_id=control,
                    run_name="health",
                    model_type="control",
                    task_scope=scope,
                    source_context=source,
                )
                composition.task_data_path.write_deliverable(outputs, request)
                return output_dir

            def reader(control: str, output_dir: Path):
                request = EvaluationReadRequest(
                    deliverable_dir=str(output_dir),
                    exp_id=control,
                    run_name="health",
                    model_type="control",
                )
                return lambda: composition.task_data_path.read_evaluation_payload(request)

            constant = write("constant", [torch.tensor([0.0])] * len(scope.rows))
            varied = write(
                "varied",
                [torch.tensor([float(index % 3)]) for index in range(len(scope.rows))],
            )
            constant_result = runner.evaluate_gate(
                "synthetic_masked_prediction_dispersion",
                HealthCheckContext(
                    model_name="control",
                    run_name="health",
                    round_index=1,
                    evaluation_payload_fn=reader("constant", constant),
                ),
            )
            varied_result = runner.evaluate_gate(
                "synthetic_masked_prediction_dispersion",
                HealthCheckContext(
                    model_name="control",
                    run_name="health",
                    round_index=1,
                    evaluation_payload_fn=reader("varied", varied),
                ),
            )
            assert constant_result.check_results[0].verdict is CheckVerdict.FAILED
            assert constant_result.action.value == "invalidate_round"
            assert constant_result.check_results[0].metrics["dispersion"] == 0.0
            assert varied_result.check_results[0].verdict is CheckVerdict.PASSED
            assert varied_result.passed is True
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry_snapshot)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(provider_snapshot)
        _plugin_binding.reset_run_scope()


def test_resource_worker_accepts_a_task_valid_batch_and_refuses_an_oversized_one(
    tmp_path: Path,
) -> None:
    """Defect caught: resource probing replaces semantic targets with zeros.

    The isolated worker boundary must return `[B,3]` inputs and the real
    `[B,2] = [truth, mask]` supervision. Batch 8 is admitted by the scope;
    batch 64 is refused because 48 training rows cannot form one full batch.
    """
    from agent.skills.evaluate_vram_skill.preflight_worker_main import _task_probe_batch

    task_module = _load("masked_task_resource", "plugins/_masked_task.py")
    bundle = task_module.materialize_run_bundle(tmp_path / "bundle")
    with run_registration_scope():
        composition = compose_run_task_bindings(str(MANIFEST))
        scope = composition.task_data_path.build_training_scope(
            ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
        )
        payload = composition.task_data_path.serialize_scope(scope)
        spec = TaskProbeDataSpec(
            manifest_path=str(MANIFEST),
            semantic_fingerprint=composition.semantic_fingerprint,
            training_scope_payload=payload,
            sampling=EpochSamplingParams(data_dir=bundle["data_dir"], epoch_seed=7),
        )
    inputs, supervision = _task_probe_batch(spec.model_dump(), batch_size=8)
    assert tuple(inputs.shape) == (8, 3)
    assert tuple(supervision.shape) == (8, 2)
    assert set(supervision[:, 1].tolist()) == {0.0, 1.0}
    with pytest.raises(ValueError, match="cannot produce one full resource probe batch of size 64"):
        _task_probe_batch(spec.model_dump(), batch_size=64)


def test_h100_receipt_preserves_the_matched_admission_contrast() -> None:
    """Defect caught: GPU evidence loses identity or conflates the verdicts.

    The persisted receipt must keep one code/composition identity and two
    controls with one measured value. Replacing either control with an
    inconclusive result or changing the measured candidate breaks a literal.
    """
    import json

    receipt = json.loads(
        (PACK / "expected" / "h100_resource_qualification.json").read_text(encoding="utf-8")
    )
    assert receipt["repository_sha"] == "1acfe3bb5b2a62b6a8ab8d6b9c82c967d841c8b3"
    assert receipt["hardware"]["device_name"] == "NVIDIA H100 80GB HBM3"
    assert receipt["candidate"]["supervision_shape"] == [8, 2]
    assert receipt["measurement"] == {
        "estimated_gb": 0.229,
        "admitted_control": {
            "operator_cap_gb": 1.0,
            "outcome": "COMPLETED_MEASUREMENT",
            "feasible": True,
        },
        "refused_control": {
            "operator_cap_gb": 0.001,
            "outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP",
            "feasible": False,
        },
    }


def test_primary_masked_mse_orders_records_when_secondary_mae_disagrees(
    tmp_path: Path,
) -> None:
    """Defect caught: an observational secondary changes champion selection.

    Candidate A has the better MAE but worse MSE; candidate B has the better
    declared primary MSE but worse MAE. Persisted production ranking must pick
    B. Reading `secondary_metric_results` as an ordering input picks A and
    fails this test.
    """
    import math

    from execute_tools.persisted_ranking import best_by_declared_metric

    with run_registration_scope():
        composition = compose_run_task_bindings(str(MANIFEST))
    artifact = tmp_path / "present.json"
    artifact.write_text("{}", encoding="utf-8")

    def evaluate(errors: list[float]) -> tuple[float, float]:
        payload = {
            f"row_{index}": {"prediction": error, "target": 0.0, "valid": True}
            for index, error in enumerate(errors)
        }
        primary = composition.metric.evaluate(
            {0: str(artifact)},
            evaluation_payload=payload,
            task_scope=object(),
        )
        secondary = composition.secondary_metrics[0].evaluate(
            {0: str(artifact)},
            evaluation_payload=payload,
            task_scope=object(),
        )
        assert type(primary).__name__ == type(secondary).__name__ == "MetricResult"
        return primary.scalar, secondary.scalar

    a_primary, a_secondary = evaluate([0.0, 0.0, 3.0])
    b_primary, b_secondary = evaluate([math.sqrt(2.0)] * 3)
    assert a_primary == 3.0
    assert a_secondary == 1.0
    assert b_primary == pytest.approx(2.0)
    assert b_secondary == pytest.approx(math.sqrt(2.0))
    assert a_primary > b_primary
    assert a_secondary < b_secondary

    def record(exp_id: str, primary: float, secondary: float) -> dict[str, Any]:
        return {
            "exp_id": exp_id,
            "status": "success",
            "denoising_score": primary,
            "metric_result": {
                "metric_id": "masked_mse",
                "direction": "lower",
                "scalar": primary,
            },
            "secondary_metric_results": [
                {
                    "metric_id": "masked_mae",
                    "direction": "lower",
                    "scalar": secondary,
                }
            ],
        }

    best = best_by_declared_metric(
        [
            record("candidate_a", a_primary, a_secondary),
            record("candidate_b", b_primary, b_secondary),
        ],
        context="synthetic masked-regression example",
    )
    assert best is not None
    assert best["exp_id"] == "candidate_b"


def test_composed_manifest_traverses_the_production_workflow(tmp_path: Path) -> None:
    """Defect caught: the example composes but cannot enter the agent loop.

    This is orchestration evidence only: typed deterministic substitutes stand
    in for the five agents, while the production ``run_workflow`` owns their
    ordering and handoffs. Training, scoring, Health, and GPU execution are
    proven by separate real witnesses in this module.
    """
    from unittest.mock import patch

    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
    from tests.unit.workflows.test_model_exploration import (
        _make_implementor_output,
        _make_interpretation_output,
        _make_proposal_output,
        _make_tune_output,
        _make_validator_output,
    )
    from workflows.model_exploration import run_workflow
    from workflows.run_config import WorkflowLaunchConfig

    with run_registration_scope():
        composition = compose_run_task_bindings(str(MANIFEST))

    model_type = "masked_reference_mlp"
    seed_dir = tmp_path / "data" / model_type / "seed" / "agent"
    seed_dir.mkdir(parents=True)
    (seed_dir / "run_output_seed_agent.json").write_text(
        HyperparamTuningOutput(
            run_name="seed",
            model_type=model_type,
            file_index=0,
            status="completed",
            task_composition_fingerprint=composition.semantic_fingerprint,
            completed_rounds=1,
            total_attempts=1,
            best_exp_id="masked_seed_001",
            best_denoising_score=3.0,
            best_formal_denoising_score=3.0,
            best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
            all_records=[
                {
                    "exp_id": "masked_seed_001",
                    "status": "success",
                    "model_type": model_type,
                    "timestamp": "2026-01-01 00:00:00",
                    "file_index": 0,
                    "params": {
                        "model_config": {},
                        "train_config": {},
                        "loss_config": {},
                    },
                    "results": {"denoising_score": 3.0},
                    "denoising_score": 3.0,
                }
            ],
            started_at="2026-01-01 00:00:00",
            finished_at="2026-01-01 00:01:00",
            metric_spec=composition.metric.spec,
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )

    calls: list[str] = []
    seen: dict[str, Any] = {}
    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as interpret,
        patch("workflows.model_exploration.MLModelProposalAgent") as propose,
        patch("workflows.model_exploration.MLModelImplementor") as implement,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as validate,
        patch("workflows.model_exploration.HyperparamTuningAgent") as tune,
    ):

        def interpret_run(inputs: Any) -> Any:
            calls.append("interpret")
            seen["interpret"] = inputs
            return _make_interpretation_output()

        def propose_run(inputs: Any) -> Any:
            calls.append("propose")
            return _make_proposal_output("masked_candidate_1")

        def implement_run(inputs: Any) -> Any:
            calls.append("implement")
            return _make_implementor_output()

        def validate_run(inputs: Any) -> Any:
            calls.append("validate")
            return _make_validator_output(passed=True)

        def tune_run(inputs: Any) -> Any:
            calls.append("tune")
            seen["tune"] = inputs
            output = _make_tune_output(model_type=inputs.model_type, score=2.0)
            output.metric_spec = composition.metric.spec
            return output

        interpret.return_value.run.side_effect = interpret_run
        propose.return_value.run.side_effect = propose_run
        implement.return_value.run.side_effect = implement_run
        validate.return_value.run.side_effect = validate_run
        tune.return_value.run.side_effect = tune_run

        with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
            results = run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=[model_type],
                    source_run_name="seed",
                    max_iterations=1,
                ),
                workspace=str(tmp_path / "workspace"),
                run_name="synthetic_masked_workflow",
                task_composition=composition,
            )

    assert len(results) == 1
    assert calls == ["interpret", "propose", "implement", "validate", "tune"]
    assert (seen["interpret"].metric_spec.id, seen["interpret"].metric_spec.direction) == (
        "masked_mse",
        "lower",
    )
    assert seen["tune"].task_composition_ref is not None
    assert seen["tune"].task_composition_ref.semantic_fingerprint == (
        composition.semantic_fingerprint
    )


def test_package_identity_is_checkout_portable_and_edits_refuse_resume(tmp_path: Path) -> None:
    """Defect caught: absolute checkout paths enter run identity or edits do not.

    Two byte-identical copies at unrelated roots must derive one fingerprint
    and validate one workspace lock. Editing the declared metric implementation
    in the second copy must move that identity and refuse the same workspace.
    Fresh interpreters mirror separate chain iterations and avoid registry
    state becoming the accidental oracle.
    """
    from core.run_invariants import RUN_INVARIANTS_BASENAME

    def copy_package(root: Path) -> Path:
        destination = root / "examples" / "synthetic_masked_regression"
        destination.parent.mkdir(parents=True)
        shutil.copytree(PACK, destination)
        manifest = root / "configs" / "task_composition" / MANIFEST.name
        manifest.parent.mkdir(parents=True)
        shutil.copy2(MANIFEST, manifest)
        return manifest

    def preflight(manifest: Path, workspace: Path) -> subprocess.CompletedProcess[str]:
        script = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(REPO_ROOT)!r})

            from core.run_invariants import RunInvariants, RunInvariantsViolation, ensure_run_invariants
            from workflows.task_composition import compose_run_task_bindings

            composition = compose_run_task_bindings({str(manifest)!r})
            print("FINGERPRINT", composition.semantic_fingerprint)
            invariants = RunInvariants(
                resolved_data_scope=[0, 1, 2],
                health_gate_enabled=False,
                health_config_sha256=None,
                runtime_estimator_identity="portable-example-estimator-v1",
                runtime_policy_identity="portable-example-policy-v1",
                task_composition_fingerprint=composition.semantic_fingerprint,
            )
            try:
                print("OUTCOME", ensure_run_invariants({str(workspace)!r}, invariants))
            except RunInvariantsViolation as exc:
                print("REFUSED")
                print(exc)
                raise SystemExit(7) from None
            """
        )
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=manifest.parents[2],
            timeout=60,
        )

    def fingerprint(result: subprocess.CompletedProcess[str]) -> str:
        return next(
            line.split(" ", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("FINGERPRINT ")
        )

    manifest_a = copy_package(tmp_path / "checkout_a")
    manifest_b = copy_package(tmp_path / "unrelated" / "checkout_b")
    workspace = tmp_path / "persisted_workspace"

    created = preflight(manifest_a, workspace)
    assert created.returncode == 0, created.stdout + created.stderr
    assert "OUTCOME created" in created.stdout
    resumed = preflight(manifest_b, workspace)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert "OUTCOME validated" in resumed.stdout
    assert fingerprint(created) == fingerprint(resumed)
    lock_before = (workspace / RUN_INVARIANTS_BASENAME).read_bytes()

    metric_plugin = (
        manifest_b.parents[2]
        / "examples"
        / "synthetic_masked_regression"
        / "plugins"
        / "_masked_metrics.py"
    )
    metric_plugin.write_text(
        metric_plugin.read_text(encoding="utf-8") + "\n# semantic package edit\n",
        encoding="utf-8",
    )
    refused = preflight(manifest_b, workspace)
    assert refused.returncode == 7, refused.stdout + refused.stderr
    assert fingerprint(refused) != fingerprint(created)
    assert "REFUSED" in refused.stdout
    assert "task_composition_fingerprint" in refused.stdout
    assert (workspace / RUN_INVARIANTS_BASENAME).read_bytes() == lock_before


def test_interpretation_node_runs_standalone_through_its_typed_contract() -> None:
    """Defect caught: a node can run only when hidden workflow state exists.

    The cold-start branch is deliberately deterministic and must not touch an
    LLM. It still enters through the public ``run(InterpretationInput)``
    contract and returns the declared typed output.
    """
    from unittest.mock import MagicMock

    from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
    from nodes.result_interpretation_agent.result_interpretation_agent import (
        ResultInterpretationAgent,
    )

    bridge = MagicMock()
    bridge.generate.side_effect = AssertionError("standalone cold start must not call an LLM")
    bridge.generate_text.side_effect = AssertionError("standalone cold start must not call an LLM")
    agent = ResultInterpretationAgent(bridge_factory=lambda **_kwargs: bridge)

    output = agent.run(InterpretationInput(summaries=[], cold_start=True))

    assert isinstance(output, InterpretationOutput)
    assert output.cold_start is True
    assert output.total_experiments == 0
    assert "no prior experimental evidence" in output.take_home_message.lower()
    bridge.generate.assert_not_called()
    bridge.generate_text.assert_not_called()
