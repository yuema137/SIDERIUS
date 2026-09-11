"""Lane F2 — the campaign-portion authority (frozen portions reach execution).

Root cause fixed here: the chain forwarded campaign portions into tuner-input
fields NO tuner code consumes, while trial workload came exclusively from the
LLM plan — the frozen 0.1×0.1 intent died in transit. The repair: a TYPED
portion is EXPERIMENT_FIXED and joins the EXISTING ``plan_overrides`` lock
(``frozen_portion_overrides``); ``None`` is AGENT_CONTROLLED. Each test names
the defect only it catches.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from workflows.run_config import WorkflowLaunchConfig, frozen_portion_overrides

REPO_ROOT = Path(__file__).resolve().parents[3]


def _launch(**kw) -> WorkflowLaunchConfig:
    return WorkflowLaunchConfig(**kw)


def test_bare_launch_merges_nothing_the_pinned_property(tmp_path):
    """THE supervisor-pinned property — the defect only this catches: a bare
    chain run's executed behavior changing. Today's dead 0.1 defaults never
    reached execution, so the repair must merge NOTHING when nothing is
    typed: the planner's values keep executing exactly as before. Fails
    by: a bare launch producing a non-empty override merge."""
    assert frozen_portion_overrides(_launch()) is None
    assert frozen_portion_overrides(_launch(plan_overrides={"epochs": 2})) == {"epochs": 2}


def test_typed_portions_join_the_lock(tmp_path):
    """The repair itself — the defect only this catches: a typed
    (EXPERIMENT_FIXED) portion failing to enter the plan_overrides lock,
    which is the exact dead-transit F2 exists to close. All three portions
    participate (eval joined on Lane C's E1/E2/E3 verdict). Fails by: any
    typed value missing from the merge."""
    merged = frozen_portion_overrides(
        _launch(trial_portion=0.07, train_portion=0.11, eval_portion=0.13)
    )
    assert merged == {"trial_portion": 0.07, "train_portion": 0.11, "eval_portion": 0.13}
    partial = frozen_portion_overrides(_launch(trial_portion=0.07))
    assert partial == {"trial_portion": 0.07}


def test_conflicting_explicit_json_refuses_identical_passes(tmp_path):
    """The two-authorities rule — the defect only this catches: the same key
    arriving from both an explicit --plan_overrides JSON and a typed flag
    with DIFFERENT values being silently resolved by precedence instead of
    refused (a silent winner is F14's defect class). Identical values must
    pass — refusing agreement is pedantry. Fails by: no refusal on
    conflict, or a refusal on agreement."""
    with pytest.raises(ValueError, match="Two authorities for one value"):
        frozen_portion_overrides(_launch(trial_portion=0.07, plan_overrides={"trial_portion": 0.5}))
    merged = frozen_portion_overrides(
        _launch(trial_portion=0.07, plan_overrides={"trial_portion": 0.07, "epochs": 2})
    )
    assert merged == {"trial_portion": 0.07, "epochs": 2}


def test_launch_input_is_never_mutated(tmp_path):
    """The defect only this catches: the merge mutating
    ``launch.plan_overrides`` in place — a frozen dataclass carrying a
    mutable dict whose silent mutation would leak the merge into every
    later reader of the ORIGINAL overrides. Fails by: the source dict
    changing."""
    src = {"epochs": 2}
    launch = _launch(trial_portion=0.07, plan_overrides=src)
    merged = frozen_portion_overrides(launch)
    assert merged == {"epochs": 2, "trial_portion": 0.07}
    assert src == {"epochs": 2}


def test_the_merge_is_wired_at_the_tuner_input_construction():
    """Reachability (the C3 lesson, applied at authoring time this round) —
    the defect only this catches: the helper existing while the production
    tuner-input construction still passes the RAW ``launch.plan_overrides``
    (the merge silently unwired = the dead transit back). AST-based over
    ``model_exploration``: the keyword ``plan_overrides`` at some Call must
    be ``frozen_portion_overrides(launch)``. Fails by: no such keyword
    value anywhere."""
    src = (REPO_ROOT / "src/workflows" / "model_exploration.py").read_text()
    wired = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if (
                    kw.arg == "plan_overrides"
                    and isinstance(kw.value, ast.Call)
                    and getattr(kw.value.func, "id", "") == "frozen_portion_overrides"
                ):
                    wired.append(node.lineno)
    assert wired, (
        "the tuner-input construction no longer routes plan_overrides through "
        "frozen_portion_overrides — the frozen-portion transit is severed"
    )


def test_unfrozen_proposer_transit_resolves_to_the_planner_default():
    """The (b)-semantics leg — the defect only this catches: the proposer
    transit either crashing on None (ProposalInput declares a concrete
    float) or silently reinstating a hand-written constant that drifts
    from the planner's schema. The authority constants must equal the
    ExperimentPlan schema defaults, hardcoded here as the expectation
    (0.02 / 0.1 — the values campaigns actually EXECUTED when unfrozen,
    which is what an estimate should assume). Fails by: either constant
    drifting."""
    from agent.utils.proposer_preflight import (
        UNCONSTRAINED_TRAIN_PORTION,
        UNCONSTRAINED_TRIAL_PORTION,
    )

    assert UNCONSTRAINED_TRIAL_PORTION == 0.02
    assert UNCONSTRAINED_TRAIN_PORTION == 0.1
