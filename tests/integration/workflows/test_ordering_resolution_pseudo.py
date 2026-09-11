"""V19 PR 2 P2-V1 — pseudo integration for ordering resolution.

Every resolution case is exercised DETERMINISTICALLY here so the
downstream P2-V2 Gate 2 smoke does not have to coax a real run into
producing a particular one.

Cases, one per test (design §7.1 "Resolution logic" + the operator's
rejection requirement):

  1. proposal wins   — agent proposes sequential, no override -> sequential
                       executes, source ``agent_proposal``.
  2. override wins   — agent proposes sequential, operator forces shuffle ->
                       shuffle executes, source ``operator_override``, and
                       the proposal is recorded but NOT reported as executed.
  3. default wins    — nothing proposed, nothing overridden -> shuffle,
                       source ``default``.
  4. rejected + no override — malformed proposal is recorded AS rejected
                       with its reason; default shuffle executes.
  5. rejected + override    — rejection still recorded; the override
                       executes and is never attributed to the agent.
  6. granularity     — two rounds of ONE iteration with different resolved
                       ordering produce two distinct keyed manifest entries.

The flow under test is the production one: real ``run_workflow`` (agents
mocked at the workflow boundary) and the real ``write_manifest`` the
chain runner uses. No real LLM, no real training.
"""

from __future__ import annotations

import contextlib
import json
import os
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import (
    ExperimentMemory,
    ExperimentRecord,
    HyperparamTuningInput,
    HyperparamTuningOutput,
)
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.ordering import resolve_ordering
from agent.schemas.proposal import ExpertAdvice, ProposalOutput
from agent.schemas.validator import ValidatorOutput
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from workflows.run_one_iteration import write_manifest
from tests.helpers.metric_fixtures import shipped_spec
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as a
#: REQUIRED keyword. The shipped TIDMAD spec is `higher`, so every expectation in
#: this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(shipped_spec())

SCOPE = list(range(20))
PERMUTATION = [4, 6, 5, 9, 7, 8, 0, 1, 2, 3, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]


# ---------------------------------------------------------------------------
# Mocked node outputs (same shapes the PR 1 pseudo harness uses)
# ---------------------------------------------------------------------------

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


def _record(exp_id: str, round_index: int, ordering) -> ExperimentRecord:
    """A record stamped exactly the way the tuner stamps one (nonet)."""
    return ExperimentRecord(
        exp_id=exp_id,
        status="success",
        model_type="punet",
        timestamp="2026-07-28 00:00:00",
        params={},
        denoising_score=1.0,
        memory=ExperimentMemory(
            expert_advice_followed="n/a", hypothesis="n/a", round_index=round_index
        ),
        proposed_order_strategy=ordering.proposed_strategy,
        proposed_file_order=ordering.proposed_file_order,
        ordering_proposal_rejected=ordering.proposal_rejected,
        ordering_proposal_rejection_reason=ordering.proposal_rejection_reason,
        override_order_strategy=ordering.override_strategy,
        override_file_order=ordering.override_file_order,
        resolved_order_strategy=ordering.resolved_strategy,
        resolved_file_order=ordering.resolved_file_order,
        ordering_resolution_source=ordering.resolution_source,
    )


def _tune_output(*records) -> HyperparamTuningOutput:
    return HyperparamTuningOutput(
        run_name="iter_001",
        model_type="punet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        best_denoising_score=1.0,
        all_records=list(records),
        started_at="2026-07-28 00:00:00",
        finished_at="2026-07-28 00:00:01",
    )


def _seed_source_run(workspace: str) -> str:
    """Write the seed tuning output iteration 1 loads, and return its data_dir.

    ``run_workflow`` at iteration 1 reads
    ``{data_dir}/{model}/{source_run}/agent/run_output_{source_run}_agent.json``
    before any node runs. Seeding it per-test keeps each case hermetic.
    """
    data_dir = os.path.join(workspace, "seed_data")
    agent_dir = os.path.join(data_dir, "punet", "v1", "agent")
    os.makedirs(agent_dir, exist_ok=True)
    with open(os.path.join(agent_dir, "run_output_v1_agent.json"), "w") as f:
        f.write(_tune_output().model_dump_json())
    return data_dir


