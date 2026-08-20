"""V21 PR E — E1: pin the native persistence layout join-on-read rests on.

O-E-3 chose join-on-read **because** the audit found every pre-tuner stage
already persists its own output into a per-attempt directory. That premise
is load-bearing for the whole PR, so this module pins it as *behaviour*
before E2 changes anything:

1. each node's ``run()`` writes ``{stage}_{run_name}.json`` into the
   workspace it is given (proposer / implementor / validator);
2. ``run_workflow`` gives each proposer attempt its own directory,
   renamed to ``attempt_{NNN}_{model_name}`` — two attempts never share
   or overwrite one;
3. discovery by the ``attempt_*`` prefix needs no model name (P6.2:
   a name-dependent discovery would inherit name-keyed fragility);
4. the inner implement→validate retry loop overwrites *within* one
   attempt directory — the known limitation, pinned as tested fact
   rather than assumption (under O-E-4 those retries are the same
   candidate, so only the terminal outcome matters to the funnel).

No LLM, no GPU, no production diff. Node LLM bridges are mocked at the
bridge boundary so the REAL ``run()`` bodies — including their persistence
blocks — execute; the workflow test mocks agents at the class boundary
because it pins directory behaviour that ``run_workflow`` itself owns.

Design doc: ``docs/design/v21_priorities/pr_e_proposal_scale_funnel.md``
Commit E1 (§0.C is the audit this module turns into regression tests).
"""

from __future__ import annotations

import contextlib
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.implementor import ImplementorInput, ImplementorOutput
from agent.schemas.proposal import ExpertAdvice, ProposalInput, ProposalOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_model_proposal_agent import MLModelProposalAgent

# Reuse the canonical node fixtures rather than fork them — an established
# pattern in this suite (e.g. test_health_evidence_pipeline imports from
# test_prompt_context_surfacing).
from tests.unit.agent.ml_code_validator_agent.test_validator_agent import (
    make_input as make_validator_input,
)
from tests.unit.agent.ml_model_implementor.test_implementor_agent import (
    FAKE_CODE_RESPONSE as IMPL_CODE_RESPONSE,
)
from tests.unit.agent.ml_model_implementor.test_implementor_agent import (
    FAKE_REASONING as IMPL_REASONING,
)
from tests.unit.agent.ml_model_proposal_agent.test_proposal_agent import (
    FAKE_COMMIT_RESPONSE,
    FAKE_INTERPRETATION,
    FAKE_REASONING,
)
from workflows.run_config import WorkflowLaunchConfig

pytestmark = pytest.mark.dual_mode


# ---------------------------------------------------------------------------
# Per-node persistence: the three stage files exist where §0.C says
# ---------------------------------------------------------------------------


