"""Step 07a C3 — the tuner's typed training-results boundary, the record
attachment and the live pseudo path (design §3.4a, §3.5, §3.6, §3.8).

Families, each naming the defect only it catches:

* `_interpret_training_status` — the boundary that turns a contract failure
  into the EXISTING training-failure status shape (`error_training`), passes
  non-success statuses through, and hands the reflect merge EXACTLY the
  legacy payload;
* `ExperimentRecord` — the two additive fields, the consistency validator's
  negatives, pre-07a records unchanged, and a resume-style mix;
* the LIVE pseudo path (`run_bounded_pseudo_iteration`, RecordingSandbox
  replaying the upgraded pseudo train outputs through the REAL tuner):
  every success record carries `training_history` (R2 + R3) and a
  `training_diagnosis` with `state="ok"`, `validation_state="present"`;
  skip records carry None; the eval SampleSet the tuner built reached the
  executor (transport reachability through the real wrapper);
* delete-the-hop reachability: the diagnosis on the persisted record IS the
  output of the tuner's `derive_training_diagnosis` call (a monkeypatched
  derivation shows up on the record);
* §3.4a MUTATION half 2 (LIVE): pre-07a canned training results (no
  `training_history`) on attempts that BUILT an eval SampleSet → every
  attempt is an `error_training` record, never a success record with
  `validation_state="absent"`; the SAME payload on a legacy attempt (no eval
  set) → a success-shaped result with `validation_state="absent"`.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path

import pytest

_tuner_execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")
from pytest import MonkeyPatch

import tests.helpers.recording_sandbox as recording_sandbox_module
from agent.schemas.hyperparam_tuning import ExperimentRecord
from agent.schemas.training_diagnosis import TrainingDiagnosis, derive_training_diagnosis
from execute_tools.training_history import LEGACY_TRAINING_RESULT_KEYS, TrainingHistory
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

# importlib because the package __init__ re-exports shadow the module name
# (the same quirk the tuner unit conftest and the step00 helper work around).
tuner_module = importlib.import_module(
    "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
)
_interpret_training_status = tuner_module._interpret_training_status

_PREFLIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "step00_preflight_results.json"

_HISTORY = {
    "cadence": "per_epoch",
    "objective_kind": "focal",
    "objective_config_fingerprint": "f" * 64,
    "objective_reduction": "mean",
    "epoch_statistic": "sample_count_weighted_mean_of_batch_criterion",
    "comparability": "established",
    "comparability_reason": None,
    "epochs_planned": 3,
    "epochs_completed": 3,
    "train_objective": [3.0, 2.0, 1.0],
    "validation_objective": [3.1, 2.1, 1.1],
    "validation_requested_samples": 8,
    "validation_samples": 8,
    "validation_seconds": [0.1, 0.1, 0.1],
    "observations": {},
}


def _success_status(with_history: bool = True, **overrides) -> dict:
    results = {"final_loss": 1.0, "loss_history": [3.0, 2.0, 1.0], "model_params": 10}
    if with_history:
        results["training_history"] = copy.deepcopy(_HISTORY)
    results.update(overrides)
    return {
        "status": "success",
        "message": "ok",
        "results": results,
        "runtime_verification": {"x": 1},
    }


# ---------------------------------------------------------------------------
# _interpret_training_status
# ---------------------------------------------------------------------------


class TestInterpretTrainingStatus:
    def test_success_with_history_yields_the_legacy_payload_and_the_typed_history(self):
        status, results = _interpret_training_status(_success_status(), expected_validation=True)
        assert status["status"] == "success"
        assert tuple(results.legacy_payload) == LEGACY_TRAINING_RESULT_KEYS
        assert "training_history" not in results.legacy_payload  # the reflect merge never sees it
        assert results.history is not None and results.history.validation_objective == [
            3.1,
            2.1,
            1.1,
        ]
        assert results.history_payload() == _HISTORY

    def test_expected_validation_without_r3_is_rewritten_into_the_existing_error_shape(self):
        """§3.4a: the tuner built an eval SampleSet; the results carry no R3 →
        the status becomes the pre-existing training-error shape (recorded as
        `error_training` by the orchestrator's existing branch), never success."""
        status, results = _interpret_training_status(
            _success_status(with_history=False), expected_validation=True
        )
        assert status["status"] == "error"
        assert status["message"].startswith("error_training:")
        assert "contract violated" in status["message"]
        assert status["error_type"] == "training_results_contract"
        assert status["runtime_verification"] == {"x": 1}  # evidence preserved for _emit_record
        assert results.history is None and results.legacy_payload == {}

    def test_legacy_attempt_without_r3_is_the_honest_absent_state(self):
        status, results = _interpret_training_status(
            _success_status(with_history=False), expected_validation=False
        )
        assert status["status"] == "success"
        assert results.history is None and results.history_state == "absent"
        assert derive_training_diagnosis(results.history).state == "absent"
        # A legacy PRODUCER that emits the payload with R3 None (run_experiment):
        legacy_payload = dict(
            _HISTORY,
            validation_objective=None,
            validation_requested_samples=None,
            validation_samples=None,
            validation_seconds=None,
        )
        status, results = _interpret_training_status(
            _success_status(training_history=legacy_payload), expected_validation=False
        )
        assert status["status"] == "success"
        d = derive_training_diagnosis(results.history)
        assert d.state == "ok" and d.validation_state == "absent"

    def test_malformed_payload_is_rewritten_into_the_error_shape(self):
        bad = _success_status(training_history=dict(_HISTORY, validation_samples=7))
        status, _ = _interpret_training_status(bad, expected_validation=True)
        assert status["status"] == "error" and "schema-invalid" in status["message"]

    @pytest.mark.parametrize(
        "status",
        [
            {"status": "error", "message": "boom"},
            {"status": "rejected_time_risk", "message": "r"},
            {"status": "skipped_resource_admission"},
        ],
    )
    def test_non_success_statuses_pass_through_untouched(self, status):
        out, results = _interpret_training_status(dict(status), expected_validation=True)
        assert out == status
        assert results.legacy_payload == {} and results.history is None


# ---------------------------------------------------------------------------
# ExperimentRecord attachment + validator
# ---------------------------------------------------------------------------


def _record(**fields) -> dict:
    base = {
        "exp_id": "e1",
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "t",
        "file_index": 6,
        "params": {},
        "final_loss": 1.0,
        "loss_history": [3.0, 2.0, 1.0],
        "model_params": 10,
    }
    base.update(fields)
    return base


class TestExperimentRecordAttachment:
    def test_pre_07a_records_validate_unchanged_with_both_fields_none(self):
        rec = ExperimentRecord.model_validate(_record())
        assert rec.training_history is None and rec.training_diagnosis is None

    def test_a_consistent_record_round_trips(self):
        d = derive_training_diagnosis(TrainingHistory.model_validate(_HISTORY))
        rec = ExperimentRecord.model_validate(
            _record(training_history=_HISTORY, training_diagnosis=d.model_dump())
        )
        again = ExperimentRecord.model_validate(rec.model_dump(mode="json"))
        assert again.training_history == rec.training_history
        assert again.training_diagnosis == rec.training_diagnosis
        assert again.training_diagnosis is not None and again.training_diagnosis.state == "ok"

    def test_history_disagreeing_with_loss_history_is_rejected(self):
        with pytest.raises(ValueError, match="disagrees with loss_history"):
            ExperimentRecord.model_validate(
                _record(loss_history=[3.0, 2.0, 0.5], training_history=_HISTORY)
            )

    def test_final_loss_not_the_last_r2_is_rejected(self):
        with pytest.raises(ValueError, match="OD-S7-3"):
            ExperimentRecord.model_validate(_record(final_loss=0.9, training_history=_HISTORY))

    def test_diagnosis_epoch_count_disagreeing_with_the_history_is_rejected(self):
        d = TrainingDiagnosis(state="ok", validation_state="present", epochs_completed=2)
        with pytest.raises(ValueError, match="epochs_completed"):
            ExperimentRecord.model_validate(
                _record(training_history=_HISTORY, training_diagnosis=d.model_dump())
            )

    def test_an_ok_diagnosis_without_a_history_is_rejected_but_absent_is_fine(self):
        ok = TrainingDiagnosis(state="ok", validation_state="present", epochs_completed=3)
        with pytest.raises(ValueError, match="requires a training_history"):
            ExperimentRecord.model_validate(_record(training_diagnosis=ok.model_dump()))
        absent = derive_training_diagnosis(None)
        rec = ExperimentRecord.model_validate(_record(training_diagnosis=absent.model_dump()))
        assert rec.training_diagnosis is not None and rec.training_diagnosis.state == "absent"

    def test_a_resume_style_mix_of_pre_and_post_07a_records_validates(self):
        """`core/resume.py` reloads records through `ExperimentRecord`; a resumed
        pre-07a run mixes records with and without the fields — both valid."""
        d = derive_training_diagnosis(TrainingHistory.model_validate(_HISTORY))
        mixed = [
            _record(exp_id="old"),
            _record(exp_id="new", training_history=_HISTORY, training_diagnosis=d.model_dump()),
            _record(
                exp_id="skip",
                status="skipped_oom_risk",
                final_loss=None,
                loss_history=None,
                model_params=None,
            ),
        ]
        recs = [ExperimentRecord.model_validate(r) for r in mixed]
        assert [r.training_history is not None for r in recs] == [False, True, False]


# ---------------------------------------------------------------------------
# LIVE pseudo path through the real tuner
# ---------------------------------------------------------------------------


def _preflight() -> list[dict]:
    return json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]


