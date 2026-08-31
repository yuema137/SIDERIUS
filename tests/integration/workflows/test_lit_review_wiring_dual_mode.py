"""Dual-mode integration tests for the Commit 6 lit-review workflow wiring.

Covers the workflow-level concerns deferred from File 1:
  * ``lit_review_config_path`` passthrough — the operator-supplied YAML at
    a non-default path drives ``LiteratureReviewInput.root_papers``.
  * ``lit_review_enabled=False`` tolerance — when the gate is off, the
    YAML is NEVER opened (a non-existent path raises NO error).
  * Channels-reach-proposer smoke — when lit-review fires, its canned
    ``LiteratureReviewOutput`` channels (agent_cards + expert_context)
    reach the ``ProposalInput`` the proposer receives.

Pattern mirrors ``test_n_recent_gate_exhaustions_dual_mode.py``: patch all
5 node agents, mock ``MLLiteratureReviewAgent.run`` to return a canned
output, capture the proposer's input for post-run assertions.

Run with:
  .venv/bin/pytest tests/integration/workflows/test_lit_review_wiring_dual_mode.py -v
"""

from __future__ import annotations

import json
import os
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import AgentCard, ExpertContextItem

# Reuse the existing dual-mode factories.
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tuning_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.llm_config import (
    LitReviewLLMConfig,
    NodeLLMConfig,
    ProposalLLMConfig,
    TunerLLMConfig,
    WorkflowLLMConfig,
)
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

pytestmark = pytest.mark.dual_mode

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "synthetic_masked_regression.yaml"


@pytest.fixture(autouse=True)
def _restore_health_plugin_globals():
    """Keep the legacy and composed parameter cells run-isolated."""
    from execute_tools.health_checks import _plugin_binding
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY

    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _composition_context(composition, data_dir: str):
    if composition is None:
        return nullcontext()
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    return bind_run_task_composition(composition, physical_data_root=data_dir)


def _stamp_seed_metric(tmp_path: Path, composition) -> None:
    """Make the shared legacy seed fixture honest for a composed run."""
    if composition is None:
        return
    path = tmp_path / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metric_spec"] = composition.metric.spec.model_dump(mode="json")
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Canned lit-review output — schema-valid with sentinel content the
# assertions key off of.
# ---------------------------------------------------------------------------

_SENTINEL_ARXIV_ID = "9999.99999"
_SENTINEL_FINDING_CONTENT = (
    "**Implication.** Dual-mode wiring sentinel — proves the lit-review "
    "channels reached the proposer.\n"
    "**Mechanism.** N/A.\n"
    "**Adaptation.** N/A.\n"
    "(rationale: synthetic test fixture.)"
)


