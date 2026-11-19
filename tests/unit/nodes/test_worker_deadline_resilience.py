"""A worker-deadline stop is never absorbed as a degraded node result (#1603).

The candidate worker's remaining budget is the cooperative deadline the LLM
bridge reads (#1585); a stop by it must reach the worker's classification
(``budget.run_within``, ``graph.failure_reason``) as ``timed_out`` /
``deadline_exceeded``. What only these tests catch, per resilience boundary:

* the stop propagates instead of becoming degraded output: the literature
  review's search decision, compression and synthesis, the analysis brief, the
  interpreter's degraded path and the proposer's causal-reasoning retry;
* any other exception, a plain provider ``TimeoutError`` included, keeps the
  existing degraded handling;
* the analysis brief keeps its own ``timed_out`` record for a refusal that is
  not the enclosing deadline's, and for any refusal when no deadline is bound.

Reverting any one re-raise makes its propagation test fail.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.execution_deadline import ExecutionDeadlineExceeded, execution_deadline


def _worker_stop(deadline) -> ExecutionDeadlineExceeded:
    """The refusal the bridge raises when the bound worker deadline is spent."""
    return ExecutionDeadlineExceeded(
        "Execution deadline exhausted at llm request", expires_at=deadline.expires_at
    )


def _wrapped(error: BaseException) -> RuntimeError:
    wrapper = RuntimeError("provider call failed")
    wrapper.__cause__ = error
    return wrapper


# ---------------------------------------------------------------------------
# Literature review: three resilience boundaries
# ---------------------------------------------------------------------------


def _review_agent(tmp_path):
    from tests.unit.agent.ml_literature_review.test_step00_prompt_goldens import make_agent

    agent = make_agent(tmp_path)
    agent.bridge = MagicMock()
    agent.search_bridge = agent.bridge
    return agent


def _search(agent):
    from agent.schemas.literature_review import DynamicSearchConfig
    from tests.unit.agent.ml_literature_review.test_step00_prompt_goldens import make_input

    inp = make_input(
        dynamic_search=DynamicSearchConfig(enabled=True, max_rounds=1, escalation_allowed=False)
    )
    return agent._run_search_loop(inp, [], {})


def _compress(agent):
    return agent._compress("full text of a paper")


def _synthesize(agent):
    from tests.unit.agent.ml_literature_review.test_step00_prompt_goldens import RP, make_input

    return agent._synthesize(make_input(), [RP])


_BOUNDARIES = {
    "search_decision": (_search, (0, [])),
    "compression": (_compress, None),
    "synthesis": (_synthesize, []),
}


@pytest.mark.parametrize("wrap", [False, True], ids=["direct", "wrapped"])
@pytest.mark.parametrize("site", sorted(_BOUNDARIES))
def test_literature_review_boundary_propagates_the_worker_stop(tmp_path, site, wrap):
    run, _ = _BOUNDARIES[site]
    agent = _review_agent(tmp_path)
    with execution_deadline(60) as deadline:
        stop = _worker_stop(deadline)
        agent.bridge.generate.side_effect = _wrapped(stop) if wrap else stop
        with pytest.raises(ExecutionDeadlineExceeded) as raised:
            run(agent)
    assert raised.value is stop


@pytest.mark.parametrize(
    "error", [RuntimeError("bad call"), TimeoutError("provider timeout")], ids=["error", "timeout"]
)
@pytest.mark.parametrize("site", sorted(_BOUNDARIES))
def test_literature_review_boundary_keeps_degrading_other_failures(tmp_path, site, error):
    run, degraded = _BOUNDARIES[site]
    agent = _review_agent(tmp_path)
    agent.bridge.generate.side_effect = error
    with execution_deadline(60):
        assert run(agent) == degraded


# ---------------------------------------------------------------------------
# Interpreter: degraded path and analysis brief
# ---------------------------------------------------------------------------


def _interpreter_with(side_effect):
    from nodes.result_interpretation_agent import ResultInterpretationAgent

    with patch("nodes.result_interpretation_agent.LLMBridge") as bridge:
        bridge.return_value.generate.side_effect = side_effect
        agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        agent.bridge = bridge.return_value
    return agent


def test_interpreter_degraded_path_propagates_the_worker_stop(tmp_path):
    from tests.unit.agent.result_interpretation_agent.test_health_feedback_outputs import (
        _make_input,
    )

    with execution_deadline(60) as deadline:
        stop = _worker_stop(deadline)
        agent = _interpreter_with(stop)
        with pytest.raises(ExecutionDeadlineExceeded):
            agent.run(_make_input(tmp_path))


def test_interpreter_degraded_path_still_degrades_other_failures(tmp_path):
    from tests.unit.agent.result_interpretation_agent.test_health_feedback_outputs import (
        _make_input,
    )

    agent = _interpreter_with(RuntimeError("provider rejected the request"))
    with execution_deadline(60):
        output = agent.run(_make_input(tmp_path))
    assert output.evolution_stats["is_degraded"] is True


class _StopBridge:
    """Cold-start brief bridge whose only call raises ``error``."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls: list[str] = []

    def generate(self, system: str, user: str, *, label: str, **_kwargs):
        self.calls.append(label)
        raise self.error