class TestNodePersistence:
    def test_proposer_persists_proposal_json(self, tmp_path):
        with patch("nodes.ml_model_proposal_agent.LLMBridge") as MockBridge:
            MockBridge.return_value.generate_text.return_value = FAKE_REASONING
            MockBridge.return_value.generate.return_value = FAKE_COMMIT_RESPONSE
            agent = MLModelProposalAgent(provider="gemini", model_id="test-model")
            agent.bridge = MockBridge.return_value
            out = agent.run(
                ProposalInput(
                    interpretation=FAKE_INTERPRETATION,
                    existing_model_types=[],
                    constraints=[],
                    storage={
                        "backend": "local",
                        "local": {"workspace": str(tmp_path), "run_name": "e1_pin"},
                    },
                )
            )
        path = tmp_path / "proposal_e1_pin.json"
        assert path.is_file(), "proposer no longer persists proposal_{run_name}.json"
        persisted = json.loads(path.read_text())
        assert persisted["model_name"] == out.model_name

    def test_implementor_persists_implementor_json(self, tmp_path):
        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent.bridge = MagicMock()
        agent._registry = MagicMock()
        agent.bridge.generate_text.return_value = IMPL_REASONING
        agent.bridge.generate.return_value = IMPL_CODE_RESPONSE
        out = agent.run(
            ImplementorInput(
                model_name="gated_dilated_tcn",
                model_description="A gated dilated TCN for signal denoising.",
                mathematical_definition="y = tanh(W_f*x) * sigmoid(W_g*x)",
                baseline_config={
                    "model_config": {"channels": 64, "depth": 4},
                    "train_config": {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                    "loss_config": {"loss_type": "focal", "gamma": 2.0},
                },
                plugin_dir=str(tmp_path / "models"),
                test_dir=str(tmp_path / "tests"),
                storage=StorageConfig(
                    backend="local",
                    local=LocalStorageConfig(workspace=str(tmp_path), run_name="e1_pin"),
                ),
            )
        )
        path = tmp_path / "implementor_e1_pin.json"
        assert path.is_file(), "implementor no longer persists implementor_{run_name}.json"
        assert json.loads(path.read_text())["model_type"] == out.model_type

    def test_validator_persists_validation_json(self, tmp_path):
        from nodes.ml_code_validator_agent import MLCodeValidatorAgent

        agent = MLCodeValidatorAgent.__new__(MLCodeValidatorAgent)
        agent.bridge = MagicMock()
        agent.bridge.generate.return_value = {
            "passed": True,
            "spec_alignment": True,
            "implementation_issues": [],
            "trainability_concerns": [],
            "notes": "pseudo",
        }
        out = agent.run(make_validator_input(tmp_path, run_name="e1_pin"))
        path = tmp_path / "validation_e1_pin.json"
        assert path.is_file(), "validator no longer persists validation_{run_name}.json"
        assert json.loads(path.read_text())["passed"] == out.passed

    def test_inner_retry_overwrites_within_one_attempt_dir(self, tmp_path):
        """The known limitation, pinned: same storage → same file, one file.

        Under O-E-4 an implement retry is the SAME candidate, so the
        terminal outcome is what survives — and E4 must not infer retry
        counts from artifacts that were overwritten.
        """
        for name in ("first_try", "second_try"):
            agent = MLModelImplementor.__new__(MLModelImplementor)
            agent.bridge = MagicMock()
            agent._registry = MagicMock()
            agent.bridge.generate_text.return_value = IMPL_REASONING
            agent.bridge.generate.return_value = IMPL_CODE_RESPONSE
            agent.run(
                ImplementorInput(
                    model_name=name,
                    model_description="Retry-overwrite pin fixture model.",
                    mathematical_definition="y = x",
                    baseline_config={
                        "model_config": {"channels": 64, "depth": 4},
                        "train_config": {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                        "loss_config": {"loss_type": "focal", "gamma": 2.0},
                    },
                    plugin_dir=str(tmp_path / "models"),
                    test_dir=str(tmp_path / "tests"),
                    storage=StorageConfig(
                        backend="local",
                        local=LocalStorageConfig(workspace=str(tmp_path), run_name="retry"),
                    ),
                )
            )
        files = [p for p in os.listdir(tmp_path) if p.startswith("implementor_")]
        assert files == ["implementor_retry.json"], files
        assert json.loads((tmp_path / "implementor_retry.json").read_text())["model_type"] == (
            "second_try"
        ), "the terminal retry outcome must be what survives"


# ---------------------------------------------------------------------------
# Workflow attempt-directory layout: run_workflow owns this behaviour
# ---------------------------------------------------------------------------


def _proposal(name: str) -> ProposalOutput:
    return ProposalOutput(
        model_name=name,
        model_description=f"{name} stub",
        mathematical_definition="—",
        motivation="—",
        expert_advice=ExpertAdvice(
            focus_areas=["—"],
            constraints=["—"],
            known_failures=["—"],
            suggested_directions=["—"],
            rationale="pseudo layout pin",
        ),
        baseline_config={
            "model_config": {},
            "train_config": {},
            "loss_config": {"loss_type": "focal"},
        },
    )


def _impl(name: str) -> ImplementorOutput:
    return ImplementorOutput(
        model_type=name,
        description_file_path=f"/tmp/{name}.md",
        model_file_path=f"/tmp/{name}.py",
        test_file_path=f"/tmp/test_{name}.py",
        config_fields={"n_layers": 2},
        model_description=f"{name} stub",
        mathematical_definition="—",
    )


def _verdict(passed: bool, name: str) -> ValidatorOutput:
    return ValidatorOutput(
        passed=passed,
        model_type=name,
        plugin_registered=passed,
        tests_passed=passed,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=passed,
        gradient_check_passed=passed,
        llm_review_passed=True,
        error_message=None if passed else "layout-pin forced failure",
    )


class TestAttemptDirectoryLayout:
    def test_two_attempts_two_directories_discoverable_without_names(self, tmp_path):
        """The join-on-read premise, as behaviour.

        Attempt 1's validation fails (max_impl_attempts=1 → straight to a
        new proposal); attempt 2 passes. Required layout afterwards:
        two distinct ``attempt_{NNN}_{model_name}`` directories, neither
        overwritten, both found by the name-blind ``attempt_*`` glob.
        """
        from agent.schemas.interpretation import InterpretationOutput
        from workflows.model_exploration import run_workflow

        interp = InterpretationOutput(
            model_types=["punet"],
            model_descriptions={"punet": "punet"},
            total_experiments=1,
            per_model_best={"punet": 1.0},
            per_model_worst={"punet": 0.5},
            best_denoising_score=1.0,
            worst_denoising_score=0.5,
            best_config={"model_config": {}},
            key_findings=[],
            bottlenecks=[],
            take_home_message="proceed",
            model_knowledge_cache={},
            runtime_vocab=[],
        )
        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

        proposals = [_proposal("alpha_net"), _proposal("beta_net")]
        verdicts = [_verdict(False, "alpha_net"), _verdict(True, "beta_net")]

        tune_out = HyperparamTuningOutput(
            run_name="e1_layout",
            model_type="beta_net",
            file_index=6,
            status="completed",
            completed_rounds=0,
            total_attempts=0,
            all_records=[],
            started_at="2026-08-08 00:00:00",
            finished_at="2026-08-08 00:00:01",
        )

        workspace = str(tmp_path)
        # Step 0 of run_workflow loads the source model's prior tuning output
        # from {data_dir}/{model}/{source}/agent/run_output_{source}_agent.json
        # (model_exploration.py:283-300) BEFORE any agent is invoked, mocked
        # or not. Seed a minimal schema-valid one.
        seed_dir = tmp_path / "data" / "punet" / "v0" / "agent"
        seed_dir.mkdir(parents=True)
        (seed_dir / "run_output_v0_agent.json").write_text(
            HyperparamTuningOutput(
                run_name="v0",
                model_type="punet",
                file_index=6,
                status="completed",
                completed_rounds=0,
                total_attempts=0,
                all_records=[],
                started_at="2026-08-08 00:00:00",
                finished_at="2026-08-08 00:00:01",
            ).model_dump_json()
        )
        with contextlib.ExitStack() as stack:
            MockInterp = stack.enter_context(
                patch("workflows.model_exploration.ResultInterpretationAgent")
            )
            MockPropose = stack.enter_context(
                patch("workflows.model_exploration.MLModelProposalAgent")
            )
            MockImpl = stack.enter_context(patch("workflows.model_exploration.MLModelImplementor"))
            MockValid = stack.enter_context(
                patch("workflows.model_exploration.MLCodeValidatorAgent")
            )
            MockTune = stack.enter_context(
                patch("workflows.model_exploration.HyperparamTuningAgent")
            )
            stack.enter_context(
                patch("workflows.model_exploration._register_plugin", return_value=None)
            )
            stack.enter_context(
                patch("workflows.model_exploration._promote_model_to_global", return_value=None)
            )
            stack.enter_context(
                patch("workflows.model_exploration._promote_loss_to_global", return_value=None)
            )
            MockInterp.return_value.run.return_value = interp
            MockPropose.return_value.run.side_effect = proposals
            MockImpl.return_value.run.side_effect = [_impl("alpha_net"), _impl("beta_net")]
            MockValid.return_value.run.side_effect = verdicts
            MockTune.return_value.run.return_value = tune_out

            run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v0",
                    max_iterations=1,
                    max_proposal_attempts=2,
                    max_impl_attempts=1,
                ),
                workspace=workspace,
                run_name="e1_layout",
            )

        iter_dir = os.path.join(workspace, "e1_layout", "iteration_001")
        assert os.path.isdir(iter_dir)
        # Name-blind discovery: the glob prefix alone finds every attempt.
        attempts = sorted(d for d in os.listdir(iter_dir) if d.startswith("attempt_"))
        assert attempts == ["attempt_001_alpha_net", "attempt_002_beta_net"], attempts
        # Distinct directories — the failed candidate's directory survives
        # the successful one. This is what makes a died-at-validation
        # candidate discoverable at all.
        assert os.path.isdir(os.path.join(iter_dir, attempts[0]))
        assert os.path.isdir(os.path.join(iter_dir, attempts[1]))
