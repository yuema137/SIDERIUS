"""Step 06 — the LLM boundary: the record-only metric payload never reaches the planner.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§8 ("Step 06 changes no prompt"; agent-facing rendering is Step 07a / 09),
ledger §20.11 (operator-directed corrective after the adversarial review).

The metric interface's payload (``ExperimentRecord.metric_result`` /
``metric_refusal``) is PERSISTED so Steps 07a / 09 can consume it, but it is
not agent-facing yet. The planner's history context json-dumps the last
``full_window`` records VERBATIM (``agent/prompts.py::_truncate_memory_history``
→ ``get_planner_user_prompt``), which is exactly how an additive record key
would leak into an LLM message. This module pins the boundary at the render:

* the planner user prompt is BYTE-IDENTICAL for a record with and without
  the payload — i.e. identical to what a pre-Step-06 record rendered — in the
  verbatim window and in the condensed tail;
* the persisted record is untouched (the filter is a rendering decision, not
  a persistence one);
* the collapse case the review flagged: a ``failed_mode_collapse`` record
  renders ONLY its policy-adjusted ``denoising_score``, never the raw metric
  scalar beside it.

The Step-00 PB-1 goldens pin the RENDERER on a test-owned history; they cannot
see production record content, which is why this test exists.

**UPGRADED at Step 07a C3** (design pr_07a §3.7): the same mechanism now hides
the trainer's ``training_history`` and the derived ``training_diagnosis`` —
persisted evidence in 07a, rendered SELECTIVELY by 07b, interpreted by Step
09. Every assertion below runs with BOTH generations of hidden keys present
on the input records, so a regression in either is a visible diff here.
"""

from __future__ import annotations

import copy

from agent.prompts import _PLANNER_HIDDEN_RECORD_KEYS, _truncate_memory_history
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.unit.agent.llm_bridge.test_step00_prompt_goldens import (
    _HISTORY_3,
    planner_fixture_kwargs,
)

_PAYLOAD = {
    "metric_id": "tidmad_denoising_score",
    "direction": "higher",
    "scalar": -2.55,
    "references_used": ["anchor_map"],
}
_REFUSAL = {
    "metric_id": "tidmad_denoising_score",
    "direction": "higher",
    "verdict": {
        "contract_id": "tidmad_denoised_h5",
        "failures": [
            {
                "requirement": "required_dtype",
                "input_identity": 6,
                "detail": "stored as 'int16', required 'int8'",
            }
        ],
    },
}


# Step 07a — the two record keys hidden by the same mechanism (design §3.7).
_TRAINING_HISTORY = {
    "cadence": "per_epoch",
    "objective_kind": "focal",
    "objective_config_fingerprint": "f" * 64,
    "objective_reduction": "mean",
    "epoch_statistic": "sample_count_weighted_mean_of_batch_criterion",
    "comparability": "established",
    "comparability_reason": None,
    "epochs_planned": 3,
    "epochs_completed": 3,
    "train_objective": [2.9, 2.4, 2.1],
    "validation_objective": [3.0, 2.5, 2.6],
    "validation_requested_samples": 24,
    "validation_samples": 24,
    "validation_seconds": [0.4, 0.4, 0.4],
    "observations": {},
}
_TRAINING_DIAGNOSIS = {
    "state": "ok",
    "validation_state": "present",
    "best_validation_epoch": 1,
    "validation_degraded_after_best": True,
    "train_trend": "decreasing",
    "validation_trend": "decreasing",
}
_STEP07A_KEYS = ("training_history", "training_diagnosis")


def _with_payload(records: list[dict]) -> list[dict]:
    out = copy.deepcopy(records)
    for rec in out:
        rec["metric_result"] = dict(_PAYLOAD, scalar=rec.get("denoising_score"))
        rec["training_history"] = copy.deepcopy(_TRAINING_HISTORY)
        rec["training_diagnosis"] = copy.deepcopy(_TRAINING_DIAGNOSIS)
    out[0]["metric_result"] = None
    out[0]["metric_refusal"] = _REFUSAL
    return out