def _brief_record(tmp_path):
    path = tmp_path / "analysis_brief_generation_brief-test.json"
    return json.loads(path.read_text())["receipt"] if path.exists() else None


def _run_cold(tmp_path, bridge):
    from nodes.result_interpretation_agent import ResultInterpretationAgent
    from tests.unit.agent.result_interpretation_agent.test_analysis_brief_generation import (
        _cold_input,
    )

    agent = ResultInterpretationAgent(provider="OPENAI", bridge_factory=lambda **_: bridge)
    return agent.run(_cold_input(tmp_path, requested=True))


def test_analysis_brief_propagates_the_enclosing_stop_without_a_record(tmp_path):
    """No ``timed_out`` record may be persisted for the worker's stop: a resumed
    run must ask for the brief again rather than reuse a stop as its outcome."""
    with execution_deadline(60) as deadline:
        bridge = _StopBridge(_worker_stop(deadline))
        with pytest.raises(ExecutionDeadlineExceeded):
            _run_cold(tmp_path, bridge)
    assert bridge.calls == ["interpretation.analysis_brief"]
    assert _brief_record(tmp_path) is None


@pytest.mark.parametrize("bound", [True, False], ids=["shorter-nested", "no-deadline"])
def test_analysis_brief_keeps_its_own_timed_out_record(tmp_path, bound):
    """A refusal by another (shorter) allocation, or any refusal with no deadline
    bound, stays the brief's own ``timed_out`` outcome; the run continues."""
    if bound:
        with execution_deadline(60) as enclosing:
            other = ExecutionDeadlineExceeded(
                "nested allocation spent", expires_at=enclosing.expires_at - 30
            )
            output = _run_cold(tmp_path, _StopBridge(other))
    else:
        output = _run_cold(tmp_path, _StopBridge(ExecutionDeadlineExceeded("spent")))
    assert output.analysis_brief is None
    assert _brief_record(tmp_path)["status"] == "timed_out"


# ---------------------------------------------------------------------------
# Proposer: causal-reasoning retry
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("synthetic_dataset_profile")
@pytest.mark.parametrize("stopped", [True, False], ids=["worker-stop", "malformed-retry"])
def test_proposer_causal_retry_propagates_only_the_worker_stop(tmp_path, stopped):
    """The retry's ``except Exception: pass`` corrects a malformed retry later;
    it must not swallow the stop and carry on to the proposing stage."""
    from tests.unit.agent.ml_model_proposal_agent.test_boldness_enforcement import (
        _make_agent,
        _make_comparison_output,
        _make_pipeline_input,
        _make_reasoning_output,
    )

    with execution_deadline(60) as deadline:
        failure = _worker_stop(deadline) if stopped else RuntimeError("malformed retry")
        agent, _ = _make_agent(
            [
                _make_comparison_output(),
                _make_reasoning_output(current=5.5, predicted=5.75),  # timid: triggers retry
                failure,
            ]
        )
        # A malformed retry is absorbed and the proposer moves on to its next
        # call, which the exhausted scripted bridge answers with StopIteration.
        with pytest.raises(ExecutionDeadlineExceeded if stopped else StopIteration):
            agent.run(_make_pipeline_input(tmp_path))
