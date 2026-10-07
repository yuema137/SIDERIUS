"""#369: explicit limits survive persistence and govern resume admission."""

import json
from pathlib import Path

import pytest

from core.run_invariants import (
    LockLaunchIdentity,
    RunInvariantsViolation,
    build_run_invariants,
    load_run_invariants,
    validate_run_invariants,
    write_run_invariants,
)


def build(tmp_path, portion=None, samples=None):
    return build_run_invariants(
        resolved_data_scope=[0],
        health_gate_enabled=False,
        health_gate_files=None,
        health_checks_config=None,
        workspace=str(tmp_path),
        task_composition_fingerprint="a" * 64,
        include_runtime_identities=False,
        launch_identity=LockLaunchIdentity(
            validation_max_portion=portion,
            validation_max_samples=samples,
        ),
    )[0]


def test_disabled_is_recorded_and_each_change_is_rejected(tmp_path):
    expected = build(tmp_path)
    path = write_run_invariants(str(tmp_path), expected)
    raw = json.loads(Path(path).read_text())
    assert raw["validation_limits_recorded"] is True
    assert raw["validation_max_portion"] is None
    assert raw["validation_max_samples"] is None
    validate_run_invariants(str(tmp_path), expected)
    for changed, field in [
        (build(tmp_path, 0.25), "validation_max_portion"),
        (build(tmp_path, samples=100), "validation_max_samples"),
    ]:
        with pytest.raises(RunInvariantsViolation, match=field):
            validate_run_invariants(str(tmp_path), changed)


def test_enabled_limits_roundtrip_and_cannot_be_removed(tmp_path):
    expected = build(tmp_path, 0.25, 100)
    write_run_invariants(str(tmp_path), expected)
    loaded = load_run_invariants(str(tmp_path))
    assert loaded.validation_max_portion == 0.25
    assert loaded.validation_max_samples == 100
    validate_run_invariants(str(tmp_path), expected)
    with pytest.raises(RunInvariantsViolation, match="validation_max"):
        validate_run_invariants(str(tmp_path), build(tmp_path))


def test_old_lock_is_readable_but_missing_evidence_cannot_certify_resume(tmp_path):
    expected = build(tmp_path)
    path = write_run_invariants(str(tmp_path), expected)
    raw = json.loads(Path(path).read_text())
    for name in ("validation_limits_recorded", "validation_max_portion", "validation_max_samples"):
        raw.pop(name)

    Path(path).write_text(json.dumps(raw))
    before = Path(path).read_bytes()
    assert load_run_invariants(str(tmp_path)) is not None
    with pytest.raises(RunInvariantsViolation, match="Legacy workspace did not record"):
        validate_run_invariants(str(tmp_path), expected)
    assert Path(path).read_bytes() == before


def test_missing_value_cannot_claim_recorded_limits(tmp_path):
    expected = build(tmp_path, 0.25, 100)
    path = write_run_invariants(str(tmp_path), expected)

    raw = json.loads(Path(path).read_text())
    raw.pop("validation_max_samples")
    Path(path).write_text(json.dumps(raw))
    with pytest.raises(RunInvariantsViolation, match="both explicit values"):
        load_run_invariants(str(tmp_path))


def test_all_launch_paths_transport_limits_to_the_shared_builder(tmp_path):
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _lock_launch_identity,
    )
    from tests.unit.sdsc_submission_scripts.test_arxiv_u1_identity_chain_wiring import _args, roi
    from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
    from workflows.model_exploration import _workflow_lock_identity
    from workflows.run_config import WorkflowLaunchConfig
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    llm = WorkflowLLMConfig(tune=TunerLLMConfig(planner_strategy="native-timing-v1"))
    values = dict(validation_max_portion=0.25, validation_max_samples=100)
    identities = [
        _lock_launch_identity(
            HyperparamTuningInput(
                model_type="synthetic_model", planner_strategy="native-timing-v1", **values
            )
        ),
        _workflow_lock_identity(WorkflowLaunchConfig(**values), llm),
    ]
    for index, identity in enumerate(identities):
        expected, _ = build_run_invariants(
            resolved_data_scope=[0],
            health_gate_enabled=False,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path / str(index)),
            task_composition_fingerprint="a" * 64,
            include_runtime_identities=False,
            launch_identity=identity,
        )
        assert expected.validation_max_portion == 0.25
        assert expected.validation_max_samples == 100
    args = _args(["--validation_max_portion", "0.25", "--validation_max_samples", "100"])
    args.workspace = str(tmp_path / "chain")
    args.health_gate_enabled = False
    args.health_gate_files = None
    composition = compose_run_task_bindings(args.task_composition)
    with bind_run_task_composition(composition, physical_data_root=args.data_dir):
        expected = roi.compute_expected_invariants(
            args, run_composition=composition, launch=roi._InvariantLaunchInputs(llm_config=llm)
        )
    assert expected.validation_max_portion == 0.25
    assert expected.validation_max_samples == 100
    assert expected.validation_limits_recorded is True