def _canned_lit_output() -> LiteratureReviewOutput:
    return LiteratureReviewOutput(
        agent_card=AgentCard(
            agent_name="ml_literature_review",
            role="dual-mode wiring sentinel",
            expertise_domain="ML denoising",
            coverage="dual-mode test fixture",
            limitations="not a real survey",
            trust_guidance="test only",
            trust_level="soft_prior",
        ),
        findings=[
            ExpertContextItem(
                source="ml_literature_review",
                kind="literature",
                content=_SENTINEL_FINDING_CONTENT,
                source_ref=f"arxiv:{_SENTINEL_ARXIV_ID}",
                confidence=0.65,
            )
        ],
        new_vocab_candidates=[],
        suggested_mindset=None,
        retrieved_papers=[],
        search_rounds_used=0,
        run_name="dual_mode_test",
        started_at="2026-06-12T00:00:00Z",
        finished_at="2026-06-12T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Custom tmp YAML — distinct from configs/lit_review_config.yaml so the
# passthrough assertion (root_papers[0].identifier == _SENTINEL_ARXIV_ID)
# can prove the OPERATOR-SUPPLIED file was the one parsed.
# ---------------------------------------------------------------------------

_OPERATOR_YAML_CONTENT = f"""
enabled: true
root_papers:
  - source_type: arxiv
    identifier: "{_SENTINEL_ARXIV_ID}"
    verbosity: 1
dynamic_search:
  enabled: false
  max_rounds: 1
  initial_verbosity: 0
  escalation_allowed: false
  results_per_query: 5
  max_escalations_per_round: 0
findings_verbosity: 1
synthesis:
  transfer_tolerance: moderate
confidence_rubric:
  omit_below: 0.40
  abstract_only_ceiling: 0.79
  bands:
    - lower: 0.80
      upper: 1.00
      criteria: "test band 1"
    - lower: 0.60
      upper: 0.79
      criteria: "test band 2"
    - lower: 0.40
      upper: 0.59
      criteria: "test band 3"
"""


def _make_llm_config() -> WorkflowLLMConfig:
    return WorkflowLLMConfig(
        interpret=NodeLLMConfig(provider="openai", model_id="test"),
        propose=ProposalLLMConfig(),
        implement=NodeLLMConfig(provider="openai", model_id="test"),
        validate_model=NodeLLMConfig(provider="openai", model_id="test"),
        tune=TunerLLMConfig(
            planner=NodeLLMConfig(provider="openai", model_id="test"),
            reflector=NodeLLMConfig(provider="openai", model_id="test"),
        ),
        lit_review=LitReviewLLMConfig(),  # defaults — both sub-slots deepseek/deepseek-v4-pro
    )


# ---------------------------------------------------------------------------
# Test 1 — lit_review_enabled=True with a non-default YAML path:
#   (a) operator YAML drives LiteratureReviewInput.root_papers
#   (b) canned LiteratureReviewOutput channels reach the proposer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("composed", [False, True], ids=["legacy", "composed-pack"])
def test_lit_review_enabled_threads_operator_yaml_channels_to_proposer(tmp_path, composed):
    """End-to-end: with lit_review_enabled=True and a tmp YAML at a
    non-default path, the workflow opens THAT file (not the default),
    threads its root_papers into the LiteratureReviewInput, and the
    canned LiteratureReviewOutput's agent_card + findings reach the
    ProposalInput the proposer receives."""
    operator_yaml = tmp_path / "operator_lit.yaml"
    operator_yaml.write_text(_OPERATOR_YAML_CONTENT, encoding="utf-8")

    workspace = str(tmp_path / "workflow_output")
    data_dir = str(tmp_path / "data")
    run_name = "lit_review_enabled_test"
    composition = compose_run_task_bindings(str(SYNTHETIC_MANIFEST)) if composed else None
    _write_tuning_output(
        tmp_path,
        "punet",
        run="v1",
        score=1.5,
        fingerprint=(composition.semantic_fingerprint if composition else None),
    )
    _stamp_seed_metric(tmp_path, composition)

    captured_lit_inputs: list = []
    captured_proposal_inputs: list = []

    def _lit_review_run(inp):
        captured_lit_inputs.append(inp)
        return _canned_lit_output()

    def _proposer_run(inp):
        captured_proposal_inputs.append(inp)
        return _make_proposal_output("test_arch")

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLLiteratureReviewAgent") as MockLitReview,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockLitReview.return_value.run.side_effect = _lit_review_run
        MockPropose.return_value.run.side_effect = _proposer_run
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        tune_output = _make_tuning_output(model_type="test_arch", score=1.6)
        if composition is not None:
            tune_output.metric_spec = composition.metric.spec
        MockTune.return_value.run.return_value = tune_output

        with _composition_context(composition, data_dir):
            run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=data_dir,
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=1,
                    lit_review_enabled=True,
                    lit_review_config_path=str(operator_yaml),
                ),
                workspace=workspace,
                run_name=run_name,
                llm_config=_make_llm_config(),
                task_composition=composition,
            )

    # --- Assertion 1: lit-review was invoked once, with the operator
    # YAML's root_papers driving its input (proves the operator-supplied
    # path was opened, not the default configs/lit_review_config.yaml).
    assert len(captured_lit_inputs) == 1, (
        f"Expected MLLiteratureReviewAgent.run to fire once; got "
        f"{len(captured_lit_inputs)} call(s)."
    )
    MockLitReview.assert_called_once_with(
        bridge_factory=None,
        root_cache_dir=os.path.join(workspace, "cache", "literature", "root_papers"),
    )
    lit_input = captured_lit_inputs[0]
    assert len(lit_input.root_papers) == 1
    assert lit_input.root_papers[0].identifier == _SENTINEL_ARXIV_ID, (
        f"Expected the operator YAML's sentinel arxiv id "
        f"({_SENTINEL_ARXIV_ID}); got '{lit_input.root_papers[0].identifier}'. "
        f"This means the workflow opened the wrong YAML file — likely the "
        f"default at configs/lit_review_config.yaml instead of the "
        f"operator-supplied {operator_yaml}."
    )
    assert lit_input.dynamic_search.enabled is False, (
        "The operator YAML has dynamic_search.enabled=False; the parsed "
        "DynamicSearchConfig should reflect that."
    )

    # --- Assertion 2: the canned LiteratureReviewOutput's channels reach
    # the proposer via the workflow's external_channels merge + the
    # local_full_context call site.
    assert len(captured_proposal_inputs) == 1, (
        f"Expected MLModelProposalAgent.run to fire once; got "
        f"{len(captured_proposal_inputs)} call(s)."
    )
    prop_input = captured_proposal_inputs[0]

    # agent_cards: the canned output's one AgentCard ("ml_literature_review")
    # must appear on the ProposalInput.
    assert len(prop_input.agent_cards) == 1, (
        f"Expected 1 agent_card on ProposalInput (the lit-review card); "
        f"got {len(prop_input.agent_cards)}."
    )
    assert prop_input.agent_cards[0].agent_name == "ml_literature_review"
    assert prop_input.agent_cards[0].trust_level == "soft_prior"

    # expert_context: the canned finding's source_ref must reach the
    # proposer. Other ExpertContextItems may be present from prior-iter
    # accumulation, so we filter to the lit-review source rather than
    # asserting on len() exactly.
    lit_findings = [ec for ec in prop_input.expert_context if ec.source == "ml_literature_review"]
    assert len(lit_findings) == 1, (
        f"Expected exactly 1 lit-review finding on ProposalInput; got {len(lit_findings)}."
    )
    assert lit_findings[0].source_ref == f"arxiv:{_SENTINEL_ARXIV_ID}"


