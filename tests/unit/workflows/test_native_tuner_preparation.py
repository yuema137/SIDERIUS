"""Pre-extraction production-input oracle (base 4131a74df19ea7c627b39cb0d766fa13cc7b874d).

Full payload equality catches dropped/swapped forwarding that schema validation
cannot detect. Expectations were captured from run_workflow before extraction;
only the pytest temporary root is normalized. The source-derived composition
fingerprint is checked separately against the real binding and persisted lock.
Planner assembly and verifier source digests are likewise checked against their
current declared owners and persisted lock; frozen baseline digests stay pinned.
Every other payload field is compared exactly. This checks input forwarding,
not equivalence of live model outputs or scientific artifacts. Node effects use
existing seams.
"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.schemas.parameter_rules import ParameterRules
from core.run_invariants import RunInvariants
from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
from execute_tools.dataset_config import DataScope
from tests.unit.workflows import test_model_exploration as workflow_tests
from tests.unit.workflows.test_model_exploration import workflow_env as workflow_env
from workflows.llm_config import NodeLLMConfig, TunerLLMConfig, WorkflowLLMConfig
from workflows.run_config import WorkflowLaunchConfig

ORACLE = Path(__file__).resolve().parents[2] / "fixtures" / "native_tuner_input"


def _nondefault_controls():
    return dict(
        max_rounds=7,
        file_index=1,
        healthgate_mode="observe_only",
        result_authority="diagnostic",
        human_advice_tune="Keep this explicit advice.",
        disclose_execution_constraints=False,
        is_trial=True,
        trial_portion=0.21,
        train_portion=0.32,
        eval_portion=0.43,
        train_validation_align=False,
        sampling_seed=137,
        train_base_seed=241,
        retain_model_outputs=True,
        retain_training_checkpoints=True,
        max_epochs=11,
        training_budget_reserve_fraction=0.17,
        trial_max_epochs=3,
        formal_max_epochs=9,
        validation_max_portion=0.23,
        validation_max_train_samples=173,
        training_validation_portion=0.19,
        validation_max_samples=71,
        validation_max_phase_seconds=29.0,
        skip_formal_min_delta=0.31,
        bypass_formal_time_budget_min_delta=0.41,
        bypass_formal_time_budget_minutes=13.0,
        trial_time_budget_minutes=5.0,
        formal_time_budget_minutes=17.0,
        trial_time_admission_source="forecast",
        formal_time_admission_source="forecast",
        trial_vram_budget_gb=2.0,
        formal_vram_budget_gb=3.0,
        vram_probe_step_timeout_seconds=37.0,
        vram_preflight_total_timeout_seconds=113.0,
        vram_preflight_host_memory_limit_gb=4.0,
        formal_training_scope_source="agent",
        formal_portion=0.27,
        formal_train_portion=0.61,
        formal_eval_portion=0.73,
        force_formal_round=False,
        formal_round_strategy="independent",
        degenerate_penalty_score=-7.0,
        attempts_per_round=2,
        attempts_per_formal_round=4,
        max_fail_rounds=6,
        max_steps_per_attempt=79,
        min_formal_batch_size=2,
        allow_extreme_steps=True,
        runtime_watchdog_enabled=True,
        runtime_safety_factor=1.13,
        runtime_trial_safety_factor=1.23,
        runtime_formal_safety_factor=1.37,
        runtime_watchdog_safety_factor=1.47,
        runtime_watchdog_floor_seconds=19.0,
        runtime_verification_max_wall_seconds=31.0,
        enable_chain_incumbent_formal_gates=True,
        health_feedback_history_window_iterations=5,
        health_feedback_history_max_entries_per_model=13,
        experiment_arm="n1-distinct-arm",
        scientific_evidence_order="literature_then_analysis",
        data_analysis_enabled=False,
        runtime_completion_policy="verified-prediction-v1",
        runtime_watchdog_deadline_policy="forecast-tightening-v1",
        gpu_admission_measurement_source="n1-measurement",
        gpu_admission_enforcement="enforce",
        gpu_pair_ceiling_gib=3.5,
        workflow_parameter_rules=ParameterRules.model_validate(
            {"model_config.segmentation_size": {"exact": 40000}}
        ),
    )


def _matrix_options(case):
    controls = _nondefault_controls() if case in ("controls", "split_routes") else {}
    routes = WorkflowLLMConfig()
    if case == "empty":
        routes = WorkflowLLMConfig(tune=TunerLLMConfig())
        controls = dict(cleanup_denoised=True, max_rounds=4, human_advice_tune="")
    if case == "split_routes":
        routes = WorkflowLLMConfig(
            tune=TunerLLMConfig(
                planner_strategy="native-timing-v1",
                planner=NodeLLMConfig(
                    provider="openai",
                    model_id="planner-distinct",
                    reasoning_effort="high",
                    max_retries=4,
                ),
                reflector=NodeLLMConfig(
                    provider="deepseek", model_id="reflector-distinct", max_retries=6
                ),
            )
        )
    return controls, routes


@pytest.mark.parametrize("case", ["omitted", "empty", "controls", "split_routes"])
def test_production_tuner_input_matches_pre_extraction_oracle(
    workflow_env, tmp_path, monkeypatch, case
):
    """A missing mapping or accidental default changes complete input equality."""
    from agent import planner_strategy

    # Exercise truly omitted routing with an explicitly installed default fixture;
    # this checkout deliberately has no experiment distribution installed.
    native = planner_strategy.resolve_planner_strategy("native-timing-v1")
    monkeypatch.setattr(
        planner_strategy,
        "entry_points",
        lambda **_kwargs: [SimpleNamespace(name="n1-fixture-default", load=lambda: lambda: native)],
    )
    from workflows import model_exploration

    builder = MagicMock(wraps=model_exploration.prepare_native_tuner_input)
    monkeypatch.setattr(model_exploration, "prepare_native_tuner_input", builder)
    controls, routes = _matrix_options(case)
    if "experiment_arm" in controls:
        seed_path = tmp_path / "data/punet/v1/agent/run_output_v1_agent.json"
        seed = json.loads(seed_path.read_text())
        seed["experiment_arm"] = "n1-distinct-arm"
        seed_path.write_text(json.dumps(seed))
    if case == "split_routes":
        from core.runtime_control import verifier_provider
        from tests.unit.core.test_native_gpu_execution import execution_policy

        profile = verifier_provider.RuntimeVerifierProfile(
            name="n1-verifier",
            version="1",
            create=lambda **_kwargs: pytest.fail("input capture must not execute verification"),
            sources={"run_config.py": workflow_tests.REPO_ROOT / "src/workflows/run_config.py"},
            qualified_assemblies=frozenset({verifier_provider.verifier_assembly_digest()}),
        )
        monkeypatch.setattr(
            verifier_provider,
            "entry_points",
            lambda **_kwargs: [SimpleNamespace(name="n1-verifier", load=lambda: lambda: profile)],
        )
        controls.update(
            runtime_verifier="n1-verifier",
            runtime_verifier_identity=profile.identity(),
            gpu_execution_policy=execution_policy(),
        )
    workflow_options = {}
    if case == "split_routes":
        raw_health = tmp_path / "raw_health.yaml"
        shutil.copyfile(
            workflow_tests.REPO_ROOT
            / "src/execute_tools/health_checks/resources/health_checks.yaml",
            raw_health,
        )
        workflow_options = dict(
            health_checks_config=str(raw_health),
            data_scope=DataScope(file_indices=[0, 1, 2, 3]),
            health_gate_files=[0, 2],
            order_strategy_override="sequential",
            file_order_override=[2, 0, 3, 1],
            enable_structured_health_feedback=True,
            measurement_capability=ResolvedMeasurementCapability(
                task_identity="n1-task",
                dataset_adapter="n1-adapter",
                data_shape_class="n1-shape",
                probe_available=False,
                unavailability_reason="offline witness",
                dataset_root=workflow_env["data_dir"],
            ),
        )
    workflow_tests.run_workflow(
        launch=WorkflowLaunchConfig(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            **controls,
        ),
        workspace=workflow_env["workspace"],
        run_name="n1_parity",
        llm_config=routes,
        **workflow_options,
    )
    builder.assert_called_once()
    assert (
        builder.call_args.kwargs["run_invariants"]
        is builder.call_args.kwargs["bindings"].run_invariants
    )
    actual = workflow_env["tune"].return_value.run.call_args.args[0]
    payload = json.loads(json.dumps(actual.model_dump(mode="json")).replace(str(tmp_path), "<TMP>"))
    expected = json.loads((ORACLE / f"{case}.json").read_text())
    actual_fingerprint = payload["task_composition_ref"].pop("semantic_fingerprint")
    baseline_fingerprint = expected["task_composition_ref"].pop("semantic_fingerprint")
    assert (
        baseline_fingerprint == "7f8103588d30aa06fdecd1d3c81e318dee7a7b3733838174829f7770843f9fd6"
    )
    assert actual_fingerprint == workflow_env["composition"].semantic_fingerprint
    # The assembly includes llm_bridge.py, so transport changes legitimately
    # change its source identity even when all forwarded settings are unchanged.
    # Keep the captured oracle intact and compare only this digest separately.
    actual_planner_assembly = payload["expected_planner_strategy"].pop("assembly_sha256")
    baseline_planner_assembly = expected["expected_planner_strategy"].pop("assembly_sha256")
    assert (
        baseline_planner_assembly
        == "419a018c994132cc127c5562a9a234ddf5f67ce0ee7a1147657b07380a71e942"
    )
    current_planner = planner_strategy.resolve_planner_strategy("native-timing-v1")
    assert actual_planner_assembly == current_planner.identity.assembly_sha256
    assert actual.expected_planner_strategy == current_planner.identity
    if case == "split_routes":
        # The verifier source and execution assembly have evolved independently.
        # Preserve the oracle bytes and verify these source-derived digests against
        # their current owners; verifier name/version remain in exact equality.
        actual_content = payload["runtime_verifier_identity"].pop("content_sha256")
        baseline_content = expected["runtime_verifier_identity"].pop("content_sha256")
        assert (
            baseline_content == "bda92755c56c34ad817e387230b08ffcff0233d3dd7574bd9269a54c307568e6"
        )
        assert actual_content == profile.identity().content_sha256
        actual_verifier_assembly = payload["runtime_verifier_identity"].pop("assembly_sha256")
        baseline_verifier_assembly = expected["runtime_verifier_identity"].pop("assembly_sha256")
        assert (
            baseline_verifier_assembly
            == "63ec1733cf6b1a1e7b0b9403e67e02c5784a2379f45df013a216604b6085bdb2"
        )
        assert actual_verifier_assembly == verifier_provider.verifier_assembly_digest()
        assert actual.runtime_verifier_identity == profile.identity()
    assert payload == expected
    from core.preflight_estimation import estimation_assembly_digest

    composition = workflow_env["composition"]
    assert composition.preflight_estimator_identity == composition.preflight_estimator.identity()
    assert composition.preflight_estimator_identity.assembly_sha256 == estimation_assembly_digest()
    provenance = json.loads((ORACLE / "provenance.json").read_text())
    baseline_identity = provenance["baseline_native_preflight_estimator_identity"]
    actual_identity = composition.preflight_estimator_identity.model_dump(mode="json")
    for field in ("name", "version", "content_sha256"):
        assert actual_identity[field] == baseline_identity[field]
    if case == "split_routes":
        assert actual.health_checks_config == str(tmp_path / "raw_health.yaml")
        assert actual.health_gate_files == [0, 2]
        assert actual.file_order_override == [2, 0, 3, 1]
        effective = Path(workflow_env["workspace"]) / "health_checks_effective.yaml"
        assert effective.is_file() and str(effective) != actual.health_checks_config
    else:
        assert actual.health_checks_config is None
    assert actual.task_composition_ref.task_data_path_id == "quickstart_tabular"
    lock = RunInvariants.model_validate_json(
        (Path(workflow_env["workspace"]) / "run_invariants_lock.json").read_text()
    )
    assert actual_fingerprint == lock.task_composition_fingerprint
    assert actual.expected_planner_strategy == lock.planner_strategy_identity
    assert actual.runtime_verifier_identity == lock.runtime_verifier_identity
    for field in (
        "experiment_arm",
        "lit_review_enabled",
        "data_analysis_enabled",
        "lit_review_config_sha256",
        "scientific_evidence_order",
        "baseline_isolation",
    ):
        assert getattr(actual, field) == getattr(lock, field)

    if case in ("controls", "split_routes"):
        assert actual.train_portion == 0.32
        assert actual.formal_max_epochs == 9
        assert actual.experiment_arm == "n1-distinct-arm"
        assert actual.human_advice == "Keep this explicit advice."
    if case == "split_routes":
        assert actual.llm_model_id == "planner-distinct"
        assert actual.reflect_model_id == "reflector-distinct"
        assert actual.max_retries == 4
        assert actual.reflect_retry_policy.max_retries == 6
