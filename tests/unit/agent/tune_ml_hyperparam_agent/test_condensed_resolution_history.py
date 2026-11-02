"""Issue #1322: condensed planner history must not present an overridden proposal as what ran.

Each witness drives the real tuner loop (planning, resolution, record building
and the shared ``_emit_record`` persistence seam) for one attempt whose authored
``lr`` is replaced by an operator ``plan_overrides`` lock, then renders the real
planner prompt with that record pushed out of the verbatim window. The expected
values are literals taken from the scenario (authored 1e-4, locked 0.002), not
re-derived from the implementation under test.
"""

from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from agent.prompts import PLANNER_FULL_WINDOW, get_planner_user_prompt
from agent.schemas.hyperparam_tuning import ExperimentPlan
from nodes.ml_hyperparameter_tune_agent.parameter_rule_receipts import (
    attach_attempt_receipts,
    resolution_event_record,
)
from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker
from tests.unit.agent.tune_ml_hyperparam_agent.test_physical_rejection_capture import (
    FAKE_PLAN,
    FAKE_VRAM_OK,
    _make_input,
    _make_oom_payload,
    _setup,
    agent_with_scripted_skill,  # pytest fixture, resolved by name
)

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")

_FIXTURE = "tests.unit.agent.tune_ml_hyperparam_agent.test_physical_rejection_capture"

_LR_EVENT = {
    "field_path": "train_cfg.lr",
    "proposed": "0.0001",
    "executed": "0.002",
    "authority": "operator_plan_overrides",
}
_STATUS = {"success": "success", "skip": "skipped_oom_risk", "error": "error_training"}


def _run_one_attempt(tmp_path, agent_with_scripted_skill, outcome, overrides, plan=None):
    verdict = _make_oom_payload() if outcome == "skip" else FAKE_VRAM_OK
    with patch(f"{_FIXTURE}.FAKE_PLAN", {**FAKE_PLAN, **(plan or {})}):
        agent, saved, _, cleanup = _setup(agent_with_scripted_skill, [verdict])
    inputs = _make_input(tmp_path, max_rounds=1)
    inputs.plan_overrides = overrides
    train = (
        {"status": "error", "message": "synthetic training failure"}
        if outcome == "error"
        else {"status": "success", "results": {"final_loss": 0.5, "model_params": 100000}}
    )
    try:
        with patch(f"{_FIXTURE}.FAKE_TRAIN", train):
            agent.run(inputs)
    finally:
        cleanup()
    assert len(saved) == 1
    record = saved[0]
    assert record["status"] == _STATUS[outcome]
    return record


def _later(i: int) -> dict:
    return {
        "exp_id": f"later_{i}",
        "status": "success",
        "memory": {"hypothesis": f"later {i}", "round_index": 2 + i},
    }


def _planner_history(prompt: str) -> list[dict]:
    """The history JSON block exactly as the planner reads it."""
    start = prompt.index("[\n  {")
    history, _ = json.JSONDecoder().raw_decode(prompt[start:])
    return history


@pytest.mark.parametrize("outcome", ["success", "skip", "error"])
def test_overridden_proposal_is_labelled_with_effective_values_after_condensation(
    tmp_path, agent_with_scripted_skill, outcome
):
    """Fails on master: the condensed entry keeps ``hypothesis`` but drops every
    effective value, so ``resolution_events`` and the supersession label are absent."""
    record = _run_one_attempt(
        tmp_path, agent_with_scripted_skill, outcome, {"train_config": {"lr": 0.002}}
    )
    # The effective request is what the record's configuration describes...
    assert record["params"]["train_config"]["lr"] == 0.002
    # ...and the transport key never stays inside the configuration params.
    assert "resolution_events" not in record["params"]
    assert _LR_EVENT in record["resolution_events"]

    history = [record] + [_later(i) for i in range(PLANNER_FULL_WINDOW)]
    original = deepcopy(history)
    rendered = _planner_history(get_planner_user_prompt(history))
    condensed = rendered[0]

    assert "params" not in condensed  # still condensed, not a verbatim copy
    assert condensed["status"] == _STATUS[outcome]
    assert _LR_EVENT in condensed["resolution_events"]
    memory = condensed["memory"]
    assert memory["hypothesis"] == "h"  # authored prose retained verbatim
    assert memory["hypothesis_provenance"].startswith("Superseded proposal")
    assert list(memory)[:2] == ["hypothesis", "hypothesis_provenance"]
    # The same evidence and label hold while the record is still verbatim.
    recent = _planner_history(get_planner_user_prompt(history[:PLANNER_FULL_WINDOW]))[0]
    assert _LR_EVENT in recent["resolution_events"]
    assert recent["memory"]["hypothesis_provenance"] == memory["hypothesis_provenance"]
    assert history == original  # projection never mutates the persisted history