def _render(history: list[dict]) -> str:
    """The USER message as it crosses ``LLMBridge._chat_json`` — the real LLM
    boundary (PB-1's ``BoundaryRecorderBridge``, network-guarded), with every
    other ``plan()`` parameter pinned by the shared fixture surface."""
    kwargs = planner_fixture_kwargs()
    kwargs["memory_history"] = history
    bridge = BoundaryRecorderBridge()
    bridge.plan(**kwargs)
    assert len(bridge.captures) == 1
    _method, label, _system, user = bridge.captures[0]
    assert label == "tuner.planner"
    return user


def test_the_planner_prompt_is_byte_identical_with_and_without_the_payload():
    """Verbatim window (three records): a pre-Step-06 record and the same
    record carrying ``metric_result`` / ``metric_refusal`` render the SAME
    bytes. This is the exact LLM boundary a Step-06 record key would cross."""
    plain = _render(_HISTORY_3)
    loaded = _render(_with_payload(_HISTORY_3))
    assert loaded == plain
    assert "metric_result" not in loaded and "metric_refusal" not in loaded
    # Step 07a: neither the history nor the diagnosis leaks — not the keys,
    # not a value that exists ONLY inside them (the R3 list, the epoch stat).
    for key in _STEP07A_KEYS:
        assert key not in loaded
    assert "validation_objective" not in loaded
    assert "sample_count_weighted_mean_of_batch_criterion" not in loaded
    assert "best_validation_epoch" not in loaded
    # ...and the payload WAS present in the input, so the equality is not vacuous.
    assert any("metric_result" in rec for rec in _with_payload(_HISTORY_3))
    assert all(all(k in rec for k in _STEP07A_KEYS) for rec in _with_payload(_HISTORY_3))


def test_the_condensed_tail_never_carries_the_payload_either():
    """Six records: three condensed + three verbatim — no position renders it."""
    six = _with_payload(_HISTORY_3 + copy.deepcopy(_HISTORY_3))
    for i, rec in enumerate(six):
        rec["exp_id"] = f"exp_{i:03d}"
    windowed = _truncate_memory_history(six)
    assert len(windowed) == 6
    for entry in windowed:
        assert not (_PLANNER_HIDDEN_RECORD_KEYS & entry.keys()), entry.keys()
    rendered = _render(six)
    assert "metric_result" not in rendered
    for key in _STEP07A_KEYS:
        assert key not in rendered


def test_the_persisted_record_is_untouched_by_the_render():
    """The filter is a RENDERING decision: the input dicts keep their keys
    (the record on disk, and what Steps 07a/09 will read, is unchanged)."""
    loaded = _with_payload(_HISTORY_3)
    before = copy.deepcopy(loaded)
    _truncate_memory_history(loaded)
    _render(loaded)
    assert loaded == before
    assert "metric_result" in loaded[1] and "metric_refusal" in loaded[0]
    assert "training_history" in loaded[1] and "training_diagnosis" in loaded[1]


def test_a_collapsed_formal_record_renders_only_the_policy_adjusted_score():
    """The ambiguity the review flagged: on a ``failed_mode_collapse`` record
    ``denoising_score`` is the gate policy's penalty while
    ``metric_result.scalar`` is the raw evaluation. The planner must see ONE
    number — the policy-adjusted one it always saw — not both."""
    collapsed = copy.deepcopy(_HISTORY_3[-1])
    collapsed.update(
        {
            "status": "failed_mode_collapse",
            "denoising_score": -10.0,
            "failure_reason": "[amplitude_collapse] flat output",
            "metric_result": dict(_PAYLOAD, scalar=1.37),
        }
    )
    rendered = _render([collapsed])
    assert '"denoising_score": -10.0' in rendered
    assert "1.37" not in rendered
    assert "metric_result" not in rendered


def test_the_hidden_key_set_is_exactly_the_step06_and_step07a_payloads():
    """A guard on scope: the set holds Step 06's two metric keys and Step 07a's
    two training-evidence keys — 07a HIDES, 07b RENDERS selected facts, Step
    09 INTERPRETS. Widening it (hiding other record data from the planner) or
    narrowing it (leaking a payload) is a Gate-1-visible byte change owned by
    those steps, not a tidy-up — the set is pinned so either move is a
    visible diff."""
    assert _PLANNER_HIDDEN_RECORD_KEYS == frozenset(
        {"metric_result", "metric_refusal", "training_history", "training_diagnosis"}
    )