def _run_iteration(workspace: str, tune_output, **override_kwargs):
    """Real run_workflow (agents mocked) + real write_manifest."""
    captured: list[HyperparamTuningInput] = []

    def _capture(inp):
        captured.append(inp)
        return tune_output

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
            launch=WorkflowLaunchConfig(
                data_dir=_seed_source_run(workspace),
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=1,
            ),
            workspace=workspace,
            run_name="iter_001",
            **override_kwargs,
        )

    iter_dir = os.path.join(workspace, "iter_001")
    model_dir = os.path.join(iter_dir, "iteration_001", "punet")
    os.makedirs(model_dir, exist_ok=True)
    with open(os.path.join(model_dir, "run_output_iter_001.json"), "w") as f:
        f.write(tune_output.model_dump_json())
    manifest = write_manifest(iter_dir, "iter_001", [tune_output])
    return captured[0], manifest


def _assert_agree(manifest, summary, *, resolved, source, index=0):
    """Record, manifest, and interpreter-facing summary must tell one story."""
    entry = manifest["ordering_by_experiment"][index]
    assert entry["resolved_order_strategy"] == resolved
    assert entry["ordering_resolution_source"] == source
    round_ordering = summary.round_ordering[index]
    assert round_ordering.resolved_order_strategy == resolved
    assert round_ordering.resolution_source == source


# ---------------------------------------------------------------------------
# Case 1 — proposal wins
# ---------------------------------------------------------------------------


def test_agent_proposal_wins_when_no_override(tmp_path):
    ordering = resolve_ordering(
        resolved_scope=SCOPE,
        proposed_strategy="sequential",
        proposed_file_order=PERMUTATION,
    )
    output = _tune_output(_record("r1", 1, ordering))
    tune_input, manifest = _run_iteration(str(tmp_path), output)

    # The workflow passed NO override down, so the agent decides.
    assert tune_input.order_strategy_override is None
    assert tune_input.file_order_override is None

    summary = tuning_output_to_model_run_summary(output, order=_STEP09A_ORDER)
    _assert_agree(manifest, summary, resolved="sequential", source="agent_proposal")
    assert manifest["ordering_by_experiment"][0]["resolved_file_order"] == PERMUTATION


# ---------------------------------------------------------------------------
# Case 2 — override wins
# ---------------------------------------------------------------------------


def test_operator_override_wins_and_is_not_attributed_to_the_agent(tmp_path):
    ordering = resolve_ordering(
        resolved_scope=SCOPE,
        proposed_strategy="sequential",
        proposed_file_order=PERMUTATION,
        override_strategy="shuffle",
    )
    output = _tune_output(_record("r1", 1, ordering))
    tune_input, manifest = _run_iteration(str(tmp_path), output, order_strategy_override="shuffle")

    assert tune_input.order_strategy_override == "shuffle"

    summary = tuning_output_to_model_run_summary(output, order=_STEP09A_ORDER)
    _assert_agree(manifest, summary, resolved="shuffle", source="operator_override")

    entry = manifest["ordering_by_experiment"][0]
    # The proposal is preserved as context and is clearly NOT what ran.
    assert entry["proposed_order_strategy"] == "sequential"
    assert entry["resolved_file_order"] is None
    assert summary.round_ordering[0].proposed_order_strategy == "sequential"


# ---------------------------------------------------------------------------
# Case 3 — default wins
# ---------------------------------------------------------------------------


def test_default_shuffle_when_nothing_is_proposed_or_overridden(tmp_path):
    ordering = resolve_ordering(resolved_scope=SCOPE)
    output = _tune_output(_record("r1", 1, ordering))
    tune_input, manifest = _run_iteration(str(tmp_path), output)

    assert tune_input.order_strategy_override is None
    summary = tuning_output_to_model_run_summary(output, order=_STEP09A_ORDER)
    _assert_agree(manifest, summary, resolved="shuffle", source="default")
    assert manifest["ordering_by_experiment"][0]["proposed_order_strategy"] is None
    assert manifest["ordering_by_experiment"][0]["ordering_proposal_rejected"] is False


