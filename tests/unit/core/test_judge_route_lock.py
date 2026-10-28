"""B2-4: judge routes are a canonical run invariant, locked identically at every entry.

Verdicts come from the production lock builders and validators against real
lock files. Route values are literals, never read back from the implementation.
"""

from __future__ import annotations

import json

import pytest

from agent.schemas.judge import JudgeRoute, JudgeRoutes
from core.run_invariants import (
    RUN_INVARIANTS_BASENAME,
    RunInvariants,
    RunInvariantsViolation,
    build_run_invariants,
    validate_run_invariants,
    write_run_invariants,
)
from workflows.llm_config import WorkflowLLMConfig

STOP = {"provider": "openai", "model_id": "gpt-5-mini", "max_output_tokens": 800, "max_retries": 3}
ROUTES = JudgeRoutes(
    stop=JudgeRoute(
        provider="openai",
        model_id="gpt-5-mini",
        reasoning_effort=None,
        max_output_tokens=800,
        max_retries=3,
    ),
    max_judge_calls=5,
)


def _invariants(judge_routes: JudgeRoutes | None) -> RunInvariants:
    return RunInvariants(
        resolved_data_scope=[0, 1],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="estimator-v1",
        runtime_policy_identity="policy-v1",
        judge_routes=judge_routes,
    )


def _judge_config(**stop: object) -> WorkflowLLMConfig:
    from tests.integration.workflows.test_chain_candidate_graduation import _llm_config_pseudo

    return _llm_config_pseudo().model_copy(
        update={
            "judge": WorkflowLLMConfig.model_validate(
                {"judge": {"stop": STOP | stop, "max_judge_calls": 5}}
            ).judge
        }
    )


class TestLockBytes:
    def test_judge_free_lock_writes_no_key_and_a_judged_lock_round_trips(self, tmp_path):
        """Fails if a judge-free lock serializes ``null`` (changing every
        existing lock's bytes) or a judged lock drops the routes."""
        write_run_invariants(str(tmp_path / "free"), _invariants(None))
        free = json.loads((tmp_path / "free" / RUN_INVARIANTS_BASENAME).read_text())
        assert "judge_routes" not in free
        write_run_invariants(str(tmp_path / "judged"), _invariants(ROUTES))
        judged = json.loads((tmp_path / "judged" / RUN_INVARIANTS_BASENAME).read_text())
        assert judged["judge_routes"]["stop"]["model_id"] == "gpt-5-mini"
        validate_run_invariants(str(tmp_path / "judged"), _invariants(ROUTES))

    @pytest.mark.parametrize(
        "resumed",
        [
            None,
            ROUTES.model_copy(
                update={"stop": ROUTES.stop.model_copy(update={"model_id": "gpt-5"})}
            ),
            ROUTES.model_copy(update={"stop": ROUTES.stop.model_copy(update={"max_retries": 9})}),
            ROUTES.model_copy(update={"max_judge_calls": 6}),
        ],
    )
    def test_a_continuation_cannot_change_or_drop_the_judge_route(self, tmp_path, resumed):
        """Fails if ``judge_routes`` is recorded but not compared: recorded
        verdicts would then be continued under another model, retry bound or call cap."""
        write_run_invariants(str(tmp_path), _invariants(ROUTES))
        with pytest.raises(RunInvariantsViolation, match="judge_routes"):
            validate_run_invariants(str(tmp_path), _invariants(resumed))


class TestEntryPaths:
    def test_chain_preflight_workflow_and_tuner_lock_the_same_routes(self, tmp_path):
        """Fails if any of the three lock sites drops or re-derives the routes;
        the W7 rule: two entry points writing one workspace must agree."""
        from agent.schemas.hyperparam_tuning import HyperparamTuningInput
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _lock_launch_identity,
        )
        from tests.unit.sdsc_submission_scripts.test_arxiv_u1_identity_chain_wiring import (
            _args,
            roi,
        )
        from workflows.run_config import WorkflowLaunchConfig
        from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings
        from workflows.training_startup import workflow_lock_identity

        llm = _judge_config()
        identities = [
            _lock_launch_identity(
                HyperparamTuningInput(
                    model_type="synthetic_model",
                    planner_strategy="native-timing-v1",
                    judge_routes=ROUTES,
                )
            ),
            workflow_lock_identity(WorkflowLaunchConfig(), llm),
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
            assert expected.judge_routes == ROUTES
        args = _args(())
        args.workspace = str(tmp_path / "chain")
        args.health_gate_enabled = False
        args.health_gate_files = None
        composition = compose_run_task_bindings(args.task_composition)
        with bind_run_task_composition(composition, physical_data_root=args.data_dir):
            preflight = roi.compute_expected_invariants(
                args, run_composition=composition, launch=roi._InvariantLaunchInputs(llm_config=llm)
            )
        assert preflight.judge_routes == ROUTES

    def test_run_workflow_locks_the_routes_and_echoes_them_to_the_tuner(
        self, tmp_path, monkeypatch
    ):
        """Fails if the workflow lock omits the routes or the tuner input does
        not carry them: the tuner would then validate the workspace lock
        against a judge-free identity and abort every judged run."""
        import tests.unit.workflows.test_arxiv_u3_isolation_workflow as harness

        monkeypatch.setattr(harness, "_llm_config_pseudo", _judge_config)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        captured = harness._run(str(workspace), isolation=False, proposal_name="fresh_tcn")
        lock = json.loads((workspace / RUN_INVARIANTS_BASENAME).read_text())
        assert JudgeRoutes.model_validate(lock["judge_routes"]) == ROUTES
        assert captured["tune_input"].judge_routes == ROUTES
