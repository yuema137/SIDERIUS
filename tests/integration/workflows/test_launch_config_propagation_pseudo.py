"""V19 propagation audit — run_workflow → tuner input, VALUE level.

Layer 3 of the launch-critical propagation chain (layers 1-2 are
covered by tests/unit/sdsc_submission_scripts/
test_gate0_config_propagation.py at the shell/CLI boundary):

    run_workflow(sentinels) → [real workflow code, real protocol
    local_validated_model] → HyperparamTuningInput captured at the
    tuner boundary → run-invariants lock on disk

Every launch-critical family carries a SENTINEL value that cannot be
confused with any layer's default (operator audit spec §4.1/§4.2/§4.3).
The workflow runs REAL code with only the five agents mocked at the
workflow boundary (the same harness as
tests/integration/workflows/test_chain_incumbent_pseudo.py) — the
propagation layers under audit are NOT mocked. No LLM, no training,
no GPU.

The workflow receives transit settings through WorkflowLaunchConfig and run
scope/Health authorities as direct arguments. The test binds a complete synthetic
20-partition task so exact descending scope sentinels exercise supported input.
The recorded boundary and lock assertions remain independent of that fixture.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
)
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ExpertAdvice, ProposalOutput
from agent.schemas.validator import ValidatorOutput
from execute_tools.dataset_config import DataScope
from tests.helpers.tuner_composed_fixture import make_tuner_composition
from tests.helpers.two_family_profile import make_two_family_profile
from tests.integration.workflows.test_chain_candidate_graduation import _llm_config_pseudo
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings


@pytest.fixture
def propagation_composition(tmp_path, offline_workflow):
    """Explicit 20-partition task for indexed-scope transport; no dataset reads."""
    pack = tmp_path / "task"
    pack.mkdir()
    initial = make_tuner_composition(pack)
    # This witness targets the still-supported indexed-file scope contract.
    # Both the synthetic data-path fixture and this profile declare 20 partitions.
    profile = make_two_family_profile(num_files=20)
    Path(initial.provenance.source_paths["dataset_profile"]).write_text(
        json.dumps(profile.to_wire())
    )
    composition = compose_run_task_bindings(initial.provenance.manifest_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    with bind_run_task_composition(composition, physical_data_root=str(data_root)):
        yield composition


# --------------------------------------------------------------------------
# Sentinels — one distinctive value per launch-critical setting. None of
# these equals the corresponding default at ANY layer (checked against the
# schema/workflow/CLI defaults when chosen).
# --------------------------------------------------------------------------

SENTINELS = {
    # portions
    "trial_portion": 0.037,
    "train_portion": 0.93,
    "eval_portion": 0.017,
    "formal_portion": 0.041,
    "formal_train_portion": 0.97,
    "formal_eval_portion": 0.019,
    # time/VRAM budgets
    "trial_time_budget_minutes": 7.0,
    "formal_time_budget_minutes": 31.0,
    "trial_vram_budget_gb": 23.0,
    "formal_vram_budget_gb": 25.0,
    # runtime control (audit spec §4.1 values)
    "runtime_watchdog_enabled": True,
    "runtime_watchdog_deadline_policy": "forecast-tightening-v1",
    "runtime_safety_factor": 1.51,
    "runtime_trial_safety_factor": 3.11,
    "runtime_formal_safety_factor": 2.22,
    "runtime_watchdog_safety_factor": 3.57,
    "runtime_watchdog_floor_seconds": 137.0,
    # incumbent deltas (PR 1)
    "skip_formal_min_delta": 0.013,
    "bypass_formal_time_budget_min_delta": 0.57,
    "enable_chain_incumbent_formal_gates": True,
    # structured feedback (PR 3; audit spec §4.3 values)
    "enable_structured_health_feedback": True,
    "health_feedback_history_window_iterations": 7,
    "health_feedback_history_max_entries_per_model": 11,
    # execution controls
    "max_rounds": 4,
    "max_epochs": 2,
    "force_formal_round": True,
}

# Ordering sentinel (audit spec §4.2): an explicit DESCENDING permutation —
# any layer that re-sorts or falls back to default ordering breaks it.
ORDER_SENTINEL = [19, 18, 17, 16, 15]
SCOPE_SENTINEL = "15-19"
HEALTH_FILES_SENTINEL = [15, 16, 17, 18, 19]
ADVICE_TUNE_SENTINEL = "SENTINEL-HUMAN-ADVICE-TUNE-77140"
ADVICE_INTERP_SENTINEL = "SENTINEL-HUMAN-ADVICE-INTERP-77141"
ADVICE_PROPOSE_SENTINEL = "SENTINEL-HUMAN-ADVICE-PROPOSE-77142"

_MINIMAL_TUNE_OUT = HyperparamTuningOutput(
    run_name="iter_001",
    model_type="punet",
    file_index=15,
    status="completed",
    completed_rounds=0,
    total_attempts=0,
    best_denoising_score=None,
    all_records=[],
    started_at="2026-07-30 00:00:00",
    finished_at="2026-07-30 00:00:01",
)

_INTERP_OUT = InterpretationOutput(
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
_PROPOSAL_OUT = ProposalOutput(
    model_name="punet",
    model_description="punet",
    mathematical_definition="—",
    motivation="—",
    expert_advice=ExpertAdvice(
        focus_areas=["—"],
        constraints=["—"],
        known_failures=["—"],
        suggested_directions=["—"],
        rationale="pseudo test — no real advice",
    ),
    baseline_config={
        "model_config": {},
        "train_config": {},
        "loss_config": {"loss_type": "focal"},
    },
)
_IMPL_OUT = ImplementorOutput(
    model_type="punet",
    description_file_path="/tmp/punet.md",
    model_file_path="/tmp/punet.py",
    test_file_path="/tmp/test_punet.py",
    config_fields={"n_layers": 4},
    model_description="punet stub for pseudo test",
    mathematical_definition="—",
)
_VALID_OUT = ValidatorOutput(
    passed=True,
    model_type="punet",
    plugin_registered=True,
    tests_passed=True,
    description_valid=True,
    config_fields_valid=True,
    instantiation_passed=True,
    gradient_check_passed=True,
    llm_review_passed=True,
)


def _run_with_sentinels(workspace: str, composition):
    """Returns (tune_input, interp_input, propose_input) captured at the
    three agent boundaries."""
    captured: list[HyperparamTuningInput] = []

    def _capture(inp):
        captured.append(inp)
        return _MINIMAL_TUNE_OUT.model_copy(
            update={
                "task_composition_fingerprint": composition.semantic_fingerprint,
                "metric_spec": composition.metric.spec,
            }
        )

    with contextlib.ExitStack() as stack:
        MockInterp = stack.enter_context(
            patch("workflows.model_exploration.ResultInterpretationAgent")
        )
        MockPropose = stack.enter_context(patch("workflows.model_exploration.MLModelProposalAgent"))
        MockImpl = stack.enter_context(patch("workflows.model_exploration.MLModelImplementor"))
        MockValid = stack.enter_context(patch("workflows.model_exploration.MLCodeValidatorAgent"))
        MockTune = stack.enter_context(patch("workflows.model_exploration.HyperparamTuningAgent"))
        stack.enter_context(
            patch("workflows.model_exploration._register_plugin", return_value=None)
        )
        stack.enter_context(
            patch("workflows.model_exploration._promote_model_to_global", return_value=None)
        )
        stack.enter_context(
            patch("workflows.model_exploration._promote_loss_to_global", return_value=None)
        )
        MockInterp.return_value.run.return_value = _INTERP_OUT
        MockPropose.return_value.run.return_value = _PROPOSAL_OUT
        MockImpl.return_value.run.return_value = _IMPL_OUT
        MockValid.return_value.run.return_value = _VALID_OUT
        MockTune.return_value.run.side_effect = _capture

        run_workflow(
            task_composition=composition,
            llm_config=_llm_config_pseudo(),
            launch=WorkflowLaunchConfig(
                data_dir="/tmp/data",
                model_types=["punet"],
                source_run_name="v1",
                start_iteration=1,
                max_iterations=1,
                source_paths=[],
                human_advice_tune=ADVICE_TUNE_SENTINEL,
                human_advice_interpret=ADVICE_INTERP_SENTINEL,
                human_advice_propose=ADVICE_PROPOSE_SENTINEL,
                **{
                    key: value
                    for key, value in SENTINELS.items()
                    if key != "enable_structured_health_feedback"
                },
            ),
            workspace=workspace,
            run_name="iter_001",
            data_scope=DataScope.from_cli(SCOPE_SENTINEL),
            health_gate_files=list(HEALTH_FILES_SENTINEL),
            health_gate_enabled=True,
            order_strategy_override="sequential",
            file_order_override=list(ORDER_SENTINEL),
            enable_structured_health_feedback=SENTINELS["enable_structured_health_feedback"],
        )
        interp_input = MockInterp.return_value.run.call_args[0][0]
        propose_input = MockPropose.return_value.run.call_args[0][0]
    assert len(captured) == 1
    return captured[0], interp_input, propose_input


@pytest.mark.dual_mode
def test_every_sentinel_reaches_the_tuner_input_and_the_lock(tmp_path, propagation_composition):
    ws = str(tmp_path / "sentinel_ws")
    os.makedirs(ws)
    tune_input, interp_input, propose_input = _run_with_sentinels(ws, propagation_composition)

    # -- typed tuner input: exact sentinel equality, field by field -------
    for name, expected in SENTINELS.items():
        got = getattr(tune_input, name)
        assert got == expected, f"{name}: tuner input has {got!r}, sent {expected!r}"

    # ordering/scope: the exact descending permutation survives — nothing
    # re-sorted it and nothing replaced it with a default order
    assert tune_input.order_strategy_override == "sequential"
    assert tune_input.file_order_override == ORDER_SENTINEL
    assert tune_input.data_scope is not None
    assert tune_input.data_scope.file_indices == [15, 16, 17, 18, 19]
    assert tune_input.health_gate_files == HEALTH_FILES_SENTINEL
    assert tune_input.health_gate_enabled is True

    # advice: the tune-stage human advice string reaches the tuner
    assert tune_input.human_advice is not None
    assert ADVICE_TUNE_SENTINEL in str(tune_input.human_advice)

    # -- interpreter boundary: feedback policy + typed-history channel +
    # stage-scoped advice (production renderer inputs, §3.4) -------------
    assert interp_input.enable_structured_health_feedback is True
    assert interp_input.health_feedback_history_window_iterations == 7
    assert interp_input.health_feedback_history_max_entries_per_model == 11
    assert ADVICE_INTERP_SENTINEL in str(interp_input.human_advice)
    assert ADVICE_TUNE_SENTINEL not in str(interp_input.human_advice)

    # -- proposer boundary: feedback flag + stage-scoped advice ----------
    # Advice reaches the proposer through the Commit-2d channel: the
    # protocol wraps human_advice into expert_context as a source="human"
    # ExpertContextItem (ml_result_interp_to_ml_model_propose.py:142-169)
    # and leaves the legacy ProposalInput.human_advice field unset.
    assert propose_input.enable_structured_health_feedback is True
    human_items = [item for item in propose_input.expert_context if item.source == "human"]
    assert human_items, "operator advice never reached the proposer context"
    joined = " ".join(item.content for item in human_items)
    assert ADVICE_PROPOSE_SENTINEL in joined
    assert ADVICE_INTERP_SENTINEL not in joined
    assert any(card.agent_name == "human" for card in propose_input.agent_cards)

    # -- artifact side: run-invariants lock records the same policy -------
    lock_path = os.path.join(ws, "run_invariants_lock.json")
    assert os.path.exists(lock_path), "run-invariants lock not written"
    lock = json.loads(open(lock_path).read())
    assert lock["runtime_watchdog_deadline_policy"] == "forecast-tightening-v1"
    lock_text = json.dumps(lock)
    flat = json.dumps(lock)
    # ordering + feedback policy + scope are lock-pinned; assert exact values
    assert '"sequential"' in flat
    assert "[19, 18, 17, 16, 15]" in flat or "19, 18, 17, 16, 15" in lock_text
    assert '"health_feedback_history_window_iterations": 7' in flat
    assert '"health_feedback_history_max_entries_per_model": 11' in flat
    assert (
        '"structured_health_feedback_enabled": true' in flat
        or '"enable_structured_health_feedback": true' in flat
    )


@pytest.mark.dual_mode
def test_off_default_parity_no_silent_activation(tmp_path, propagation_composition):
    """OFF/default parity (audit spec §4.3): omitting every V19 flag gives
    feedback OFF with 3/8 retention and no watchdog override at the tuner
    boundary — a legacy-style invocation is NOT silently upgraded."""
    composition = propagation_composition
    ws = str(tmp_path / "default_ws")
    os.makedirs(ws)
    captured: list[HyperparamTuningInput] = []

    def _capture(inp):
        captured.append(inp)
        return _MINIMAL_TUNE_OUT.model_copy(
            update={
                "task_composition_fingerprint": composition.semantic_fingerprint,
                "metric_spec": composition.metric.spec,
            }
        )

    with contextlib.ExitStack() as stack:
        MockInterp = stack.enter_context(
            patch("workflows.model_exploration.ResultInterpretationAgent")
        )
        MockPropose = stack.enter_context(patch("workflows.model_exploration.MLModelProposalAgent"))
        MockImpl = stack.enter_context(patch("workflows.model_exploration.MLModelImplementor"))
        MockValid = stack.enter_context(patch("workflows.model_exploration.MLCodeValidatorAgent"))
        MockTune = stack.enter_context(patch("workflows.model_exploration.HyperparamTuningAgent"))
        stack.enter_context(
            patch("workflows.model_exploration._register_plugin", return_value=None)
        )
        stack.enter_context(
            patch("workflows.model_exploration._promote_model_to_global", return_value=None)
        )
        stack.enter_context(
            patch("workflows.model_exploration._promote_loss_to_global", return_value=None)
        )
        MockInterp.return_value.run.return_value = _INTERP_OUT
        MockPropose.return_value.run.return_value = _PROPOSAL_OUT
        MockImpl.return_value.run.return_value = _IMPL_OUT
        MockValid.return_value.run.return_value = _VALID_OUT
        MockTune.return_value.run.side_effect = _capture

        run_workflow(
            task_composition=composition,
            llm_config=_llm_config_pseudo(),
            launch=WorkflowLaunchConfig(
                data_dir="/tmp/data",
                model_types=["punet"],
                source_run_name="v1",
                start_iteration=1,
                max_iterations=1,
                source_paths=[],
            ),
            workspace=ws,
            run_name="iter_001",
        )
    (tune_input,) = captured
    assert tune_input.enable_structured_health_feedback is False
    assert tune_input.health_feedback_history_window_iterations == 3
    assert tune_input.health_feedback_history_max_entries_per_model == 8
    assert tune_input.runtime_watchdog_safety_factor is None
    assert tune_input.enable_chain_incumbent_formal_gates is False
    assert tune_input.order_strategy_override is None
    assert tune_input.file_order_override is None
