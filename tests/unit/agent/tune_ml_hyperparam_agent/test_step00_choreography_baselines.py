"""Step-00 WF-1 / WF-2 — plan()/reflect() call-surface baselines (Type 5).

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.5 / §15.1 (roadmap steps 05/07a A-surfaces: "same kwargs reach
LLMBridge").

One bounded pseudo tuner iteration (the same production-path harness as
REC-2) crosses the real ``plan()``/``reflect()`` call sites; the widened
``RecordingLLMBridge`` records the full surfaces. The ``plan()`` surface
is 25 parameters excl. ``self`` — ``memory_history`` bound POSITIONALLY
(itself part of the pinned surface, review F11) plus 24 keywords, all
passed explicitly by the sole production call site.

Justified exclusions (design §13, WF-1 row): ``registry`` is a live
object — pinned by type name; ``memory_history`` is recorded by
reference — pinned by type/length here and by content in the registered
k9 choreography (WF-4). Every VALUE-carrying kwarg remains deep-compared,
so the exclusions cannot hide drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.golden import assert_json_golden
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

GOLDENS = Path(__file__).parent / "goldens"
_PREFLIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "step00_preflight_results.json"

_PRESENT = "<present>"


@pytest.fixture(scope="module")
def pseudo_run(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("step00_wf")
    try:
        output, bridge, sandbox, workspace = run_bounded_pseudo_iteration(
            tmp, mp, preflight_results=preflight
        )
    finally:
        mp.undo()
    return output, bridge, sandbox, workspace


def project_plan_call(call: tuple) -> dict:
    """Serializable projection of one recorded ``plan()`` call.

    ``config_manual`` is reduced to its sorted top-level key list:
    production populates it with schema docstrings/manual PROSE, and
    embedding that text here would red a choreography baseline on any
    editorial production-comment edit (closure-audit F3 — the §13.1
    no-production-source-text rule). Content parity for manuals belongs
    to PB goldens built from test-owned fixtures.
    """
    _method, memory_history, expert_advice, force_model, kwargs = call
    projected = dict(kwargs)
    registry = projected.pop("registry", None)
    config_manual = projected.pop("config_manual", None)
    projected["config_manual_keys"] = (
        sorted(config_manual) if isinstance(config_manual, dict) else config_manual
    )
    return {
        "memory_history": {
            "type": type(memory_history).__name__,
            "length": len(memory_history),
        },
        "expert_advice": expert_advice,
        "force_model": force_model,
        "registry_type": type(registry).__name__ if registry is not None else None,
        "kwargs": projected,
    }


class TestWF1PlanCallSurface:
    def test_first_plan_call_full_surface(self, pseudo_run):
        _output, bridge, _sandbox, _ws = pseudo_run
        plans = [c for c in bridge.calls if c[0] == "plan"]
        assert len(plans) == 3, "the bounded iteration makes exactly 3 plan calls"
        assert_json_golden(
            project_plan_call(plans[0]),
            GOLDENS / "wf1_plan_call_round1_surface.json",
            surface="WF-1 plan() round-1 call surface",
        )

    def test_kwarg_key_set_stable_across_all_calls(self, pseudo_run):
        _output, bridge, _sandbox, _ws = pseudo_run
        plans = [c for c in bridge.calls if c[0] == "plan"]
        key_sets = [sorted(c[4].keys()) for c in plans]
        assert key_sets[0] == key_sets[1] == key_sets[2]
        assert_json_golden(
            key_sets[0],
            GOLDENS / "wf1_plan_kwarg_key_set.json",
            surface="WF-1 plan() kwarg key set",
        )


class TestWF2ReflectCallSurface:
    def test_reflect_calls_shape(self, pseudo_run):
        _output, bridge, _sandbox, _ws = pseudo_run
        reflects = [c for c in bridge.calls if c[0] == "reflect"]
        assert len(reflects) == 2, "one reflect per successful round"
        projected = []
        for _method, exp_id, hypothesis, actual_results, reflection_context in reflects:
            projected.append(
                {
                    "exp_id": _PRESENT if exp_id else exp_id,
                    "hypothesis": {"type": type(hypothesis).__name__, "present": bool(hypothesis)},
                    "actual_results_keys": sorted(actual_results.keys()),
                    "reflection_context_keys": sorted(reflection_context.keys())
                    if reflection_context
                    else None,
                }
            )
        assert_json_golden(
            projected,
            GOLDENS / "wf2_reflect_call_surfaces.json",
            surface="WF-2 reflect() call surfaces",
        )