# ---------------------------------------------------------------------------
# Test 2 — lit_review_enabled=False with a non-existent config path:
#   (a) no FileNotFoundError raised (path is never opened)
#   (b) MLLiteratureReviewAgent.run is NEVER called
#   (c) ProposalInput.agent_cards is empty (no lit-review channels reach
#       the proposer)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("composed", [False, True], ids=["legacy", "composed-pack"])
def test_lit_review_disabled_tolerates_missing_yaml_path(tmp_path, composed):
    """With lit_review_enabled=False, the workflow must NOT open
    lit_review_config_path even if it points at a non-existent file —
    the path is consulted only when actually used."""
    non_existent_path = str(tmp_path / "does_not_exist" / "operator_lit.yaml")
    assert not os.path.exists(non_existent_path), (
        "Test invariant — the path must NOT exist for this assertion to be meaningful."
    )

    workspace = str(tmp_path / "workflow_output")
    data_dir = str(tmp_path / "data")
    run_name = "lit_review_disabled_test"
    composition = compose_run_task_bindings(str(SYNTHETIC_MANIFEST)) if composed else None
    _write_tuning_output(
        tmp_path,
        "punet",
        run="v1",
        score=1.5,
        fingerprint=(composition.semantic_fingerprint if composition else None),
    )
    _stamp_seed_metric(tmp_path, composition)

    captured_lit_inputs: list = []
    captured_proposal_inputs: list = []

    def _lit_review_run(inp):
        captured_lit_inputs.append(inp)
        return _canned_lit_output()

    def _proposer_run(inp):
        captured_proposal_inputs.append(inp)
        return _make_proposal_output("test_arch")

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLLiteratureReviewAgent") as MockLitReview,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockLitReview.return_value.run.side_effect = _lit_review_run
        MockPropose.return_value.run.side_effect = _proposer_run
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        tune_output = _make_tuning_output(model_type="test_arch", score=1.6)
        if composition is not None:
            tune_output.metric_spec = composition.metric.spec
        MockTune.return_value.run.return_value = tune_output

        # No FileNotFoundError should be raised — the non-existent path
        # must never be opened when lit_review_enabled=False.
        with _composition_context(composition, data_dir):
            run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=data_dir,
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=1,
                    lit_review_enabled=False,
                    lit_review_config_path=non_existent_path,
                ),
                workspace=workspace,
                run_name=run_name,
                llm_config=_make_llm_config(),
                task_composition=composition,
            )

    # --- Assertion 1: MLLiteratureReviewAgent.run was NEVER called.
    assert len(captured_lit_inputs) == 0, (
        f"With lit_review_enabled=False, the lit-review node must NOT "
        f"run; got {len(captured_lit_inputs)} call(s) instead."
    )

    # --- Assertion 2: ProposalInput carries no lit-review channels.
    assert len(captured_proposal_inputs) == 1
    prop_input = captured_proposal_inputs[0]
    assert prop_input.agent_cards == [], (
        f"With lit-review disabled, ProposalInput.agent_cards should be "
        f"empty; got {prop_input.agent_cards}."
    )
    lit_findings = [ec for ec in prop_input.expert_context if ec.source == "ml_literature_review"]
    assert lit_findings == [], (
        f"With lit-review disabled, no lit-review findings should reach "
        f"the proposer; got {lit_findings}."
    )
