"""B6-8a launch admission of LLM COMBINE adaptors (D3 rubric source, D4 run call sum).

Pure unit tests over ``adaptor_llm.admit_llm_adaptors``; each names its defect.
"""

import json

import pytest

from agent.schemas.judge import JudgeRoute, JudgeRoutes
from agent.schemas.judge_task import (
    JudgeTaskDeclarations,
    RubricCriterion,
    RubricSpec,
    rubric_ref,
)
from tools.candidate_worker.adaptor_llm import UnsupportedRubricSource, admit_llm_adaptors
from workflows.definition import AdaptorInstance
from workflows.judge_strategies import StrategyError

ROUTE = JudgeRoute(
    provider="openai", model_id="judge", reasoning_effort=None, max_output_tokens=64, max_retries=0
)
RUBRIC = RubricSpec(
    schema_version="siderius.rubric/v1",
    id="usefulness",
    version="1",
    criteria=(RubricCriterion(name="use", description="Useful for a proposal.", weight=1.0),),
    scale_min=1,
    scale_max=5,
)


def adaptor(sources: int = 3, **combine) -> AdaptorInstance:
    return AdaptorInstance.model_validate_json(
        json.dumps(
            {
                "id": "judge",
                "inputs": [
                    {"name": "reviews", "contract": "literature.output", "cardinality": "many"}
                ],
                "bindings": [
                    {
                        "port": "reviews",
                        "sources": [{"kind": "result", "node": f"r{i}"} for i in range(sources)],
                    }
                ],
                "combine": {
                    "kind": "rubric-rank/v1",
                    "route_slot": "aggregate",
                    "max_calls": 9,
                    "guidance": "none",
                    "criterion": "c",
                    "rubric": rubric_ref(RUBRIC).model_dump(),
                    "scoring": "per_item",
                    "repeats": 1,
                    **combine,
                },
                "select": {"kind": "top-k/v1", "k": 1},
                "distribute": {"kind": "single/v1"},
            }
        )
    )


def admit(declarations, *, cap=20, bodies=1, stop_calls=0, value=None):
    admit_llm_adaptors(
        (value or adaptor(),),
        JudgeRoutes(aggregate=ROUTE, max_judge_calls=cap),
        declarations,
        bodies=bodies,
        stop_calls=stop_calls,
    )


def test_a_rubric_the_task_does_not_declare_is_refused_naming_the_supported_source():
    """Defect: a rubric absent from the task composition (an experiment-owned one) is
    silently ignored or reaches a scorer call (D3)."""
    with pytest.raises(UnsupportedRubricSource, match=r"`rubrics:` section .*unknown_rubric"):
        admit(None)
    edited = RUBRIC.model_copy(update={"scale_max": 7})
    with pytest.raises(UnsupportedRubricSource, match="digest_mismatch"):
        admit(JudgeTaskDeclarations(rubrics=(edited,)))
    admit(JudgeTaskDeclarations(rubrics=(RUBRIC,)))


@pytest.mark.parametrize(
    ("bodies", "stop_calls", "cap", "admitted"),
    [(1, 0, 3, True), (1, 0, 2, False), (3, 2, 11, True), (3, 2, 10, False)],
)
def test_the_run_call_sum_is_adaptor_bound_times_bodies_plus_the_stop_bound(
    bodies, stop_calls, cap, admitted
):
    """Defect: max_judge_calls ignores loop bodies or the JudgeStop bound (D4: sum is
    3 per_item calls x bodies + stop calls)."""
    declarations = JudgeTaskDeclarations(rubrics=(RUBRIC,))
    if admitted:
        admit(declarations, cap=cap, bodies=bodies, stop_calls=stop_calls)
    else:
        with pytest.raises(StrategyError, match=f"max_judge_calls is {cap}"):
            admit(declarations, cap=cap, bodies=bodies, stop_calls=stop_calls)


def test_task_guidance_and_routes_are_required_where_declared():
    """Defect: guidance 'task_blocks' without task judge blocks, an unrouted slot, or an
    absent run cap reaches a call."""
    declarations = JudgeTaskDeclarations(rubrics=(RUBRIC,))
    with pytest.raises(StrategyError, match="declares no judge_blocks"):
        admit(declarations, value=adaptor(guidance="task_blocks"))
    with pytest.raises(StrategyError, match=r"judge\.debate route"):
        admit(declarations, value=adaptor(route_slot="debate"))
    with pytest.raises(StrategyError, match=r"require WorkflowLLMConfig\.judge\.max_judge_calls"):
        admit_llm_adaptors(
            (adaptor(),), JudgeRoutes(aggregate=ROUTE), declarations, bodies=1, stop_calls=0
        )


def test_rubric_ranking_maps_exact_means_into_select_and_replays(tmp_path, monkeypatch):
    """Defect: the B6 ranking drops the exact rubric mean (threshold/top-k then compare
    display floats), loses the judge's order, or replay re-runs instead of re-deriving."""
    from tests.unit.workflows.test_judge_strategies import RUBRIC as SCORED_RUBRIC
    from tests.unit.workflows.test_judge_strategies import StubBridge, literature
    from tools.candidate_worker.adaptor_llm import JudgeAdaptorContext, decide_llm

    value = adaptor(rubric=rubric_ref(SCORED_RUBRIC).model_dump(), max_calls=3).model_copy()
    items = tuple(literature(i) for i in range(3))
    declarations = JudgeTaskDeclarations(rubrics=(SCORED_RUBRIC,))
    bridge = StubBridge()
    monkeypatch.setattr("agent.judge.call.bridge_for_route", lambda route: bridge)
    context = JudgeAdaptorContext(
        workspace=tmp_path,
        run_name="r",
        run_id="run-1",
        routes=JudgeRoutes(aggregate=ROUTE, max_judge_calls=9),
        declarations=declarations,
    )
    outcome, record = decide_llm(value, items, iteration=2, context=context)
    assert outcome.ranking is not None and outcome.ranking.basis == "rubric"
    assert [entry.exact for entry in outcome.ranking.entries] == ["13/3", "3", "3"]
    assert [output.inputs[0].position for output in outcome.outputs] == [2]
    assert record.strategy_evidence is not None
    replay = JudgeAdaptorContext(
        **{**context.__dict__, "replay": {"judge": record.strategy_evidence.sha256}}
    )
    calls = len(bridge.calls)
    assert decide_llm(value, items, iteration=2, context=replay) == (outcome, record)
    assert len(bridge.calls) == calls