def test_unchanged_control_keeps_record_and_condensed_bytes(tmp_path, agent_with_scripted_skill):
    """A plan that survives resolution intact must persist no receipt and render
    no label (fails if the receipt is written for an empty provenance, or the
    label is keyed on the hypothesis rather than on recorded divergence).

    The control authors the formal mode and evaluation fraction the round
    resolves to, so the real tracker reports no disagreement.
    """
    record = _run_one_attempt(
        tmp_path,
        agent_with_scripted_skill,
        "success",
        {},
        plan={"is_trial": False, "eval_portion": 1.0},
    )
    assert record["params"]["train_config"]["lr"] == 0.0001
    assert "resolution_events" not in record

    history = [record] + [_later(i) for i in range(PLANNER_FULL_WINDOW)]
    condensed = _planner_history(get_planner_user_prompt(history))[0]
    assert "resolution_events" not in condensed
    assert list(condensed["memory"]) == ["hypothesis", "conclusion", "round_index"]


@pytest.mark.parametrize("files", [4, 2000])
def test_condensed_list_valued_events_stay_bounded_for_many_file_tasks(files):
    """A file-list event renders whole (``repr``) and grows with the task's file
    count; condensed entries must cap it while the record and verbatim window
    keep the full value. Fails if the condensed projection copies events
    unbounded (2000 indices are ~10 kB per value) or truncates the record."""
    authored = ExperimentPlan(
        hypothesis="target files",
        is_trial=True,
        trial_strategy="target",
        target_files=list(range(files)),
    )
    resolved = authored.model_copy(update={"target_files": list(reversed(range(files)))})
    provenance = ResolutionTracker(authored).finish(resolved)
    record = {
        "exp_id": "many_files_001",
        "status": "success",
        "params": {**resolution_event_record(provenance), "train_config": {"lr": 0.001}},
        "memory": {"hypothesis": "target files", "round_index": 1},
    }
    attach_attempt_receipts(record)
    full = next(e for e in record["resolution_events"] if e["field_path"] == "target_files")
    assert full["executed"] == repr(list(reversed(range(files))))  # persisted whole

    history = [record] + [_later(i) for i in range(PLANNER_FULL_WINDOW)]
    original = deepcopy(history)
    condensed = _planner_history(get_planner_user_prompt(history))[0]
    event = next(e for e in condensed["resolution_events"] if e["field_path"] == "target_files")
    for value, whole in (
        (event["proposed"], full["proposed"]),
        (event["executed"], full["executed"]),
    ):
        assert len(value) <= 160  # stated bound per condensed event value
        if len(whole) <= 120:
            assert value == whole  # short values are never altered
        else:
            assert value.startswith(whole[:60]) and value.endswith(whole[-20:])
            assert f"({len(whole)} chars; full value in the persisted record)" in value
    assert len(json.dumps(condensed)) < 2_000  # whole entry independent of file count
    recent = _planner_history(get_planner_user_prompt(history[:1]))[0]
    assert recent["resolution_events"] == record["resolution_events"]  # verbatim stays full
    assert history == original
