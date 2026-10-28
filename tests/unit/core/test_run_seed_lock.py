"""Issue #983 S3a: the run seed is a locked, canonical run invariant.

Every verdict comes from the production lock and resolver functions against
real lock files. Each test names the defect whose assertion it owns.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.run_invariants import (
    RUN_INVARIANTS_BASENAME,
    RunInvariants,
    RunInvariantsViolation,
    build_run_invariants,
    load_run_invariants,
    run_seed_lock_fields,
    validate_run_invariants,
    write_run_invariants,
)
from core.run_seed_lock import (
    WorkspaceRunSeed,
    continuation_run_seed,
    resolve_workspace_run_seed,
)

#: Literal seeds, never read back from the implementation. ``SEED`` exceeds
#: 2**52 so a float round-trip anywhere on the path would corrupt it.
SEED = 4_503_599_627_370_497
OTHER = 11
PRE_SEED = "created before the run-seed contract"


def _invariants(run_seed: int | None) -> RunInvariants:
    return RunInvariants(
        resolved_data_scope=[0, 1],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="estimator-v1",
        runtime_policy_identity="policy-v1",
        **run_seed_lock_fields(run_seed),
    )


def _lock(workspace: Path, run_seed: int | None) -> Path:
    return Path(write_run_invariants(str(workspace), _invariants(run_seed)))


class TestLockBytes:
    def test_seeded_lock_records_seed_and_derivation(self, tmp_path):
        """Fails if either field is dropped from serialization: a resume
        could then neither adopt the seed nor tell which derivation used it."""
        raw = json.loads(_lock(tmp_path, SEED).read_text())
        assert raw["run_seed"] == SEED
        assert raw["seed_derivation"] == "siderius-seed/v1"

    def test_seedless_lock_keeps_the_pre_seed_key_set(self, tmp_path):
        """Fails if a seedless lock serializes ``null`` keys, which would
        change the bytes of every candidate-graph and archived-shape lock."""
        raw = json.loads(_lock(tmp_path, None).read_text())
        assert "run_seed" not in raw
        assert "seed_derivation" not in raw


class TestContinuation:
    def test_resume_adopts_the_locked_seed(self, tmp_path):
        """Fails if a continuation without --run_seed generates a new seed
        instead of reusing the lock's, silently changing the run's numerics."""
        _lock(tmp_path, SEED)
        resolved = resolve_workspace_run_seed(str(tmp_path), None)
        assert resolved == WorkspaceRunSeed(value=SEED, origin="locked")
        assert continuation_run_seed(str(tmp_path), None) == SEED
        validate_run_invariants(str(tmp_path), _invariants(resolved.value))

    def test_a_conflicting_explicit_seed_is_refused(self, tmp_path):
        """Fails if a different --run_seed is accepted against a seeded lock,
        at the resolver or at the canonical lock comparison."""
        _lock(tmp_path, SEED)
        drift = f"run_seed: locked={SEED} vs this run={OTHER}"
        with pytest.raises(RunInvariantsViolation, match=drift):
            resolve_workspace_run_seed(str(tmp_path), OTHER)
        with pytest.raises(RunInvariantsViolation, match=drift):
            continuation_run_seed(str(tmp_path), OTHER)
        with pytest.raises(RunInvariantsViolation, match=drift):
            validate_run_invariants(str(tmp_path), _invariants(OTHER))

    def test_pre_seed_workspace_is_readable_but_refused_for_continuation(self, tmp_path):
        """Fails if a lock without a seed is continued by a seeded run (two
        randomness regimes in one trajectory), or if the refusal rewrites or
        stops reading the old lock (D-OP-3.1)."""
        path = _lock(tmp_path, None)
        before = path.read_bytes()
        assert load_run_invariants(str(tmp_path)).run_seed is None
        with pytest.raises(RunInvariantsViolation, match=PRE_SEED):
            resolve_workspace_run_seed(str(tmp_path), None)
        with pytest.raises(RunInvariantsViolation, match=PRE_SEED):
            continuation_run_seed(str(tmp_path), SEED)
        with pytest.raises(RunInvariantsViolation, match=PRE_SEED):
            validate_run_invariants(str(tmp_path), _invariants(SEED))
        assert path.read_bytes() == before

    def test_pre_seed_lock_still_validates_a_seedless_run(self, tmp_path):
        """Fails if seedless-vs-seedless is refused: candidate graphs carry no
        seed until their request does, and old tooling must still read."""
        _lock(tmp_path, None)
        validate_run_invariants(str(tmp_path), _invariants(None))


class TestFreshWorkspace:
    def test_history_import_never_inherits_the_source_seed(self, tmp_path, monkeypatch):
        """Fails if resolution reads any lock but the target's, so a
        ``--seed_paths`` import would continue the source run's seed."""
        _lock(tmp_path / "source", SEED)
        monkeypatch.setattr("core.seeding.generate_run_seed", lambda: 7)
        resolved = resolve_workspace_run_seed(str(tmp_path / "new"), None)
        assert resolved == WorkspaceRunSeed(value=7, origin="generated")
        assert resolved.log_line() == "[seed] run_seed=7 source=generated"

    def test_an_explicit_seed_starts_a_new_workspace(self, tmp_path):
        """Fails if an operator seed is replaced or mislabelled on a fresh run."""
        resolved = resolve_workspace_run_seed(str(tmp_path), OTHER)
        assert resolved == WorkspaceRunSeed(value=OTHER, origin="operator")


