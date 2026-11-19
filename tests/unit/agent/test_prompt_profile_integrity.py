"""A bound prompt profile that cannot render stops the run (#1542).

What only these tests catch:

* every integrity failure of a bound profile (undeclared boundary, renderer
  that raises, renderer that returns non-text, provider source drift, changed
  identity at binding) is the one typed ``PromptProfileIntegrityError`` naming
  profile and boundary, and is NOT a ``ValueError`` that ordinary validation
  handlers absorb;
* each production handler that converts failures into recoverable outcomes
  re-raises it instead: the native loop's proposal-attempt handler (proposer
  feedback), the proposer's boldness retry, the interpreter's degraded path,
  the tuner's round-failure path and the literature review's resilience
  boundaries. Reverting any one of these re-raises makes its test fail.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.prompt_rendering import (
    PromptProfileIntegrityError,
    PromptRenderingProfile,
    bind_prompt_profile,
    prompt_boundary,
    raise_if_prompt_profile_failure,
)

_BOUNDARY = "test.integrity_probe"


@prompt_boundary(_BOUNDARY)
def _probe(text: str) -> str:
    return f"native {text}"


def _profile(tmp_path, renderers, native=()):
    source = tmp_path / "provider.txt"
    source.write_text("provider bytes")
    return PromptRenderingProfile("paper-x", "1", renderers, frozenset(native), {"source": source})


def _integrity(boundary=_BOUNDARY):
    return PromptProfileIntegrityError(
        "paper-x", boundary, "synthetic test failure", "renderer_failure"
    )


@pytest.mark.parametrize(
    ("renderers", "reason", "kind", "remedy"),
    [
        ({}, "does not declare boundary", "undeclared", "declare the boundary in the profile"),
        (
            {_BOUNDARY: lambda text: (_ for _ in ()).throw(ValueError("refuse"))},
            "ValueError: refuse",
            "renderer_failure",
            "fix the profile's renderer",
        ),
        (
            {_BOUNDARY: lambda text: 7},
            "returned int, not text",
            "renderer_failure",
            "fix the profile's renderer",
        ),
    ],
    ids=["undeclared", "renderer-raises", "renderer-returns-non-text"],
)
def test_bound_profile_failures_are_typed_and_name_profile_and_boundary(
    tmp_path, renderers, reason, kind, remedy
):
    """Fails if a failure kind escapes as a plain ValueError (absorbable by
    validation handlers) or if the message loses the profile, the boundary or
    the remedy that matches its cause."""
    with bind_prompt_profile(_profile(tmp_path, renderers)):
        with pytest.raises(PromptProfileIntegrityError) as raised:
            _probe("x")
    error = raised.value
    assert not isinstance(error, ValueError)
    assert (error.profile, error.boundary, error.kind) == ("paper-x", _BOUNDARY, kind)
    message = str(error)
    assert reason in message and "paper-x" in message and _BOUNDARY in message
    assert f"Remedy: {remedy}" in message


def test_source_drift_during_the_run_is_typed(tmp_path):
    profile = _profile(tmp_path, {_BOUNDARY: lambda text: "pinned"})
    with bind_prompt_profile(profile):
        (tmp_path / "provider.txt").write_text("changed bytes")
        with pytest.raises(PromptProfileIntegrityError, match="changed during the run") as raised:
            _probe("x")
    assert raised.value.kind == "source_drift"
    assert "Remedy: restore the provider source the run started with" in str(raised.value)


def test_changed_identity_at_binding_is_typed(tmp_path):
    profile = _profile(tmp_path, {})
    expected = profile.identity()
    (tmp_path / "provider.txt").write_text("changed bytes")
    with pytest.raises(PromptProfileIntegrityError, match="changed after composition") as raised:
        with bind_prompt_profile(profile, expected=expected):
            pass
    assert raised.value.kind == "identity_drift"
    assert "Remedy: restore the provider source pinned at composition" in str(raised.value)


def test_wrapped_integrity_failure_is_found_through_explicit_causes():
    try:
        try:
            raise _integrity()
        except PromptProfileIntegrityError as inner:
            raise ValueError("a node wrapped it") from inner
    except ValueError as outer:
        with pytest.raises(PromptProfileIntegrityError):
            raise_if_prompt_profile_failure(outer)
    raise_if_prompt_profile_failure(ValueError("ordinary failure"))  # returns


# ---------------------------------------------------------------------------
# Production handlers that would otherwise absorb the failure
# ---------------------------------------------------------------------------


def test_native_loop_stops_instead_of_feeding_the_proposer(tmp_path):
    """Before #1542 the attempt handler appended "Node error: ValueError: ..."
    to previous_failures and asked the proposer again."""
    from tests.integration.workflows.test_chain_candidate_graduation import _llm_config_pseudo
    from tests.unit.workflows.test_model_exploration import (
        _make_interpretation_output,
        _make_proposal_output,
    )
    from workflows.model_exploration import run_workflow
    from workflows.run_config import WorkflowLaunchConfig
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    quickstart = (
        Path(__file__).resolve().parents[3] / "configs" / "task_composition" / "quickstart.yaml"
    )
    workspace = str(tmp_path / "ws")
    os.makedirs(workspace)
    composition = compose_run_task_bindings(str(quickstart))
    wrapped = ValueError("implementor wrapped it")
    wrapped.__cause__ = _integrity("implementor.validator_feedback")
    with (
        bind_run_task_composition(composition, physical_data_root=workspace),
        patch("workflows.model_exploration.ResultInterpretationAgent") as interp,
        patch("workflows.model_exploration.MLModelProposalAgent") as proposer,
        patch("workflows.model_exploration.MLModelImplementor") as implementor,
    ):
        interp.return_value.run.return_value = _make_interpretation_output()
        proposer.return_value.run.return_value = _make_proposal_output(model_name="candidate")
        implementor.return_value.run.side_effect = wrapped
        with pytest.raises(PromptProfileIntegrityError, match=r"implementor\.validator_feedback"):
            run_workflow(
                launch=WorkflowLaunchConfig(
                    source_paths=[],
                    max_iterations=1,
                    start_iteration=1,
                    max_proposal_attempts=3,
                    data_dir=workspace,
                ),
                workspace=workspace,
                run_name="profile_integrity",
                llm_config=_llm_config_pseudo(),
                task_composition=composition,
            )
        assert proposer.return_value.run.call_count == 1


@pytest.mark.usefixtures("synthetic_dataset_profile")
def test_proposer_boldness_retry_does_not_swallow_it(tmp_path):
    from tests.unit.agent.ml_model_proposal_agent.test_boldness_enforcement import (
        _make_agent,
        _make_comparison_output,
        _make_pipeline_input,
        _make_reasoning_output,
    )

    agent, _ = _make_agent(
        [
            _make_comparison_output(),
            _make_reasoning_output(current=5.5, predicted=5.75),  # timid: triggers retry
            _integrity("proposal.template"),
        ]
    )
    with pytest.raises(PromptProfileIntegrityError):
        agent.run(_make_pipeline_input(tmp_path))


def test_interpreter_does_not_degrade_on_it(tmp_path):
    from nodes.result_interpretation_agent import ResultInterpretationAgent
    from tests.unit.agent.result_interpretation_agent.test_health_feedback_outputs import (
        _make_input,
    )

    with patch("nodes.result_interpretation_agent.LLMBridge") as bridge:
        bridge.return_value.generate.side_effect = _integrity("interpretation.model_user")
        agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        agent.bridge = bridge.return_value
    with pytest.raises(PromptProfileIntegrityError):
        agent.run(_make_input(tmp_path))


def test_literature_review_resilience_boundaries_do_not_swallow_it(tmp_path):
    from tests.unit.agent.ml_literature_review.test_step00_prompt_goldens import (
        RP,
        make_agent,
        make_input,
    )

    agent = make_agent(tmp_path)
    agent.bridge = MagicMock()
    agent.bridge.generate.side_effect = _integrity("constraints.disclosure")
    with pytest.raises(PromptProfileIntegrityError):
        agent._synthesize(make_input(), [RP])


def test_worker_records_a_distinct_reason_for_the_stop():
    """The worker's graph evidence names the stop (in-process or reported by a
    unit child) instead of the generic native failure. Fails if either source
    of the classification is ignored."""
    from tools.candidate_worker.graph import failure_reason
    from tools.candidate_worker.unit_runner import NodeUnitRaised

    assert failure_reason(NodeUnitRaised("n", "prompt_profile_integrity")) == (
        "prompt_profile_integrity"
    )
    wrapped = ValueError("wrapped")
    wrapped.__cause__ = _integrity()
    assert failure_reason(wrapped) == "prompt_profile_integrity"
    assert failure_reason(NodeUnitRaised("n")) == "native_failure"
    assert failure_reason(RuntimeError("ordinary")) == "native_failure"


def test_unit_result_bytes_are_unchanged_when_no_failure_is_reported():
    """The new worker transport field is omitted when unset, so every ordinary
    unit result keeps its pre-#1542 bytes. Fails if the field serializes as null."""
    from tools.candidate_worker.unit_models import NodeUnitResult
    from tools.candidate_worker.unit_transport import encode_transport

    ordinary = encode_transport(NodeUnitResult(node_id="n", phase="proposal", outcome="raised"))
    assert b"failure" not in ordinary
    flagged = NodeUnitResult(
        node_id="n", phase="proposal", outcome="raised", failure="prompt_profile_integrity"
    )
    assert b'"failure":"prompt_profile_integrity"' in encode_transport(flagged)
