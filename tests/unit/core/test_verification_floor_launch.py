"""Launch overrides must survive to recorded policy and both slowdown decisions."""

import json
import random
from pathlib import Path

import pytest

from core.runtime_control.launch_argv import runtime_control_argv
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from nodes.ml_hyperparameter_tune_agent.cli import build_agent_input, build_parser
from nodes.ml_hyperparameter_tune_agent.runtime import _build_runtime_policy
from tests.unit.core.test_runtime_verification_window import _call_keyword_value
from workflows.candidate_training_settings import parse_training_settings
from workflows.run_one_iteration import build_parser as workflow_parser

FIELD = "runtime_verification_pathological_min_unit_ms"
ROOT = Path(__file__).resolve().parents[3]


def test_workflow_floor_transport() -> None:
    """Catch a dropped optional field at either standard-launch or protocol hop."""
    args = workflow_parser().parse_args(
        [
            "--workspace",
            "/tmp/floor",
            "--run_name",
            "floor",
            "--task_composition",
            "unused.yaml",
            "--data_dir",
            "/tmp/data",
            f"--{FIELD}",
            "0",
        ]
    )
    assert getattr(args, FIELD) == 0.0
    settings = parse_training_settings(json.dumps({"launch": {FIELD: 0.0}}))
    assert getattr(settings.launch, FIELD) == 0.0
    from tests.helpers.launcher_bindings import workflow_call_bindings
    from tests.helpers.workflow_delegation import (
        TUNER_PREPARATION,
        TUNER_PREPARATION_ENTRYPOINT,
        assert_run_workflow_delegates,
    )

    assert (
        workflow_call_bindings(ROOT / "src/workflows/run_one_iteration.py")[FIELD]
        == f"args.{FIELD}"
    )
    assert (
        _call_keyword_value(
            ROOT / "src/workflows/standard_launch.py", "WorkflowLaunchConfig", FIELD
        )
        == f"args.{FIELD}"
    )
    assert_run_workflow_delegates(
        TUNER_PREPARATION_ENTRYPOINT, TUNER_PREPARATION, "local_validated_model"
    )
    assert (
        _call_keyword_value(TUNER_PREPARATION, "local_validated_model", FIELD) == f"launch.{FIELD}"
    )
    assert (
        _call_keyword_value(
            ROOT / "src/agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py",
            "HyperparamTuningInput",
            FIELD,
        )
        == FIELD
    )


@pytest.mark.parametrize("guard", ["streak", "distribution"])
@pytest.mark.parametrize("batch_size", [1, 1024])
@pytest.mark.parametrize("window", [None, 420.0])
def test_cli_floor_reaches_verifier_and_evidence(
    tmp_path: Path, guard: str, batch_size: int, window: float | None
) -> None:
    """Zero restores ratio-only refusal; positive floors use observed batch cost.

    Dropping the CLI field, either policy key, or the subprocess policy transport
    loses the refusal/evidence assertions. Large batches retain sub-ms rates but
    exceed the default wall-time floor, distinguishing rates from observations.
    """
    parser = build_parser()
    common = [
        "--data_dir",
        str(tmp_path),
        "--task_composition",
        "unused.yaml",
        "--planner_strategy",
        "native-timing-v1",
    ]
    if window is not None:
        common += ["--runtime_verification_max_wall_seconds", str(window)]
    rng = random.Random(88)
    prefix = [0.0156] * 30
    if guard == "distribution":
        prefix = [0.0156 * rng.uniform(0.4, 1.6) for _ in range(30)]
    trace = prefix + [0.219] * 250
    for floor, expected in [
        (None, "verified" if batch_size == 1 else "failed_pathological_unit"),
        (0.0, "failed_pathological_unit"),
        (1000.0, "verified"),
    ]:
        flags = [] if floor is None else [f"--{FIELD}", str(floor)]
        inp = build_agent_input(parser.parse_args(common + flags), parser)
        raw = _build_runtime_policy(
            inp, chosen_time_budget=None, is_trial=True, base_dir=str(tmp_path)
        )
        assert raw.get("verification", {}) == {
            **({} if window is None else {"max_wall_ms": window * 1000.0}),
            **({} if floor is None else {"pathological_min_unit_ms": floor}),
        }
        # Hold verification open long enough to expose both guard-specific traces.
        raw.setdefault("verification", {}).update(
            min_timed_steps=30,
            steady={"rel_spread_tol": 0.00001 if guard == "distribution" else 0.1},
        )
        policy = RuntimeControlPolicy.model_validate(raw)
        argv = runtime_control_argv(
            configs_dir=str(tmp_path),
            exp_id="floor",
            observation_out=str(tmp_path / "observation.json"),
            policy=policy,
            drop_stale_observation=False,
        )
        loaded = RuntimeControlPolicy.model_validate_json(
            Path(argv[argv.index("--runtime_policy_json") + 1]).read_text()
        )
        session = RuntimeVerificationSession(str(tmp_path / "observation.json"), policy=loaded)
        verifier = session.start_phase_verification("training", "optimizer_step")
        for rate in trace:
            verifier.feed(rate, elapsed_ms=rate * batch_size)
            if verifier.is_terminal:
                break
        verifier.finalize()
        assert verifier.state == expected, verifier.failure_reason
        if expected == "failed_pathological_unit":
            assert ("consecutive" if guard == "streak" else "disjoint observed rate blocks") in (
                verifier.failure_reason or ""
            )
        evidence = json.loads((tmp_path / "observation.json").read_text())["runtime_policy"]
        assert evidence["verification"]["pathological_min_unit_ms"] == (
            100.0 if floor is None else floor
        )
        assert evidence["verification"]["max_wall_ms"] == (60000.0 if window is None else 420000.0)