class TestEntryPaths:
    def test_tuner_and_workflow_lock_builders_carry_the_seed(self, tmp_path):
        """Fails if either lock-identity builder drops the seed, writing a
        seedless lock for a seeded run."""
        from agent.schemas.hyperparam_tuning import HyperparamTuningInput
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _lock_launch_identity,
        )
        from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
        from workflows.run_config import WorkflowLaunchConfig
        from workflows.training_startup import workflow_lock_identity

        llm = WorkflowLLMConfig(tune=TunerLLMConfig(planner_strategy="native-timing-v1"))
        identities = [
            _lock_launch_identity(
                HyperparamTuningInput(
                    model_type="synthetic_model", planner_strategy="native-timing-v1", run_seed=SEED
                )
            ),
            workflow_lock_identity(WorkflowLaunchConfig(), llm, SEED),
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
            assert (expected.run_seed, expected.seed_derivation) == (SEED, "siderius-seed/v1")

    def test_chain_preflight_adopts_the_lock_and_refuses_a_conflict(self, tmp_path):
        """Fails if the chain pre-flight expects no seed on iteration >= 2
        (every continuation would then drift against its own lock) or admits
        a conflicting --run_seed before restoration."""
        from tests.unit.sdsc_submission_scripts.test_arxiv_u1_identity_chain_wiring import (
            _args,
            roi,
        )
        from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
        from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

        llm = WorkflowLLMConfig(tune=TunerLLMConfig(planner_strategy="native-timing-v1"))
        _lock(tmp_path, SEED)

        def preflight(extra: tuple[str, ...]) -> RunInvariants:
            args = _args(extra)
            args.workspace = str(tmp_path)
            args.health_gate_enabled = False
            args.health_gate_files = None
            composition = compose_run_task_bindings(args.task_composition)
            with bind_run_task_composition(composition, physical_data_root=args.data_dir):
                return roi.compute_expected_invariants(
                    args,
                    run_composition=composition,
                    launch=roi._InvariantLaunchInputs(llm_config=llm),
                )

        assert preflight(()).run_seed == SEED
        with pytest.raises(RunInvariantsViolation, match="run_seed"):
            preflight(("--run_seed", str(OTHER)))

    def test_run_workflow_generates_locks_prints_and_forwards_the_seed(self, tmp_path, capsys):
        """Fails if the workflow startup skips resolution (a seedless lock),
        prints no seed line, or the tuner input loses the locked seed."""
        from tests.unit.workflows.test_arxiv_u3_isolation_workflow import _run

        workspace = tmp_path / "ws"
        workspace.mkdir()
        captured = _run(str(workspace), isolation=False, proposal_name="fresh_tcn")
        lock = json.loads((workspace / RUN_INVARIANTS_BASENAME).read_text())
        assert isinstance(lock["run_seed"], int)
        assert lock["seed_derivation"] == "siderius-seed/v1"
        assert f"[seed] run_seed={lock['run_seed']} source=generated" in capsys.readouterr().out
        assert captured["tune_input"].run_seed == lock["run_seed"]


class TestLaunchSurface:
    def test_cli_binds_an_explicit_seed_and_refuses_out_of_range(self):
        """Fails if --run_seed accepts a value outside RunSeed (inexact in a
        JavaScript number) or does not reach the launch projection."""
        from tests.unit.sdsc_submission_scripts.test_arxiv_u1_identity_chain_wiring import _args

        assert _args(("--run_seed", str(SEED))).run_seed == SEED
        assert _args(()).run_seed is None
        with pytest.raises(SystemExit):
            _args(("--run_seed", str(2**53)))

    def test_seedless_launch_projection_has_no_seed_key(self):
        """Fails if a seedless launch projects ``run_seed: null``, which would
        change reviewed native-chain capture bytes (seed-contract §13.2)."""
        from workflows.launch_projection import json_launch_values
        from workflows.run_config import WorkflowLaunchConfig

        assert "run_seed" not in json_launch_values(WorkflowLaunchConfig())
        assert json_launch_values(WorkflowLaunchConfig(run_seed=SEED))["run_seed"] == SEED

    def test_candidate_settings_refuse_a_launch_run_seed(self):
        """T12. Fails if a candidate graph accepts a second seed authority
        beside its run request (seed-contract M3)."""
        from workflows.candidate_training_settings import CandidateTrainingSettings
        from workflows.run_config import WorkflowLaunchConfig

        with pytest.raises(
            ValueError, match=r"unsupported fresh training controls: \['run_seed'\]"
        ):
            CandidateTrainingSettings(launch=WorkflowLaunchConfig(run_seed=SEED))
