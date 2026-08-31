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
from tests.helpers.tuner_prompt_fixtures import HISTORY, planner_kwargs

_PAYLOAD = {
    "metric_id": "fixture_quality",
    "direction": "higher",
    "scalar": -2.55,
    "references_used": ["fixture_reference"],
}
_REFUSAL = {
    "metric_id": "fixture_quality",
    "direction": "higher",
    "verdict": {
        "contract_id": "fixture_deliverable",
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
    kwargs = planner_kwargs()
    kwargs["memory_history"] = history
    bridge = BoundaryRecorderBridge()
    bridge.plan(**kwargs)
    assert len(bridge.captures) == 1
    _method, label, _system, user = bridge.captures[0]
    assert label == "tuner.planner"
    return user


#: The heading of the block Step 07 PR 07b renders FROM the hidden diagnosis.
_DYNAMICS_HEADING = "### Training dynamics"


def _without_dynamics_block(prompt: str) -> str:
    """The prompt minus the owned training-dynamics block.

    07b renders a compact SUMMARY of ``training_diagnosis``, so the prompt is
    no longer byte-identical with and without that payload — and must not be,
    or the render would be doing nothing. What must still be identical is
    everything else, above all the json-dumped history: that is where a raw
    record key would actually leak.
    """
    if _DYNAMICS_HEADING not in prompt:
        return prompt
    head, _, tail = prompt.partition(_DYNAMICS_HEADING)
    _block, sep, rest = tail.partition("\n\n")
    return head + (rest if sep else "")


def test_the_planner_prompt_is_byte_identical_with_and_without_the_payload():
    """Verbatim window (three records): a pre-Step-06 record and the same
    record carrying ``metric_result`` / ``metric_refusal`` render the SAME
    bytes everywhere the raw record is serialised.

    **UPGRADED at Step 07 PR 07b.** The claim is now stated where it is still
    true, and it is a sharper claim than before: the *history JSON and all
    surrounding prose* are byte-identical, while the *owned dynamics block*
    deliberately differs — that block is 07b rendering the diagnosis, and
    asserting whole-prompt equality would have meant asserting the feature does
    nothing. The absence assertions below still run against the FULL prompt, so
    a raw key or an inner-only value leaking into the rendered block is caught.
    """
    plain = _render(HISTORY)
    loaded = _render(_with_payload(HISTORY))
    assert _without_dynamics_block(loaded) == _without_dynamics_block(plain)
    # ...and the render really is live: the block exists and reflects the
    # payload, so the equality above is not achieved by rendering nothing.
    assert _DYNAMICS_HEADING in loaded
    assert loaded != plain
    assert "metric_result" not in loaded and "metric_refusal" not in loaded
    # Step 07a: neither the history nor the diagnosis leaks — not the keys,
    # not a value that exists ONLY inside them (the R3 list, the epoch stat).
    for key in _STEP07A_KEYS:
        assert key not in loaded
    assert "validation_objective" not in loaded
    assert "sample_count_weighted_mean_of_batch_criterion" not in loaded
    assert "best_validation_epoch" not in loaded
    # ...and the payload WAS present in the input, so the equality is not vacuous.
    assert any("metric_result" in rec for rec in _with_payload(HISTORY))
    assert all(all(k in rec for k in _STEP07A_KEYS) for rec in _with_payload(HISTORY))


def test_the_condensed_tail_never_carries_the_payload_either():
    """Six records: three condensed + three verbatim — no position renders it."""
    six = _with_payload(HISTORY + copy.deepcopy(HISTORY))
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
    loaded = _with_payload(HISTORY)
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
    collapsed = copy.deepcopy(HISTORY[-1])
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


def test_the_hidden_key_set_is_exactly_the_step06_step07a_step10_and_robs1_payloads():
    """A guard on scope: Step 06's two metric keys, Step 07a's two
    training-evidence keys, Step 10 / P2b's three secondary-metric keys, and
    `R-OBS-1`'s `static_observations` —
    07a HIDES, 07b RENDERS selected facts, Step 09 INTERPRETS, P2b transports.
    Widening it (hiding other record data from the planner) or narrowing it
    (leaking a payload) is a byte change owned by those steps, not a tidy-up —
    the set is pinned so either move is a visible diff.

    P2b's widening is byte-neutral on every EXISTING prompt, which is why it
    needs no Gate-1 evidence and why `test_widening_the_set_moved_no_existing_
    prompt_byte` below is the load-bearing half of this pin: the three keys are
    written onto a record only when a run DECLARED secondaries, TIDMAD declares
    none, and a record without them takes `_planner_visible`'s identity branch.

    `R-OBS-1` widens it by exactly one key on the same terms and for a stronger
    reason: an observable is DIAGNOSTIC by construction — `D-BUD-16` forbids it
    becoming a budget or selection mechanism — so putting one in front of the
    planner is precisely the vote it must never get. Byte-neutral on every
    existing prompt by the same argument: `records.py` writes the key only when
    a run declared a static observable, and no shipped manifest declares one.
    Its DYNAMIC sibling needs no entry, because it rides `training_history`,
    which this set has hidden since 07a.
    """
    assert _PLANNER_HIDDEN_RECORD_KEYS == frozenset(
        {
            "metric_result",
            "metric_refusal",
            "training_history",
            "training_diagnosis",
            "secondary_metric_results",
            "secondary_metric_refusals",
            "secondary_metric_errors",
            "static_observations",
        }
    )


def test_widening_the_set_moved_no_existing_prompt_byte():
    """Step 10 / P2b: hiding keys that a pre-P2b record cannot carry changes
    nothing for any run that does not declare a secondary.

    The claim is stated as an equivalence against the PRE-P2b key set rather
    than as "the output looks right": for any record that carries none of the
    three new keys, filtering with the widened set must produce exactly what
    filtering with the old set produced — same keys, same ORDER, same values.
    Key order matters because the filtered dict is `json.dumps`ed into the
    prompt, so a reordering is a byte change even when the content is equal.
    """
    from agent.prompts import _planner_visible

    pre_p2b_keys = {"metric_result", "metric_refusal", "training_history", "training_diagnosis"}
    assert pre_p2b_keys < set(_PLANNER_HIDDEN_RECORD_KEYS), "P2b only WIDENS the set"

    history = copy.deepcopy(HISTORY)
    assert not any(k.startswith("secondary_") for rec in history for k in rec), (
        "these fixtures predate P2b — that is the point of using them here"
    )
    for rec in history:
        as_before = {k: v for k, v in rec.items() if k not in pre_p2b_keys}
        after = _planner_visible(rec)
        assert list(after.items()) == list(as_before.items())

    # A record with NO hidden key at all still takes the identity branch, so
    # nothing is rebuilt and no key can be reordered.
    bare = {k: v for k, v in history[-1].items() if k not in _PLANNER_HIDDEN_RECORD_KEYS}
    assert _planner_visible(bare) is bare

    rendered = _render(history)
    for key in _PLANNER_HIDDEN_RECORD_KEYS:
        assert key not in rendered
