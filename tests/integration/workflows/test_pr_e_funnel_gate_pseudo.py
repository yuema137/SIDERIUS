"""V21 PR E — the REQUIRED bounded pseudo-mode complete-funnel Gate (DC-2).

**This test is a merge requirement**, unlike PR D's optional live check.
It exercises, as ONE path through the real `run_workflow`:

```text
real proposer run()      -> mint + proposal_{run}.json      (real persistence)
real protocols           -> candidate_id inside the objects
real implementor run()   -> plugin file + implementor JSON  (real persistence)
real validator run()     -> verdict + validation JSON       (real persistence)
real tuner run()         -> records + run_output JSON       (K9 pseudo stack:
                            RecordingLLMBridge + RecordingSandbox — canned
                            LLM/training results, REAL tuner control flow,
                            REAL _emit_record stamping, REAL output echo)
filesystem discovery     -> attempt_* glob, name-blind
read-side join           -> assemble_iteration_funnel on candidate_id
derived complete row     -> fan-in of all tuner records
```

No real GPU. No real LLM. The scientific outcome (canned scores) is never
the oracle — the assertion surface is the instrumentation path. Validator
subprocess results and tuner preflight measurements are supplied explicitly;
the implementor smoke check and generated-model registration run locally.
Accidental provider calls, hardware discovery and subprocesses are refused.

LLM boundaries are mocked at the BRIDGE level so every node's real
``run()`` body executes, including its persistence block; the interp
agent alone is class-patched (interpretation is not a funnel stage). The
tuner reuses the K.9 canned choreography (3 plans + 2 reflects → 3
records: 1 OOM-skip + 2 successes), which also gives the Gate a
non-trivial FAN-IN: one candidate, three records.

Design doc: ``docs/design/v21_priorities/pr_e_proposal_scale_funnel.md``
Commit E4 / §12 of the implementation mandate.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationOutput
from execute_tools.funnel_assembly import assemble_iteration_funnel
from workflows.run_config import WorkflowLaunchConfig

pytestmark = pytest.mark.dual_mode

_MODEL_TYPE = "pe_wavenet_delta"  # matches the K.9 canned tuner choreography
_TUNER_PSEUDO_FOLDER = "ml_hyperparameter_tune_agent_k9_invented"

_PROPOSER_REASONING = "Use a two-layer tabular classifier for the funnel gate."
_PROPOSER_COMMIT = {
    "model_name": _MODEL_TYPE,
    "output_type": "classifier",
    "model_description": "A two-layer tabular classifier for the E4 funnel gate.",
    "mathematical_definition": "y = W_2 relu(W_1 x + b_1) + b_2",
    "motivation": "Deterministic funnel-gate candidate.",
    "expert_advice": {
        "focus_areas": ["funnel"],
        "constraints": ["none"],
        "known_failures": ["none"],
        "suggested_directions": ["none"],
        "rationale": "pseudo gate",
    },
    "baseline_config": {
        "model_config": {"hidden_dim": 128},
        "train_config": {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cuda"},
        "loss_config": {"loss_type": "ce"},
    },
    "parameter_count_estimate": 5_000_000,
}

_INTERP = InterpretationOutput(
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


def _disable_sleeps(monkeypatch):
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *a, **kw: None)


def _real_proposer_cls(captured_system_prompts: list[str] | None = None):
    """Real proposer, mocked bridge.

    ``captured_system_prompts`` (PR 01b / S1-C) collects every SYSTEM
    prompt the proposer actually hands to the bridge, so the caller can
    assert on the bytes the LLM boundary received.
    """
    from nodes.ml_model_proposal_agent import MLModelProposalAgent

    class _RealProposerMockBridge:
        """Constructs the REAL proposer with a mocked LLM bridge, so the
        real run() executes: parse -> MINT -> persist."""

        def __init__(self, *a, **kw):
            with patch("nodes.ml_model_proposal_agent.LLMBridge") as MockBridge:
                MockBridge.return_value.generate_text.return_value = _PROPOSER_REASONING
                MockBridge.return_value.generate.return_value = _PROPOSER_COMMIT
                self._agent = MLModelProposalAgent(provider="gemini", model_id="pseudo")
                self._agent.bridge = MockBridge.return_value
            self.bridge = self._agent.bridge

        def run(self, inp):
            output = self._agent.run(inp)
            if captured_system_prompts is not None:
                for call in self.bridge.generate_text.call_args_list:
                    captured_system_prompts.append(call.args[0])
            return output

    return _RealProposerMockBridge


def _real_implementor_cls():
    from nodes.ml_model_implementor import MLModelImplementor

    class _RealImplementorMockBridge:
        def __init__(self, *a, **kw):
            agent = MLModelImplementor.__new__(MLModelImplementor)
            agent.bridge = MagicMock()
            agent._registry = MagicMock()
            agent.bridge.generate_text.return_value = "Map four float features to two class logits."
            agent.bridge.generate.return_value = {
                "extra_imports": "",
                "config_fields_code": "    hidden_dim: int = Field(default=128, ge=8, le=8192)",
                "config_fields": {"hidden_dim": 128},
                "init_body": "        self.net = nn.Sequential(nn.Linear(4, config.hidden_dim), nn.ReLU(), nn.Linear(config.hidden_dim, 2))",
                "forward_body": "        return self.net(x.float())",
            }
            self._agent = agent
            self.bridge = agent.bridge

        def run(self, inp):
            return self._agent.run(inp)

    return _RealImplementorMockBridge


def _real_validator_cls():
    from nodes.ml_code_validator_agent import MLCodeValidatorAgent

    class _RealValidatorMockBridge:
        def __init__(self, *a, **kw):
            agent = MLCodeValidatorAgent.__new__(MLCodeValidatorAgent)
            agent.bridge = MagicMock()
            agent.bridge.generate.return_value = {
                "passed": True,
                "spec_alignment": True,
                "implementation_issues": [],
                "trainability_concerns": [],
                "notes": "pseudo gate review",
            }
            self._agent = agent
            self.bridge = agent.bridge

        def run(self, inp):
            assert Path(inp.test_file_path).is_file()
            with patch(
                "nodes.ml_code_validator_agent.ml_code_validator_agent._run_tests",
                return_value=(True, "Supplied validator test result; no subprocess executed."),
            ) as run_tests:
                output = self._agent.run(inp)
            run_tests.assert_called_once_with(inp.test_file_path)
            return output

    return _RealValidatorMockBridge


def _real_tuner_cls(workspace: str, run_name: str, monkeypatch, hardware):
    from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.tuner_composed_effects import (
        composed_tuner_effects,
        recording_sandbox_for_attempts,
    )

    class _RealTunerPseudoStack:
        def __init__(self, *a, **kw):
            self.bridge = bridge = RecordingLLMBridge.for_agent(_TUNER_PSEUDO_FOLDER)
            self.sandbox = sandbox = recording_sandbox_for_attempts(
                _MODEL_TYPE, base_dir=workspace, run_name=run_name, completed_attempts=2
            )
            self._agent = HyperparamTuningAgent(
                bridge_factory=lambda **_kw: bridge,
                sandbox_factory=lambda **_kw: sandbox,
            )

        def run(self, inp):
            with composed_tuner_effects(
                monkeypatch,
                sandbox=self.sandbox,
                bridge=self.bridge,
                expected_attempts=3,
                hardware_context=hardware,
                preflight_results=[
                    ("MEASURED_PEAK_ABOVE_VRAM_CAP", 0.4),
                    ("COMPLETED_MEASUREMENT", 0.1),
                    ("COMPLETED_MEASUREMENT", 0.1),
                ],
            ):
                return self._agent.run(inp)

    return _RealTunerPseudoStack


@pytest.fixture
def funnel_composition(tmp_path):
    from tests.helpers.tuner_composed_fixture import _isolated_registrations, make_tuner_composition
    from workflows.task_composition import bind_run_task_composition

    with _isolated_registrations():
        composition = make_tuner_composition(tmp_path)
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        with bind_run_task_composition(composition, physical_data_root=str(data_dir)):
            yield composition


def test_complete_funnel_row_from_one_pseudo_iteration(tmp_path, monkeypatch, funnel_composition):
    from tests.helpers.tuner_composed_effects import (
        _install_effect_backstop,
        synthetic_cuda_context,
    )

    _install_effect_backstop(monkeypatch)
    hardware = synthetic_cuda_context(monkeypatch)
    monkeypatch.setattr(
        "workflows.model_exploration.get_or_create_hardware_context",
        lambda *args, **kwargs: hardware,
    )
    _disable_sleeps(monkeypatch)

    workspace = str(tmp_path)
    run_name = "e4_gate"
    proposer_system_prompts: list[str] = []

    # Step 0 seed: run_workflow loads the source model's prior output
    # before any agent runs.
    seed_dir = tmp_path / "data" / "punet" / "v0" / "agent"
    seed_dir.mkdir(parents=True)
    (seed_dir / "run_output_v0_agent.json").write_text(
        HyperparamTuningOutput(
            task_composition_fingerprint=funnel_composition.semantic_fingerprint,
            metric_spec=funnel_composition.metric.spec,
            run_name="v0",
            model_type="punet",
            file_index=6,
            status="completed",
            completed_rounds=0,
            total_attempts=0,
            all_records=[],
            started_at="2026-08-08 00:00:00",
            finished_at="2026-08-08 00:00:01",
            # DS5 run-invariants: the seed must match this run's declared
            # gate posture, or ingress refuses it (the guard working).
            health_gate_enabled=False,
        ).model_dump_json()
    )

    from workflows.model_exploration import run_workflow

    with contextlib.ExitStack() as stack:
        MockInterp = stack.enter_context(
            patch("workflows.model_exploration.ResultInterpretationAgent")
        )
        MockInterp.return_value.run.return_value = _INTERP
        stack.enter_context(
            patch(
                "workflows.model_exploration.MLModelProposalAgent",
                _real_proposer_cls(proposer_system_prompts),
            )
        )
        stack.enter_context(
            patch("workflows.model_exploration.MLModelImplementor", _real_implementor_cls())
        )
        stack.enter_context(
            patch("workflows.model_exploration.MLCodeValidatorAgent", _real_validator_cls())
        )
        stack.enter_context(
            patch(
                "workflows.model_exploration.HyperparamTuningAgent",
                _real_tuner_cls(workspace, run_name, monkeypatch, hardware),
            )
        )
        # Retain real registration of the generated tabular model in the
        # temporary workspace. Global-library promotion is outside this witness.
        stack.enter_context(
            patch("workflows.model_exploration._promote_model_to_global", return_value=None)
        )
        stack.enter_context(
            patch("workflows.model_exploration._promote_loss_to_global", return_value=None)
        )

        from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig

        run_workflow(
            task_composition=funnel_composition,
            llm_config=WorkflowLLMConfig(tune=TunerLLMConfig(planner_strategy="native-timing-v1")),
            launch=WorkflowLaunchConfig(
                data_dir=str(tmp_path / "data"),
                model_types=["punet"],
                source_run_name="v0",
                max_iterations=1,
                max_proposal_attempts=1,
                max_impl_attempts=1,
                max_rounds=2,
                is_trial=True,
                trial_portion=0.05,
                train_portion=0.1,
                eval_portion=0.05,
                trial_vram_budget_gb=0.3,
                trial_time_budget_minutes=None,
            ),
            workspace=workspace,
            run_name=run_name,
            trial_strategy="snapshot",
            eval_strategy="snapshot",
            health_gate_enabled=False,
        )

    # ---- PR 01b (S1-C): the workflow actually DELIVERS the task config ---
    # `run_workflow` injects the shipped description post-hoc, right
    # before the proposer runs (`model_exploration.py`, the
    # `propose_input.task_description = get_task_description(_task_cfg)`
    # hop). Nothing else in the repository exercises that hop through the
    # real workflow: every unit-tier proposer test builds its own
    # ProposalInput, so deleting the injection leaves them all green.
    #
    # Mutation M-6 (parent §15) is exactly that deletion, and this is its
    # RED target. It is asserted on whichever proposer SYSTEM surface this
    # Gate renders — the LEGACY reasoning prompt, because the Gate passes
    # a tune-only `llm_config` (`propose=None` selects the legacy path). The
    # three-stage pipeline JOIN is proven separately by the S1-C unit
    # captures, the six regenerated PB-3 goldens, and Checkpoint C.
    from workflows.task_config import get_task_description, load_task_config

    shipped_description = get_task_description(load_task_config())
    assert proposer_system_prompts, "the real proposer never reached the LLM boundary"
    assert any(shipped_description in system for system in proposer_system_prompts), (
        "the workflow's task-config injection did not reach the proposer's "
        "rendered SYSTEM prompt — the shipped task description is missing"
    )

    iter_dir = os.path.join(workspace, run_name, "iteration_001")

    # ---- The on-disk stage artifacts all carry ONE minted id -------------
    attempts = [d for d in sorted(os.listdir(iter_dir)) if d.startswith("attempt_")]
    assert attempts == [f"attempt_001_{_MODEL_TYPE}"]
    attempt_dir = Path(iter_dir) / attempts[0]

    # S2 / U6 (#256): the implementor/validation artifacts of the TERMINAL
    # implement→validate attempt live in the nested `impl_KKK/`; the
    # proposal stays at the attempt level. Resolved through the one authority
    # the funnel itself uses.
    from execute_tools.impl_attempts import stage_artifact_dir

    stage_dir = Path(stage_artifact_dir(str(attempt_dir)))
    minted: set[str] = set()
    for stem, where in (
        ("proposal", attempt_dir),
        ("implementor", stage_dir),
        ("validation", stage_dir),
    ):
        payload = json.loads((where / f"{stem}_{run_name}.json").read_text())
        assert isinstance(payload.get("candidate_id"), str), f"{stem} JSON lost the id"
        minted.add(payload["candidate_id"])
    assert len(minted) == 1, f"stage artifacts disagree on identity: {minted}"
    (candidate_id,) = minted
    assert candidate_id.startswith("cand_")

    run_output_path = Path(iter_dir) / _MODEL_TYPE / f"run_output_{run_name}.json"
    assert run_output_path.is_file(), "the real tuner did not persist its output"
    run_output = json.loads(run_output_path.read_text())
    assert run_output["candidate_id"] == candidate_id
    assert len(run_output["all_records"]) == 3  # K.9: 1 OOM-skip + 2 successes
    for rec in run_output["all_records"]:
        assert rec["candidate_id"] == candidate_id

    # ---- Read-side join: one complete row, correct fan-in ----------------
    funnel = assemble_iteration_funnel(iter_dir)
    assert funnel.discoverable is True
    assert len(funnel.rows) == 1 and not funnel.unjoinable
    row = funnel.rows[0]
    assert row.candidate_id == candidate_id
    assert row.stopped_at_stage is None, "a complete candidate stopped nowhere"
    assert row.incomplete_stages == []
    assert row.tuner_record_count == 3
    # O-E-6 convention-explicit columns, each from its native owner:
    assert row.proposed_trainable_parameter_count_estimate == 5_000_000
    assert row.implemented_total_parameter_count is not None
    assert row.implemented_trainable_parameter_count is not None
    # The K.9 canned rounds: OOM-skip carries no model_params; successes do.
    assert len(row.trained_trainable_parameter_counts) == 3
    assert row.unreadable == []