# ---------------------------------------------------------------------------
# Cases 4 + 5 — a rejected proposal survives to every consumer
# ---------------------------------------------------------------------------


def _rejected_ordering(**override):
    from agent.schemas.hyperparam_tuning import ExperimentPlan

    _plan, rejected = ExperimentPlan.parse_with_fallback(
        {"model_type": "punet", "order_strategy": "sequential", "file_order": [4, 4, 4]}
    )
    assert rejected is not None
    return resolve_ordering(resolved_scope=SCOPE, rejected_proposal=rejected, **override)


def test_rejected_proposal_without_override_falls_back_and_is_recorded(tmp_path):
    ordering = _rejected_ordering()
    output = _tune_output(_record("r1", 1, ordering))
    _tune_input, manifest = _run_iteration(str(tmp_path), output)

    summary = tuning_output_to_model_run_summary(output, order=_STEP09A_ORDER)
    _assert_agree(manifest, summary, resolved="shuffle", source="default")

    entry = manifest["ordering_by_experiment"][0]
    assert entry["ordering_proposal_rejected"] is True
    assert "duplicate" in entry["ordering_proposal_rejection_reason"]
    assert entry["proposed_order_strategy"] == "sequential"
    assert summary.round_ordering[0].proposal_rejected is True


def test_rejected_proposal_with_override_records_both(tmp_path):
    ordering = _rejected_ordering(override_strategy="sequential", override_file_order=PERMUTATION)
    output = _tune_output(_record("r1", 1, ordering))
    _tune_input, manifest = _run_iteration(
        str(tmp_path),
        output,
        order_strategy_override="sequential",
        file_order_override=PERMUTATION,
    )

    summary = tuning_output_to_model_run_summary(output, order=_STEP09A_ORDER)
    _assert_agree(manifest, summary, resolved="sequential", source="operator_override")

    entry = manifest["ordering_by_experiment"][0]
    assert entry["ordering_proposal_rejected"] is True
    assert entry["resolved_file_order"] == PERMUTATION
    # The override is the operator's, never the agent's.
    assert entry["proposed_file_order"] == [4, 4, 4]
    assert entry["proposed_file_order"] != entry["resolved_file_order"]


# ---------------------------------------------------------------------------
# Case 6 — per-round granularity end to end
# ---------------------------------------------------------------------------


def test_two_rounds_with_different_ordering_stay_distinct_end_to_end(tmp_path):
    """The granularity rule, through the real manifest writer and the real
    interpreter summary builder."""
    seq = resolve_ordering(
        resolved_scope=SCOPE, proposed_strategy="sequential", proposed_file_order=PERMUTATION
    )
    shuf = resolve_ordering(resolved_scope=SCOPE)
    output = _tune_output(_record("r1", 1, seq), _record("r2", 2, shuf))
    _tune_input, manifest = _run_iteration(str(tmp_path), output)

    assert len(manifest["ordering_by_experiment"]) == 2
    summary = tuning_output_to_model_run_summary(output, order=_STEP09A_ORDER)
    _assert_agree(manifest, summary, resolved="sequential", source="agent_proposal", index=0)
    _assert_agree(manifest, summary, resolved="shuffle", source="default", index=1)
    assert [e["exp_id"] for e in manifest["ordering_by_experiment"]] == ["r1", "r2"]


def test_manifest_block_survives_to_disk(tmp_path):
    """The manifest is a cross-process handoff, so the block must serialize."""
    ordering = resolve_ordering(
        resolved_scope=SCOPE, proposed_strategy="sequential", proposed_file_order=PERMUTATION
    )
    output = _tune_output(_record("r1", 1, ordering))
    _run_iteration(str(tmp_path), output)
    with open(os.path.join(str(tmp_path), "iter_001", "manifest.json")) as f:
        on_disk = json.load(f)
    assert on_disk["ordering_by_experiment"][0]["resolved_file_order"] == PERMUTATION
    assert on_disk["ordering_by_experiment"][0]["ordering_resolution_source"] == "agent_proposal"
