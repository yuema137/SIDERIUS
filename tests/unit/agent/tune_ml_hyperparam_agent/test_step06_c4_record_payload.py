"""Step 06 — C4: the metric's identity/direction/value on every record, additively.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§5, §9, §10, §12, §19 C4.

``ExperimentRecord`` gained ``metric_result`` / ``metric_refusal`` BESIDE the
frozen ``denoising_score`` / ``file_vector`` / ``score_table`` (untouched,
D1). What only these tests catch:

* the LIVE path populates ``metric_result`` from the handle's own result —
  identity, direction, scalar — and it AGREES with ``denoising_score``
  (one value, two names); ``per_sample`` is a POINTER (``file_vector`` on the
  same record), not a second copy (design §5) — which also keeps the planner's
  verbatim history dump from doubling the vector;
* records written BEFORE Step 06 validate unchanged and read ``None``;
* a record whose payload disagrees with the frozen field is REJECTED, but a
  ``failed_mode_collapse`` record — where ``denoising_score`` is the gate
  policy's penalty by design — is not;
* the refusal record carries the structured ``NotScoreableResult``; result and
  refusal are mutually exclusive;
* the storage boundary's ``-inf → null`` image re-validates.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.evaluation_metric import (
    TIDMAD_METRIC_ID,
    MetricResult,
    NotScoreableError,
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
)
from execute_tools.scoring_utils import coerce_nonfinite_to_none
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

_TUNER = importlib.import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")
_HERE = Path(__file__).parent
_PREFLIGHT_FIXTURE = _HERE / "fixtures" / "step00_preflight_results.json"
_REPLAY_WS = _HERE.parents[1] / "core" / "fixtures" / "step00_replay_workspace" / "iter_001"


@pytest.fixture(scope="module")
def pseudo_run(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("step06_c4")
    try:
        output, bridge, sandbox, workspace = run_bounded_pseudo_iteration(
            tmp, mp, preflight_results=preflight
        )
    finally:
        mp.undo()
    return output, bridge, sandbox, workspace


# ---------------------------------------------------------------------------
# 1. The live path populates the payload; it agrees with the frozen fields
# ---------------------------------------------------------------------------


def test_success_records_carry_the_metric_identity_direction_and_value(pseudo_run):
    output, _bridge, sandbox, _ws = pseudo_run
    successes = [r for r in output.all_records if r.status == "success"]
    assert successes, "the bounded iteration produced at least one success record"
    for record in successes:
        payload = record.metric_result
        assert payload is not None
        assert (payload.metric_id, payload.direction) == (TIDMAD_METRIC_ID, "higher")
        assert payload.scalar == record.denoising_score
        assert payload.per_sample is None  # pointer: file_vector on the same record
        assert record.file_vector is not None
        assert record.metric_refusal is None
    # The RAW saved dict (what the planner's history dump sees) has the result
    # key on success entries and never the refusal key.
    saved = {r["exp_id"]: r for r in sandbox.saved_records}
    for record in successes:
        raw = saved[record.exp_id]
        assert "metric_result" in raw and "metric_refusal" not in raw
        assert "per_sample" not in raw["metric_result"]


def test_records_that_never_reached_scoring_carry_no_payload(pseudo_run):
    output, _bridge, sandbox, _ws = pseudo_run
    skipped = [r for r in output.all_records if r.status == "skipped_oom_risk"]
    assert skipped
    for record in skipped:
        assert record.metric_result is None and record.metric_refusal is None
    raw = {r["exp_id"]: r for r in sandbox.saved_records}[skipped[0].exp_id]
    assert "metric_result" not in raw and "metric_refusal" not in raw


# ---------------------------------------------------------------------------
# 2. Historical artifacts validate unchanged
# ---------------------------------------------------------------------------


def test_pre_step06_records_validate_unchanged_and_read_none(pseudo_run):
    """A record exactly as production wrote it before C4 (the same raw dict
    minus the one added key) validates and reads ``metric_result is None``."""
    _output, _bridge, sandbox, _ws = pseudo_run
    replayed = 0
    for raw in sandbox.saved_records:
        legacy = {k: v for k, v in raw.items() if k not in ("metric_result", "metric_refusal")}
        record = ExperimentRecord.model_validate(legacy)
        assert record.metric_result is None and record.metric_refusal is None
        replayed += 1
    assert replayed >= 3


def test_committed_pre_step06_run_output_artifact_validates():
    """The Step-00 replay workspace's real ``run_output_*.json`` (committed
    before Step 06) loads as a ``HyperparamTuningOutput`` without migration.
    (Its sibling ``interpretation_*.json`` is a deliberately MINIMAL resume
    fixture read as a dict by ``core/resume.py``, never a full
    ``InterpretationOutput`` — not a Step-06 surface.)"""
    run_output = json.loads(
        (_REPLAY_WS / "iteration_001" / "pe_wavenet_delta" / "run_output_iter_001.json").read_text()
    )
    out = HyperparamTuningOutput.model_validate(run_output)
    assert all(r.metric_result is None for r in out.all_records)


# ---------------------------------------------------------------------------
# 3. Agreement is validated; the collapse penalty is the documented exception
# ---------------------------------------------------------------------------


def _base_record(**overrides) -> dict:
    record = {
        "exp_id": "e1",
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-08-15 00:00:00",
        "file_index": 6,
        "params": {},
        "denoising_score": 1.5,
        "file_vector": [None] * 5 + [1.5] + [None] * 14,
    }
    record.update(overrides)
    return record


def _payload(scalar: float | None, per_sample=None) -> dict:
    return MetricResult(
        metric_id=TIDMAD_METRIC_ID, direction="higher", scalar=scalar, per_sample=per_sample
    ).model_dump(mode="json")


def test_a_payload_that_disagrees_with_denoising_score_is_rejected():
    with pytest.raises(ValidationError, match="disagrees with denoising_score"):
        ExperimentRecord.model_validate(_base_record(metric_result=_payload(1.4)))


def test_a_payload_whose_evidence_disagrees_with_file_vector_is_rejected():
    with pytest.raises(ValidationError, match="disagrees with file_vector"):
        ExperimentRecord.model_validate(
            _base_record(metric_result=_payload(1.5, per_sample=[None] * 5 + [9.9] + [None] * 14))
        )


def test_the_collapse_penalty_is_not_a_disagreement():
    """``_apply_degeneracy_reaction`` replaces ``denoising_score`` with the
    penalty on a formal collapse; the metric's RAW result stays on the record.
    Source: ``ml_hyperparameter_tune_agent.py::_apply_degeneracy_reaction``."""
    ExperimentRecord.model_validate(
        _base_record(
            status="failed_mode_collapse", denoising_score=-10.0, metric_result=_payload(1.5)
        )
    )


def test_result_and_refusal_are_mutually_exclusive():
    refusal = NotScoreableResult(
        metric_id=TIDMAD_METRIC_ID,
        direction="higher",
        verdict=ScoreabilityVerdict(
            contract_id="tidmad_denoised_h5",
            failures=(ScoreabilityFailure(requirement="completeness", detail="d"),),
        ),
    ).model_dump(mode="json")
    with pytest.raises(ValidationError, match="mutually exclusive"):
        ExperimentRecord.model_validate(
            _base_record(metric_result=_payload(1.5), metric_refusal=refusal)
        )


def test_the_non_finite_sentinel_round_trips_through_the_storage_boundary():
    """In memory the scorer's ``-inf`` sits on BOTH fields; on disk
    ``coerce_nonfinite_to_none`` writes ``null`` on both; both validate."""
    in_memory = _base_record(
        denoising_score=float("-inf"),
        file_vector=[None] * 20,
        metric_result=_payload(float("-inf")),
    )
    ExperimentRecord.model_validate(in_memory)
    on_disk = json.loads(json.dumps(coerce_nonfinite_to_none(in_memory)))
    reloaded = ExperimentRecord.model_validate(on_disk)
    assert reloaded.denoising_score is None
    assert reloaded.metric_result is not None and reloaded.metric_result.scalar is None


# ---------------------------------------------------------------------------
# 4. The refusal record carries the structured result and validates
# ---------------------------------------------------------------------------


def test_the_refusal_record_carries_the_structured_result_and_validates(monkeypatch):
    monkeypatch.setattr(_TUNER.time, "strftime", lambda *_a, **_k: "2026-08-15 00:00:00")
    refusal = NotScoreableResult(
        metric_id=TIDMAD_METRIC_ID,
        direction="higher",
        verdict=ScoreabilityVerdict(
            contract_id="tidmad_denoised_h5",
            failures=(
                ScoreabilityFailure(
                    requirement="required_dtype", input_identity=6, detail="int16 vs int8"
                ),
            ),
        ),
    )
    record = _TUNER._build_scoring_failure_record(
        NotScoreableError(refusal),
        exp_id="e1",
        model_type="wavenet",
        file_index=6,
        record_params={},
        timing={"train_time_s": 1.0, "inference_time_s": 1.0, "scoring_time_s": 0.1},
        expert_advice_str="",
        hypothesis="h",
        round_index=1,
        attempt_in_round=1,
    )
    parsed = ExperimentRecord.model_validate(record)
    assert parsed.status == "error_scoring"
    assert parsed.metric_result is None
    assert parsed.metric_refusal is not None
    assert parsed.metric_refusal.metric_id == TIDMAD_METRIC_ID
    assert parsed.metric_refusal.verdict.failures[0].requirement == "required_dtype"
    assert parsed.metric_refusal.verdict.failures[0].input_identity == 6
