"""Issue #983 S7a: the data-analysis sampling seed (T14, T15 analysis part).

Explicitness is read from the operator's envelope, never from the LLM plan. A
declared seed executes and renders exactly as before; an undeclared one is
derived from the run seed, replaces the plan's value, reaches the task's
selection identity and coverage, and never reaches a prompt. Literal derived
values are pinned (``siderius-seed/v1``, purpose ``data_analysis.sampling``,
empty coordinates), never recomputed by the test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from agent.data_analysis.plan_validation import AnalysisPlanResolutionError
from agent.schemas.data_analysis.resources import AnalysisResourceEnvelope
from core.seeding import MissingRunSeed
from nodes.data_analysis_agent import DataAnalysisAgent
from tests.unit.nodes.test_data_analysis_agent import _Bridge, _Capability, _input

PAPER_SEED = 20260915
#: derive_seed(run_seed, "data_analysis.sampling", SeedCoordinates()) for run seeds 1, 2.
DERIVED = {1: 1196625095671327141, 2: 7498033353603223692}


class _SeedCapability(_Capability):
    def __init__(self) -> None:
        super().__init__()
        self.seeds: list[int] = []

    def materialize_analysis_view(self, authorized):
        self.seeds.append(authorized.request.sampling_policy.seed)
        return super().materialize_analysis_view(authorized)


class _PlanSeedBridge(_Bridge):
    """Records every LLM request; the plan carries ``plan_seed`` (absent: omitted)."""

    def __init__(self, *, plan_seed, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan_seed = plan_seed
        self.requests: list[tuple[str, str, str]] = []

    def generate(self, system, user, *, label):
        self.requests.append((label, system, user))
        planning = label in {"data_analysis.plan", "data_analysis.plan.resolution_retry"}
        value = copy.deepcopy(
            super().generate(system, user, label="data_analysis.plan" if planning else label)
        )
        if planning:
            policy = value["invocations"][0]["sampling_plan"]["policy"]
            if self.plan_seed is None:
                policy.pop("seed")
            else:
                policy["seed"] = self.plan_seed
        return value


def _with_envelope(tmp_path: Path, seed: int | None):
    analysis_input = _input(tmp_path)
    policy = {} if seed is None else {"sampling_policy": {"seed": seed}}
    envelope = AnalysisResourceEnvelope.model_validate(
        {"wall_time_budget_s": 15, "per_skill_timeout_s": 5, "preferred_device": "cpu", **policy}
    )
    return analysis_input.model_copy(update={"resource_envelope": envelope})


def _run(tmp_path: Path, *, envelope_seed, plan_seed, run_seed):
    analysis_input = _with_envelope(tmp_path, envelope_seed)
    capability = _SeedCapability()
    bridge = _PlanSeedBridge(analysis_input=analysis_input, plan_seed=plan_seed)
    report = DataAnalysisAgent(
        run_seed=run_seed,
        task_analysis_capability=capability,
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    ).run(analysis_input)
    root = tmp_path / "data_analysis" / "standalone" / "request"
    return report, capability, bridge, root


def test_declared_seed_executes_and_renders_exactly_as_declared(tmp_path):
    """Fails if a declared envelope seed is replaced, recorded as derived, or
    dropped from a prompt (the paper's analysis-on prompts declare 20260915)."""
    report, capability, bridge, root = _run(
        tmp_path, envelope_seed=PAPER_SEED, plan_seed=PAPER_SEED, run_seed=1
    )
    assert capability.seeds == [PAPER_SEED]
    assert report.findings[0].coverage.sampling_seed == PAPER_SEED
    recorded = json.loads((root / "sampling_seeds.json").read_text())
    assert recorded["invocations"] == [
        {
            "invocation_id": "summary-invocation",
            "sampling_seed": PAPER_SEED,
            "sampling_seed_source": "declared",
        }
    ]
    prompts = {label: user for label, _system, user in bridge.requests}
    for label in ("data_analysis.skill_selection", "data_analysis.plan"):
        assert f'"seed": {PAPER_SEED}' in prompts[label]
    assert f'"sampling_seed": {PAPER_SEED}' in prompts["data_analysis.synthesis"]


def test_plan_seed_contradicting_the_declared_seed_is_a_plan_error(tmp_path):
    """Fails if a plan may execute a seed other than the operator's declared one."""
    with pytest.raises(AnalysisPlanResolutionError, match=f"declared sampling seed {PAPER_SEED}"):
        _run(tmp_path, envelope_seed=PAPER_SEED, plan_seed=0, run_seed=1)


def test_undeclared_seed_is_derived_replaces_the_plan_seed_and_stays_out_of_prompts(tmp_path):
    """Fails if explicitness is read from the LLM plan (its copied ``seed: 0``
    would execute), if the derived seed does not reach the task's selection
    and coverage, or if it or its provenance reaches any prompt."""
    report, capability, bridge, root = _run(tmp_path, envelope_seed=None, plan_seed=0, run_seed=1)
    assert capability.seeds == [DERIVED[1]]
    assert report.findings[0].coverage.sampling_seed == DERIVED[1]
    recorded = json.loads((root / "sampling_seeds.json").read_text())
    assert recorded["run_seed"] == 1
    assert recorded["invocations"] == [
        {
            "invocation_id": "summary-invocation",
            "sampling_seed": DERIVED[1],
            "sampling_seed_source": "derived",
            "llm_plan_seed_ignored": 0,
        }
    ]
    for _label, system, user in bridge.requests:
        text = system + user
        assert str(DERIVED[1]) not in text and "sampling_seed_source" not in text
        assert "llm_plan_seed_ignored" not in text
    synthesis = next(user for label, _s, user in bridge.requests if label.endswith("synthesis"))
    assert '"sampling_seed"' not in synthesis
    selection = next(user for label, _s, user in bridge.requests if label.endswith("selection"))
    assert '"seed"' not in selection.split("Resource envelope:")[1].split("Safe asset")[0]


def test_llm_requests_are_identical_for_different_run_seeds(tmp_path):
    """T15 (analysis): an unset envelope and a seedless plan, executed under run
    seeds 1 and 2 with identical stubbed views. Fails if any run seed, derived
    seed or seed provenance leaks into a plan, selection or synthesis request."""
    # Both runs use the same workspace path (the input digest rendered in the
    # plan prompt binds it); the first run's directory is moved aside, not removed.
    workspace = tmp_path / "workspace"
    runs = {}
    for run_seed in (1, 2):
        runs[run_seed] = _run(workspace, envelope_seed=None, plan_seed=None, run_seed=run_seed)
        workspace.rename(tmp_path / f"run-{run_seed}")
    requests = {
        run_seed: bridge.requests for run_seed, (_report, _cap, bridge, _root) in runs.items()
    }
    assert [label for label, *_ in requests[1]] == [
        "data_analysis.skill_selection",
        "data_analysis.plan",
        "data_analysis.synthesis",
    ]
    assert requests[1] == requests[2]
    assert runs[1][1].seeds == [DERIVED[1]] and runs[2][1].seeds == [DERIVED[2]]
    text = json.dumps(requests[1])
    for forbidden in ("sampling_seed_source", *map(str, DERIVED.values())):
        assert forbidden not in text


def test_agent_refuses_a_missing_run_seed_before_any_llm_call(tmp_path):
    """Fails if the analysis node invents or skips the run seed: only an entry
    boundary may generate one (MissingRunSeed)."""
    analysis_input = _with_envelope(tmp_path, None)
    bridge = _PlanSeedBridge(analysis_input=analysis_input, plan_seed=0)
    agent = DataAnalysisAgent(
        task_analysis_capability=_SeedCapability(),
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    )
    with pytest.raises(MissingRunSeed):
        agent.run(analysis_input)
    assert bridge.requests == []


def test_envelope_declaration_survives_dump_and_validate_round_trips():
    """Fails if an undeclared seed is written as ``0`` (a model_dump/validate
    round trip, as the literature and source-scope edges do, would then turn
    a derived seed into a declared 0), or if a declared seed is dropped."""
    undeclared = AnalysisResourceEnvelope(wall_time_budget_s=10, per_skill_timeout_s=5)
    declared = AnalysisResourceEnvelope(
        wall_time_budget_s=10, per_skill_timeout_s=5, sampling_policy={"seed": PAPER_SEED}
    )
    assert "seed" not in undeclared.model_dump(mode="json")["sampling_policy"]
    for mode in ("python", "json"):
        again = AnalysisResourceEnvelope.model_validate(undeclared.model_dump(mode=mode))
        assert again.declared_sampling_seed() is None
        kept = AnalysisResourceEnvelope.model_validate(declared.model_dump(mode=mode))
        assert kept.declared_sampling_seed() == PAPER_SEED
    assert declared.model_dump(mode="json")["sampling_policy"]["seed"] == PAPER_SEED
