"""Issue #983 S3b: the tuner derives every attempt seed from the locked run seed.

Each test names the defect whose assertion it owns. Pseudo-iteration tests
drive the production ``HyperparamTuningAgent.run`` with a scripted bridge.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from unittest.mock import MagicMock, patch

import pytest

from core.seeding import MissingRunSeed, SeedCoordinates, derive_seed
from nodes.ml_hyperparameter_tune_agent.attempt_seeds import derive_attempt_seeds
from tests.helpers.recording_llm_bridge import RecordingLLMBridge
from tests.helpers.step00_pseudo_iteration import (
    FIXTURE_RUN_SEED,
    PSEUDO_AGENT_FOLDER,
    run_bounded_pseudo_iteration,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?")
PREFLIGHT = pathlib.Path(__file__).parent / "fixtures" / "step00_preflight_results.json"

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


def _preflight():
    return json.loads(PREFLIGHT.read_text())["results"]


def _trial_configs(workspace: str) -> list[dict]:
    paths = sorted(pathlib.Path(workspace).rglob("trial_config_*.json"))
    assert paths, "the pseudo run persisted no trial_config"
    return [json.loads(p.read_text()) for p in paths]


class TestAttemptPosition:
    def test_seeds_differ_by_chain_iteration_round_attempt_and_run_seed(self):
        """T7. Fails if any coordinate is dropped (F-SEED-1: every native
        chain repeated one seed per (iteration, attempt)) or the run seed
        does not reach the derivation."""

        def train(run_seed, iteration, round_index, attempt):
            return derive_attempt_seeds(
                run_seed,
                SeedCoordinates(iteration=iteration),
                round_index=round_index,
                attempt=attempt,
                align=True,
            ).train_sampling

        base = train(5, 1, 1, 1)
        assert len({base, train(6, 1, 1, 1), train(5, 2, 1, 1), train(5, 1, 2, 1)}) == 4
        assert train(5, 1, 1, 2) != base

    def test_alignment_reuses_the_training_selection_seed(self):
        """Fails if train_validation_align stops aligning the two legs (or
        unaligned evaluation silently reuses the training seed)."""
        scope = SeedCoordinates(iteration=3)
        aligned = derive_attempt_seeds(9, scope, round_index=1, attempt=1, align=True)
        split = derive_attempt_seeds(9, scope, round_index=1, attempt=1, align=False)
        assert aligned.eval_sampling == aligned.train_sampling
        assert split.eval_sampling != split.train_sampling

    def test_caller_cannot_claim_tuner_owned_coordinates(self):
        """Fails if a caller can pre-set round/attempt and collapse every
        attempt of a run onto one seed."""
        from agent.schemas.hyperparam_tuning import HyperparamTuningInput

        with pytest.raises(ValueError, match="tuner- and trainer-owned"):
            HyperparamTuningInput(model_type="fcnet", seed_coordinates=SeedCoordinates(attempt=1))


class TestPseudoIteration:
    def test_persisted_seeds_derive_from_the_locked_run_seed(self, tmp_path, monkeypatch):
        """T7/T11. Fails if the tuner still derives seeds from run_name, if
        the trainer context omits the attempt position, or if the lock does
        not record the seed the attempts used."""
        _, _, _, workspace = run_bounded_pseudo_iteration(
            tmp_path, monkeypatch, preflight_results=_preflight()
        )
        for config in _trial_configs(workspace):
            at = SeedCoordinates.model_validate(config["seed_context"]["at"])
            assert config["seed_context"]["run_seed"] == FIXTURE_RUN_SEED
            assert at.round is not None and at.attempt is not None
            assert config["train_sampling_seed"] == derive_seed(
                FIXTURE_RUN_SEED, "tuner.train_sampling", at
            )
            assert "train_base_seed" not in config
        lock = json.loads((pathlib.Path(workspace) / "run_invariants_lock.json").read_text())
        assert lock["run_seed"] == FIXTURE_RUN_SEED

    def test_missing_run_seed_is_refused_before_any_llm_call(self, tmp_path, monkeypatch):
        """T11 (M2). Fails if a workflow-reached tuner generates a seed (or
        runs unseeded) when the protocol delivers none."""
        bridge = RecordingLLMBridge.for_agent(PSEUDO_AGENT_FOLDER)
        with pytest.raises(MissingRunSeed):
            run_bounded_pseudo_iteration(
                tmp_path,
                monkeypatch,
                preflight_results=_preflight(),
                input_overrides={"run_seed": None},
                bridge=bridge,
            )
        assert bridge.calls == []

    def test_llm_requests_are_identical_across_run_seeds(self, tmp_path, monkeypatch):
        """T15 (native). Fails if any seed value leaks into a planner or
        reflector request; the trial configs prove the seed took effect."""
        recorded = []
        for run_seed in (1, 2):
            _, bridge, _, workspace = run_bounded_pseudo_iteration(
                tmp_path / str(run_seed),
                monkeypatch,
                preflight_results=_preflight(),
                input_overrides={"run_seed": run_seed},
            )
            text = repr(bridge.calls).replace(str(tmp_path / str(run_seed)), "<TMP>")
            # Record timestamps are wall-clock, not seed-owned.
            text = _TIMESTAMP.sub("<TS>", text)
            recorded.append((text, [c["train_sampling_seed"] for c in _trial_configs(workspace)]))
        assert recorded[0][0] == recorded[1][0]
        assert recorded[0][1] != recorded[1][1]


class TestStandaloneEntryBoundary:
    def _argv(self, workspace, *extra: str) -> list[str]:
        return [
            "ml_hyperparameter_tune_agent.py",
            *("--force_model", "fcnet", "--max_rounds", "1"),
            *("--workspace", str(workspace), "--run_name", "cli_test"),
            *("--task_composition", str(REPO_ROOT / "configs/task_composition/quickstart.yaml")),
            *("--data_dir", str(workspace)),
            *extra,
        ]

    def _run_main(self, argv) -> int:
        from nodes.ml_hyperparameter_tune_agent import main

        pathlib.Path(argv[argv.index("--workspace") + 1]).mkdir(parents=True, exist_ok=True)
        with (
            patch("nodes.ml_hyperparameter_tune_agent.HyperparamTuningAgent") as agent_cls,
            patch.object(sys, "argv", argv),
        ):
            agent_cls.return_value = MagicMock()
            main()
        return agent_cls.return_value.run.call_args[0][0].run_seed

    def test_main_generates_then_adopts_the_locked_seed(self, tmp_path, monkeypatch, capsys):
        """T11 (R2). Fails if the standalone CLI hands the node no seed, does
        not print it before execution, or ignores the workspace lock on rerun."""
        from core.run_invariants import RunInvariants, run_seed_lock_fields, write_run_invariants

        monkeypatch.setattr("core.seeding.generate_run_seed", lambda: 7)
        assert self._run_main(self._argv(tmp_path / "fresh")) == 7
        assert "[seed] run_seed=7 source=generated" in capsys.readouterr().out
        locked = tmp_path / "locked"
        write_run_invariants(
            str(locked),
            RunInvariants(
                resolved_data_scope=[0],
                health_gate_enabled=False,
                health_config_sha256=None,
                **run_seed_lock_fields(41),
            ),
        )
        assert self._run_main(self._argv(locked)) == 41
        assert "[seed] run_seed=41 source=locked" in capsys.readouterr().out


class TestRetiredSeedPins:
    @pytest.mark.parametrize("name", ["sampling_seed", "train_base_seed"])
    def test_tuner_input_refuses_a_retired_pin_even_when_null(self, name):
        """T13. Fails if a retired pin is silently ignored by the node input."""
        from agent.schemas.hyperparam_tuning import HyperparamTuningInput

        with pytest.raises(ValueError, match="seeds derive from run_seed; set --run_seed"):
            HyperparamTuningInput.model_validate({"model_type": "fcnet", name: None})

    def test_saved_settings_and_cli_refuse_a_retired_pin(self):
        """T13. Fails if a saved workflow/settings launch or the runner CLI
        accepts a retired pin instead of refusing with the run-seed message."""
        from tests.unit.sdsc_submission_scripts.test_arxiv_u1_identity_chain_wiring import _args
        from workflows.candidate_training_settings import parse_training_settings

        with pytest.raises(ValueError, match="seeds derive from run_seed"):
            parse_training_settings(json.dumps({"launch": {"train_base_seed": 3}}))
        with pytest.raises(SystemExit):
            _args(("--sampling_seed", "5"))

    def test_seedless_saved_review_stays_comparable(self):
        """T13 migration. Fails if a launch review recorded before the
        retirement (pins projected as null) is refused, or a review that
        executed a set pin is silently accepted."""
        from core.retired_seed_pins import RetiredSeedPin
        from workflows.launch_projection import json_launch_values
        from workflows.reviewed_launch_binding import ReviewedLaunchRefusal
        from workflows.run_config import WorkflowLaunchConfig

        current = json_launch_values(WorkflowLaunchConfig())
        expectations = MagicMock()
        from workflows.launch_expectations import LaunchExpectations

        check = LaunchExpectations.check_projection
        check(
            expectations,
            WorkflowLaunchConfig(),
            {**current, "sampling_seed": None, "train_base_seed": None},
        )
        with pytest.raises(RetiredSeedPin):
            check(expectations, WorkflowLaunchConfig(), {**current, "sampling_seed": 5})
        with pytest.raises(ReviewedLaunchRefusal):
            check(expectations, WorkflowLaunchConfig(max_rounds=9), current)
