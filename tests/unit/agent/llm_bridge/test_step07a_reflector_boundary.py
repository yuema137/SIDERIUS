"""Step 07a — the REFLECTOR boundary: the training payload never reaches the reflect dump.

Design: ``pr_07a_training_history_diagnosis.md`` §3.7 (hidden at BOTH renders;
parent §8.2 item 4 "MISSING — CAPTURE"). PB-2 already pins the reflector's
BYTES on a test-owned ``actual_results``; WF-2 pins the ``actual_results`` KEY
SET the tuner passes to ``brain.reflect``. Neither sees the MECHANISM: the
tuner's typed boundary (`_interpret_training_status`) hands the reflect merge
EXACTLY the legacy payload (`final_loss` / `loss_history` / `model_params`),
so the additive ``training_history`` — which the trainer now emits inside the
same results dict — cannot enter ``reflect_results = {**train_results,
**score_results}``.

Assertions, each naming its defect:

* the boundary's ``legacy_payload`` on a results dict WITH ``training_history``
  is exactly the legacy keys — merged with the score results it reproduces the
  WF-2 golden's ``actual_results_keys`` (the frozen kwarg-key surface);
* the reflector USER prompt rendered from that legacy payload is
  BYTE-IDENTICAL to the pre-07a render (a train result without the payload);
* MUTATION control: passing the RAW results dict (the pre-07a
  ``train_status.get("results", {})`` line) into the same render CHANGES the
  bytes — the equality above is not vacuous and the tuner-side hiding is the
  mechanism.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from execute_tools.training_history import LEGACY_TRAINING_RESULT_KEYS
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _interpret_training_status,
)
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.unit.agent.llm_bridge.test_step00_prompt_goldens import reflect_fixture_args

_WF2_GOLDEN = (
    Path(__file__).resolve().parents[1]
    / "tune_ml_hyperparam_agent"
    / "goldens"
    / "wf2_reflect_call_surfaces.json"
)

_TRAIN_RESULTS_WITH_HISTORY = {
    "final_loss": 0.0123,
    "loss_history": [0.5, 0.1, 0.0123],
    "model_params": 850_000,
    "training_history": {
        "cadence": "per_epoch",
        "objective_kind": "focal",
        "objective_config_fingerprint": "f" * 64,
        "objective_reduction": "mean",
        "epoch_statistic": "sample_count_weighted_mean_of_batch_criterion",
        "comparability": "established",
        "comparability_reason": None,
        "epochs_planned": 3,
        "epochs_completed": 3,
        "train_objective": [0.5, 0.1, 0.0123],
        "validation_objective": [0.6, 0.2, 0.05],
        "validation_requested_samples": 40,
        "validation_samples": 40,
        "validation_seconds": [0.3, 0.3, 0.3],
        "observations": {},
    },
}
# The score-side keys the tuner merges in on a healthy formal round (WF-2).
_SCORE_RESULTS = {
    "denoising_score": -2.55,
    "file_vector": [None] * 20,
    "is_degenerate": False,
    "failure_reason": None,
    "gate_action": "continue",
    "health_gate_results": [],
}


def _render_reflect(actual_results: dict) -> str:
    exp_id, hypothesis, _fixture_results, context = reflect_fixture_args()
    bridge = BoundaryRecorderBridge()
    bridge.reflect(exp_id, hypothesis, actual_results, context)
    assert len(bridge.captures) == 1
    _method, label, _system, user = bridge.captures[0]
    assert label == "tuner.reflector"
    return user


def _boundary_legacy_payload() -> dict:
    status = {"status": "success", "results": copy.deepcopy(_TRAIN_RESULTS_WITH_HISTORY)}
    _status, results = _interpret_training_status(status, expected_validation=True)
    assert results.history is not None  # the payload DID arrive at the boundary
    return results.legacy_payload


def test_the_legacy_payload_merged_with_scores_is_exactly_the_wf2_key_set():
    """Defect: a boundary that let `training_history` through (or dropped a
    legacy key) would change the kwarg-key surface WF-2 pins at `brain.reflect`."""
    payload = _boundary_legacy_payload()
    assert tuple(payload) == LEGACY_TRAINING_RESULT_KEYS
    merged = {**payload, **_SCORE_RESULTS}
    golden = json.loads(_WF2_GOLDEN.read_text(encoding="utf-8"))
    pinned = golden[0]["actual_results_keys"]
    assert sorted(merged.keys()) == pinned


def test_the_reflector_prompt_is_byte_identical_to_the_pre_07a_render():
    """The bytes the reflector LLM sees are those of a train result WITHOUT
    the payload — the frozen PB-2 surface (the golden file itself is
    unchanged; this pins the mechanism on a payload-carrying input)."""
    payload = _boundary_legacy_payload()
    pre_07a = {k: v for k, v in _TRAIN_RESULTS_WITH_HISTORY.items() if k != "training_history"}
    with_boundary = _render_reflect({**payload, **_SCORE_RESULTS})
    without_payload = _render_reflect({**pre_07a, **_SCORE_RESULTS})
    assert with_boundary == without_payload
    assert "training_history" not in with_boundary
    assert "validation_objective" not in with_boundary


def test_mutation_the_raw_results_dict_would_change_the_reflector_bytes():
    """Control: re-introduce the pre-07a line `train_results =
    train_status.get("results", {})` — the payload leaks into the dump and the
    bytes move. Proves the tuner-side `legacy_payload` is what keeps PB-2 exact."""
    raw = copy.deepcopy(_TRAIN_RESULTS_WITH_HISTORY)
    leaked = _render_reflect({**raw, **_SCORE_RESULTS})
    exact = _render_reflect({**_boundary_legacy_payload(), **_SCORE_RESULTS})
    assert leaked != exact
    assert "training_history" in leaked
