"""The planner pairs measured training-phase time with its epoch count."""

from __future__ import annotations

import copy

import pytest

from agent.prompts import get_planner_user_prompt


def _record(*, epochs: int = 2, measured_epochs: int = 2) -> dict:
    return {
        "exp_id": "measured_candidate",
        "status": "success",
        "params": {"train_config": {"epochs": epochs, "batch_size": 8}},
        "timing": {"train_time_s": 780, "validation_time_s": 600, "inference_time_s": 30},
        "runtime_verification": {
            "components": {
                "training": {
                    "actual_seconds": 120,
                    "workload": {"detail": {"epochs": measured_epochs, "steps_per_epoch": 50}},
                }
            }
        },
    }


def test_measured_training_and_epoch_count_reach_real_planner_prompt():
    record = _record()
    original = copy.deepcopy(record)
    prompt = get_planner_user_prompt(
        [record], current_round=2, max_rounds=3, trial_time_budget_minutes=30
    )

    assert "train=13.0 min (validation 10.0 min of that" in prompt
    assert "Measured training phase: 2 epoch(s), 50 steps/epoch, 2.00 min actual" in prompt
    assert "Do not scale the whole attempt time" in prompt
    assert record == original


def test_latest_successful_measurement_survives_condensed_history_window():
    history = [_record()] + [
        {"exp_id": f"later_{i}", "status": "skipped", "memory": {}} for i in range(4)
    ]
    prompt = get_planner_user_prompt(history)
    assert "Measured training phase: 2 epoch(s), 50 steps/epoch, 2.00 min actual" in prompt


@pytest.mark.parametrize(
    "change",
    [
        lambda rec: rec["params"]["train_config"].update(epochs=3),
        lambda rec: rec["runtime_verification"]["components"]["training"].update(
            actual_seconds=None
        ),
        lambda rec: rec["runtime_verification"]["components"]["training"].update(
            actual_seconds=float("nan")
        ),
        lambda rec: rec["runtime_verification"]["components"]["training"]["workload"][
            "detail"
        ].update(steps_per_epoch=0),
        lambda rec: rec.pop("runtime_verification"),
    ],
)
def test_missing_or_incoherent_measurement_does_not_create_timing_claim(change):
    record = _record()
    change(record)
    prompt = get_planner_user_prompt([record])
    assert "Measured training phase:" not in prompt
    assert "train=13.0 min" in prompt


def test_other_task_without_epoch_configuration_keeps_existing_timing_render():
    record = _record()
    record["params"]["train_config"].pop("epochs")
    prompt = get_planner_user_prompt([record])
    assert "Measured training phase:" not in prompt
    assert "train=13.0 min" in prompt


def test_current_cache_provenance_remains_visible_in_planner_history():
    """#419: the native planner must see honest evidence; paper projection is external."""
    record = _record()
    record["runtime_verification"]["storage"] = {"cache_state": "warm_page_cache"}
    before = get_planner_user_prompt([record])
    record["runtime_verification"]["storage"] = {
        "cache_state": "unknown",
        "process_read_bytes_scope": "incomplete",
        "cache_state_unknown_reason": "loader service reads the source",
    }
    after = get_planner_user_prompt([record])
    assert after != before
    assert '"cache_state": "unknown"' in after
    assert "loader service reads the source" in after
    phase_evidence = "Measured training phase: 2 epoch(s), 50 steps/epoch, 2.00 min actual"
    assert phase_evidence in before and phase_evidence in after