@pytest.fixture(scope="module")
def pseudo_run(tmp_path_factory):
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("step07a_c3")
    try:
        out = run_bounded_pseudo_iteration(tmp, mp, preflight_results=_preflight())
    finally:
        mp.undo()
    return out


class TestLivePseudoPath:
    def test_every_success_record_carries_history_and_an_ok_present_diagnosis(self, pseudo_run):
        output, _bridge, sandbox, _ws = pseudo_run
        successes = [r for r in output.all_records if r.status == "success"]
        assert successes, "the pseudo iteration must produce success records"
        for rec in successes:
            h = rec.training_history
            assert h is not None and h.validation_objective is not None
            assert len(h.train_objective) == 5 and len(h.validation_objective) == 5
            assert h.train_objective == rec.loss_history
            d = rec.training_diagnosis
            assert d is not None and d.state == "ok" and d.validation_state == "present"
            assert d.best_validation_epoch == 4  # the pseudo validation curve is monotone
        others = [r for r in output.all_records if r.status != "success"]
        for rec in others:
            assert rec.training_history is None
        # Transport reachability through the REAL wrapper: the tuner-built eval
        # SampleSet reached the executor boundary on every training call.
        assert sandbox.training_kwargs and all(
            kw.get("eval_sample_set") for kw in sandbox.training_kwargs
        )

    def test_the_persisted_records_on_disk_carry_both_fields(self, pseudo_run):
        _output, _bridge, sandbox, _ws = pseudo_run
        saved = [r for r in sandbox.saved_records if r.get("status") == "success"]
        assert saved
        for r in saved:
            assert "training_history" in r and "training_diagnosis" in r
            assert r["training_diagnosis"]["state"] == "ok"


