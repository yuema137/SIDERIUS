"""Step-00 WF-1 / WF-2 — plan()/reflect() call-surface baselines (Type 5).

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.5 / §15.1 (roadmap steps 05/07a A-surfaces: "same kwargs reach
LLMBridge").

One bounded pseudo tuner iteration (the same production-path harness as
REC-2) crosses the real ``plan()``/``reflect()`` call sites; the widened
``RecordingLLMBridge`` records the full surfaces. The ``plan()`` surface
has ``memory_history`` bound POSITIONALLY (itself part of the pinned
surface, review F11); the golden key set records the current keywords
passed explicitly by the production call site.

Justified exclusions (design §13, WF-1 row): ``registry`` is a live
object — pinned by type name; ``memory_history`` is recorded by
reference — pinned by type/length here and by content in the registered
k9 choreography (WF-4). Every VALUE-carrying kwarg remains deep-compared,
with source digests normalized as described below.

DECLARED GOLDEN DELTAS (never a re-baseline to make a test green)
----------------------------------------------------------------

* **Issue #372** — adds ``planner_strategy``, ``expected_planner_strategy``
  and the full JSON ``timing_context``. Every previous value is unchanged.
  Provider name/version remain pinned; source hashes are normalized to
  markers because strategy identity tests own source-change/refusal checks.
  The fixture explicitly selects native and does not require an installed
  experiment default. Historical rendered text remains exp-owned.

* **PR01A2 builtin loss offers (2026-09-12)** — one textual field-name
  insertion: ``kwargs.task_render.fields`` gains ``loss_context``. This is
  the approved additive typed carrier, not a plan() keyword or a change to
  the legacy prompt bytes (eight actual bridge pairs remain byte-identical).
  CI's captured diff contained exactly that one insertion; no regeneration.

* **Step 12 / PR-12a C7-2** — the composed-prompt gating (D-12a-5). Two
  deltas, measured BEFORE either golden was touched and applied by textual
  insertion (**9 insertions, 0 deletions** across both files; nothing else
  regenerated):

  ``wf1_plan_call_round1_surface.json`` — ``kwargs.task_render`` gained
  SEVEN keys: ``available_models_block``, ``per_file_table_protocol``,
  ``target_strategy_impact_note``, ``sampling_impact_tradeoff``,
  ``per_file_comparison_block``, ``score_field_noun``,
  ``score_display_noun``. Each carries the LEGACY bytes VERBATIM — the
  blocks moved out of the prompt templates into the render authority so a
  COMPOSED run can be given different ones, and ``TunerTaskRender`` is
  where 07b declared such tokens must live ("a renderer that grew a new
  token would have to declare it here").

  ``wf2_reflect_call_surfaces.json`` — ``additive_kwargs`` gained
  ``task_render: TunerTaskRender`` on both calls. ``reflect()`` had no
  ``task_render`` by 07b's §3.9 decision, which recorded the reflector's
  literal "200 vs 4000" anchor as a GAP rather than "smuggling" a kwarg;
  C7 must gate the reflector's task NAMING, and that needs the signal. It
  is the same ADDITIVE-kwarg shape ``metric_spec`` and
  ``training_diagnosis`` arrived in, and it defaults to ``None`` — so a
  caller that omits it renders the legacy words.

  **What these deltas deliberately do NOT show is a prompt change.** The
  legacy RENDERED prompt manifest is byte-identical across all of C7 —
  pinned independently at ``6e8de64b…`` by
  ``tests/unit/guardrails/test_step12_pr12a_c0_legacy_parity.py``. These
  goldens pin the CALL SURFACE; that one pins what the LLM receives. Both
  had to be checked, and only the surface moved.

* **D-BUD-6 mode-aware epoch caps (2026-08-26)** — two textual insertions
  per golden, nothing regenerated: ``wf1_plan_call_round1_surface.json``
  kwargs gained ``trial_max_epochs: null`` and ``formal_max_epochs: null``,
  and ``wf1_plan_kwarg_key_set.json`` gained the same two names in sorted
  position. The same ADDITIVE-kwarg shape ``metric_spec`` and
  ``task_render`` arrived in: ``plan()`` now discloses the per-mode
  EFFECTIVE epoch ceilings (resolved by
  ``HyperparamTuningInput.resolve_epoch_cap``); both ``None`` — every
  legacy run, including this bounded pseudo iteration — renders the FIXED
  block byte-identically, which is why the values recorded here are null.
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
    # #372 adds typed policy facts and a verified provider pin. Choreography
    # freezes their transport, while strategy tests own source-digest identity.
    for name in ("timing_context", "expected_planner_strategy"):
        carrier = projected[name]
        projected[name] = carrier.model_dump(mode="json")
    for name in ("content_sha256", "assembly_sha256"):
        value = projected["expected_planner_strategy"][name]
        assert isinstance(value, str) and len(value) == 64
        projected["expected_planner_strategy"][name] = "<source SHA-256>"
    registry = projected.pop("registry", None)
    config_manual = projected.pop("config_manual", None)
    # WF-1 owns the call surface, not one scientific task's rendered prose.
    # Pin the typed carrier and its complete field set; task-render content is
    # covered by the renderer's own focused tests.  Embedding that content here
    # formerly made this generic choreography oracle a second TIDMAD authority.
    task_render = projected.pop("task_render", None)
    projected["task_render"] = (
        None
        if task_render is None
        else {
            "type": type(task_render).__name__,
            "fields": sorted(type(task_render).model_fields),
        }
    )
    # Step 07 PR 07b (P3) — same treatment for the metric declaration: its
    # `direction` and `id` are what the planner prompt now states, so a drift
    # in either is an LLM-visible change this baseline must catch.
    metric_spec = projected.pop("metric_spec", None)
    projected["metric_spec"] = None if metric_spec is None else metric_spec.model_dump(mode="json")
    custom_loss_inventory = projected.pop("custom_loss_inventory", None)
    projected["custom_loss_inventory"] = (
        None
        if custom_loss_inventory is None
        else {
            "type": type(custom_loss_inventory).__name__,
            "composed": custom_loss_inventory.composed,
            "names": list(custom_loss_inventory.names),
            "unavailable_reason": custom_loss_inventory.unavailable_reason,
            "generation_allowed": custom_loss_inventory.generation_allowed,
        }
    )
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
        for _method, exp_id, hypothesis, actual_results, reflection_context, extra in reflects:
            projected.append(
                {
                    "exp_id": _PRESENT if exp_id else exp_id,
                    "hypothesis": {"type": type(hypothesis).__name__, "present": bool(hypothesis)},
                    "actual_results_keys": sorted(actual_results.keys()),
                    "reflection_context_keys": sorted(reflection_context.keys())
                    if reflection_context
                    else None,
                    # Step 07 PR 07b — the two ADDITIVE kwargs, pinned by NAME
                    # and TYPE. The point of WF-2 here is that they arrived as
                    # kwargs and did NOT appear inside `actual_results` or
                    # `reflection_context`, whose key lists above stay at their
                    # frozen 9 and 23.
                    "additive_kwargs": {
                        name: type(value).__name__ for name, value in sorted(extra.items())
                    },
                }
            )
        assert_json_golden(
            {"calls": projected},
            GOLDENS / "wf2_reflect_call_surfaces.json",
            surface="WF-2 reflect() call surfaces",
        )


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