class TestDeleteTheHop:
    def test_the_records_diagnosis_is_the_output_of_the_tuner_call(self, tmp_path, monkeypatch):
        """Reachability: monkeypatch `derive_training_diagnosis` AS SEEN BY THE
        TUNER to a sentinel-producing function — the persisted record carries
        the sentinel. A tuner that derived the diagnosis elsewhere (or not at
        all) would leave this RED."""
        sentinel = TrainingDiagnosis(state="absent", validation_state="absent", flat_rel_tol=0.123)
        # AS SEEN BY THE CALLER: the diagnosis is derived inside the node's
        # private `execution` module (Step 07 PR 07b, C7d).
        monkeypatch.setattr(_tuner_execution, "derive_training_diagnosis", lambda _h: sentinel)
        output, _bridge, _sandbox, _ws = run_bounded_pseudo_iteration(
            tmp_path, monkeypatch, preflight_results=_preflight()
        )
        successes = [r for r in output.all_records if r.status == "success"]
        assert successes
        assert all(r.training_diagnosis == sentinel for r in successes)


class TestExpectedValidationMutationHalf2:
    def test_pre_07a_training_results_on_an_expecting_attempt_record_error_training(
        self, tmp_path, monkeypatch
    ):
        """§3.4a half 2 (LIVE): strip `training_history` from the canned pseudo
        results (the pre-07a producer) while the tuner builds an eval SampleSet
        for every attempt → NO success record; every attempt that trained is
        `error_training` with the contract message. The pre-07a tuner would
        have written a success record here."""
        real_load = recording_sandbox_module.load_pseudo_data

        def stripped(category, name):
            canned = real_load(category, name)
            entries = canned["execute_training"]
            for e in entries if isinstance(entries, list) else [entries]:
                e["results"].pop("training_history", None)
            return canned

        monkeypatch.setattr(recording_sandbox_module, "load_pseudo_data", stripped)
        output, _bridge, sandbox, _ws = run_bounded_pseudo_iteration(
            tmp_path, monkeypatch, preflight_results=_preflight()
        )
        statuses = [r.status for r in output.all_records]
        assert "success" not in statuses, statuses
        errors = [r for r in output.all_records if r.status == "error_training"]
        assert errors, statuses
        for r in errors:
            assert "contract violated" in (r.memory.conclusion if r.memory else "")
            assert r.training_history is None and r.training_diagnosis is None
        assert sandbox.training_kwargs and all(
            kw.get("eval_sample_set") for kw in sandbox.training_kwargs
        )
