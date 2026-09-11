"""F-12e-G2 — a diverged training run's own record must survive the storage boundary.

The defect this module owns is a WRITER/READER CONTRADICTION across
persistence, not a schema opinion:

* WRITER — ``execute_tools/scoring_utils.py::coerce_nonfinite_to_none`` is
  applied to every record in ``core/sandbox_executor.py``
  (``LocalRecorder.save_record``) and replaces every non-finite float with
  JSON ``null``. That is correct and stays: RFC-8259 has no NaN/Infinity.
* READER — ``ExperimentRecord.loss_history`` and
  ``TrainingHistory.train_objective`` / ``validation_objective`` declared
  ``list[float]``, an ELEMENT type that forbids exactly what the writer
  produces.

The trainer emits ``float("nan")`` by construction on a diverged epoch
(``execute_tools/train_engine_sandbox.py`` — ``np.mean`` over an empty batch
list, and a diverged criterion), so ONE bad epoch was enough to make
``HyperparamTuningOutput.model_validate`` raise in
``nodes/ml_hyperparameter_tune_agent/records.py``, drop the run to the
degraded ``status="failed"`` partial output with no ``best_denoising_score``,
and thereby sever the iteration-to-iteration restore chain
(``run_one_iteration.py`` writes ``status="no_records"``; ``core/resume.py``
skips absorption and never appends to ``committed_iters``).

**Why an in-memory test could not catch this.**
``tests/unit/execute_tools/test_step07a_c1_training_history.py`` already
asserts at two places that the schema accepts ``float("nan")`` /
``float("inf")``. Both are true and both stay green through the defect,
because neither crosses ``coerce_nonfinite_to_none`` + ``json.dump`` +
re-validate. The value the schema was asked to accept is not the value that
comes back off disk. Every test here therefore drives the REAL
``LocalRecorder``.
"""

from __future__ import annotations

import copy
import json
import math

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.training_diagnosis import derive_training_diagnosis
from core.sandbox_executor import LocalRecorder, coerce_nonfinite_to_none
from execute_tools.training_history import TrainingHistory

NAN = float("nan")

#: A three-epoch history whose LAST epoch diverged, in both curves. R3 is the
#: SAME criterion as R2, so a diverged model produces non-finite R3 rows too.
_DIVERGED_HISTORY: dict = {
    "cadence": "per_epoch",
    "objective_kind": "focal",
    "objective_config_fingerprint": "f" * 64,
    "objective_reduction": "mean",
    "epoch_statistic": "sample_count_weighted_mean_of_batch_criterion",
    "comparability": "established",
    "comparability_reason": None,
    "epochs_planned": 3,
    "epochs_completed": 3,
    "train_objective": [3.0, 2.0, NAN],
    "validation_objective": [3.1, 2.1, NAN],
    "validation_requested_samples": 8,
    "validation_samples": 8,
    "validation_requested_samples_before_limit": None,
    "validation_seconds": [0.1, 0.1, 0.1],
    "observations": {},
}


def _diverged_record(**overrides) -> dict:
    """A SCORED success record from a run whose last training epoch diverged."""
    history = copy.deepcopy(_DIVERGED_HISTORY)
    diagnosis = derive_training_diagnosis(TrainingHistory.model_validate(history))
    record = {
        "exp_id": "e1",
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-08-25 00:00:00",
        "file_index": 6,
        "params": {},
        "final_loss": NAN,
        "loss_history": [3.0, 2.0, NAN],
        "model_params": 10,
        "training_history": history,
        "training_diagnosis": diagnosis.model_dump(),
        # The point of the whole defect: the attempt WAS scored.
        "denoising_score": -2.5,
        "is_trial": False,
    }
    record.update(overrides)
    return record


def _persist(tmp_path, record: dict) -> list[dict]:
    """Push one record through the REAL recorder and read the summary back.

    This is the hop the in-memory tests skip: ``save_record`` applies
    ``coerce_nonfinite_to_none`` and ``json.dump``; ``get_summary`` re-reads
    the file. What comes back is the storage image, not the input.
    """
    recorder = LocalRecorder(
        record_dir=str(tmp_path / "records"),
        summary_file=str(tmp_path / "summary.json"),
        run_name="g2run",
    )
    recorder.save_record(copy.deepcopy(record))
    return recorder.get_summary()


def _output_dict(all_records: list[dict]) -> dict:
    return {
        "run_name": "g2run",
        "model_type": "wavenet",
        "file_index": 6,
        "status": "completed",
        "started_at": "2026-08-25 00:00:00",
        "finished_at": "2026-08-25 00:10:00",
        "completed_rounds": 1,
        "total_attempts": 1,
        "best_exp_id": "e1",
        "best_denoising_score": -2.5,
        "all_records": all_records,
    }


# ---------------------------------------------------------------------------
# The storage image itself
# ---------------------------------------------------------------------------


def test_the_recorder_writes_none_where_the_objective_was_non_finite(tmp_path):
    """Pins the WRITER half of the contradiction, so the reader tests below
    are not arguing with a hypothetical.

    Fails if ``coerce_nonfinite_to_none`` stops reaching the objective series
    (e.g. someone makes the coercion shallow, or moves it off
    ``save_record``) — at which point the on-disk record would carry a bare
    ``NaN`` token and break every ``JSON.parse`` consumer instead.
    """
    summary = _persist(tmp_path, _diverged_record())
    assert summary[0]["loss_history"] == [3.0, 2.0, None]
    assert summary[0]["final_loss"] is None
    assert summary[0]["training_history"]["train_objective"] == [3.0, 2.0, None]
    assert summary[0]["training_history"]["validation_objective"] == [3.1, 2.1, None]
    # And the bytes on disk really are RFC-8259 — no NaN / Infinity token.
    raw = (tmp_path / "summary.json").read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    json.loads(raw)  # strict re-parse; raises on a non-standard token


# ---------------------------------------------------------------------------
# The owning round trip
# ---------------------------------------------------------------------------


def test_a_scored_iteration_is_not_discarded_because_one_epoch_diverged(tmp_path):
    """THE regression. Real recorder → real summary → real output validation.

    Fails, before the repair, with a ``ValidationError`` carrying
    ``float_type`` errors at ``all_records.0.loss_history.2`` and
    ``all_records.0.training_history.train_objective.2`` (and
    ``.validation_objective.2``). In production that exception is swallowed by
    ``records.py``'s degraded branch, the run writes a ``status="failed"``
    partial output with **no** ``best_denoising_score``, and the chain's
    restore link for this iteration is gone.

    Expectations are hardcoded, never read back off the validated object.
    """
    summary = _persist(tmp_path, _diverged_record())
    output = HyperparamTuningOutput.model_validate(_output_dict(summary))

    # 1. Absorption succeeded and produced the HEALTHY output, not the
    #    degraded partial: the degraded branch carries status="failed" and
    #    best_denoising_score=None.
    assert output.status == "completed"
    assert output.best_denoising_score == -2.5
    assert output.best_exp_id == "e1"

    # 2. The record survived with its POSITIONS intact — three epochs, the
    #    diverged one still occupying index 2. This is what "the raw values
    #    stay on the record" means once the value has crossed JSON: the
    #    position is preserved and the absence is explicit.
    record = output.all_records[0]
    assert record.exp_id == "e1"
    assert record.loss_history == [3.0, 2.0, None]
    assert record.training_history is not None
    assert record.training_history.train_objective == [3.0, 2.0, None]
    assert record.training_history.validation_objective == [3.1, 2.1, None]
    assert record.training_history.epochs_completed == 3
    assert record.denoising_score == -2.5


def test_the_chain_severs_on_loss_history_alone_without_any_step_07a_payload(tmp_path):
    """This is NOT a Step-07a-only defect.

    ``loss_history`` predates Step 07a and is written by producers that emit
    no ``training_history`` at all (the baseline runner,
    ``scripts/run_comparison.py``). Strip the whole 07a payload and the round
    trip still had to survive — before the repair it raised on
    ``all_records.0.loss_history.2`` by itself.

    Fails if someone "fixes" this by widening only the Step-07a types.
    """
    record = _diverged_record(
        training_history=None,
        training_diagnosis=derive_training_diagnosis(None).model_dump(),
    )
    summary = _persist(tmp_path, record)
    assert summary[0]["training_history"] is None
    assert summary[0]["loss_history"] == [3.0, 2.0, None]

    output = HyperparamTuningOutput.model_validate(_output_dict(summary))
    assert output.best_denoising_score == -2.5
    assert output.all_records[0].loss_history == [3.0, 2.0, None]
    assert output.all_records[0].training_history is None


def test_the_diagnosis_reaches_the_same_invalid_verdict_from_the_storage_image(tmp_path):
    """``derive_training_diagnosis`` must judge the restored curve exactly as
    it judged the live one.

    ``training_diagnosis.py`` documents the contract: *"Divergence /
    non-finite criterion is EVIDENCE — the raw values stay on the record's
    history; the diagnosis declines to summarize them."* Before the repair
    ``_all_finite`` called ``math.isfinite(None)`` and raised ``TypeError``
    instead of declining, so a restored history could not be diagnosed at
    all.

    Fails with ``TypeError: must be real number, not NoneType`` if the
    ``is not None`` test is dropped, and fails with ``state == "ok"`` — a
    diagnosis that summarizes a diverged curve as if it were healthy — if
    someone makes ``_all_finite`` skip ``None`` elements instead of judging
    them.
    """
    summary = _persist(tmp_path, _diverged_record())
    restored = TrainingHistory.model_validate(summary[0]["training_history"])

    diagnosis = derive_training_diagnosis(restored)
    assert diagnosis.state == "invalid"
    assert diagnosis.validation_state == "present"
    assert diagnosis.epochs_completed == 3
    # An invalid diagnosis carries NO curve facts — a summarized diverged
    # curve is the silent-wrong-statistic failure this guards.
    assert diagnosis.train_first is None
    assert diagnosis.train_last is None
    assert diagnosis.train_min is None
    assert diagnosis.train_trend is None
    assert diagnosis.validation_min is None
    assert diagnosis.train_validation_gap_final is None

    # And the LIVE history reaches the identical verdict — the storage image
    # must not be a second, more permissive regime.
    live = derive_training_diagnosis(TrainingHistory.model_validate(_DIVERGED_HISTORY))
    assert live.model_dump() == diagnosis.model_dump()


def test_a_healthy_run_round_trips_unchanged(tmp_path):
    """The repair must not make a finite run look different.

    Fails if the widened element type silently rewrites finite values (e.g.
    someone implements tolerance by filtering rather than by typing).
    """
    history = dict(
        _DIVERGED_HISTORY,
        train_objective=[3.0, 2.0, 1.0],
        validation_objective=[3.1, 2.1, 1.1],
    )
    record = _diverged_record(
        final_loss=1.0,
        loss_history=[3.0, 2.0, 1.0],
        training_history=history,
        training_diagnosis=derive_training_diagnosis(
            TrainingHistory.model_validate(history)
        ).model_dump(),
    )
    summary = _persist(tmp_path, record)
    output = HyperparamTuningOutput.model_validate(_output_dict(summary))
    assert output.all_records[0].loss_history == [3.0, 2.0, 1.0]
    assert output.all_records[0].training_history is not None
    assert output.all_records[0].training_history.train_objective == [3.0, 2.0, 1.0]
    assert output.all_records[0].training_diagnosis is not None
    assert output.all_records[0].training_diagnosis.state == "ok"
    assert output.all_records[0].training_diagnosis.train_last == 1.0


def test_the_run_output_survives_the_second_crossing_that_resume_re_validates(tmp_path):
    """The record crosses the coercion TWICE, and the second crossing fails
    harder than the first.

    ``records.py:1034`` coerces ``HyperparamTuningOutput.model_dump()`` again
    before writing ``run_output_<run>.json``; ``core/resume.py:343`` then
    re-reads it with ``HyperparamTuningOutput.model_validate_json`` and turns
    any failure into a ``ResumeError``, which HALTS the chain rather than
    skipping one iteration. So a repair that fixed only the finalisation path
    would have moved a skipped iteration into a dead chain.

    Fails, before the repair, with
    ``ResumeError: ... run_output failed validation at ...`` naming the same
    ``loss_history`` / ``train_objective`` element paths.
    """
    from core.resume import _validate_run_output

    summary = _persist(tmp_path, _diverged_record())
    output = HyperparamTuningOutput.model_validate(_output_dict(summary))

    # Exactly what records.py does before writing the file.
    safe_output = coerce_nonfinite_to_none(output.model_dump())
    output_path = tmp_path / "run_output_g2run.json"
    output_path.write_text(json.dumps(safe_output, indent=4), encoding="utf-8")

    reparsed = _validate_run_output(str(output_path), 1)
    assert reparsed.best_denoising_score == -2.5
    assert reparsed.all_records[0].loss_history == [3.0, 2.0, None]
    assert reparsed.all_records[0].training_history is not None
    assert reparsed.all_records[0].training_history.train_objective == [3.0, 2.0, None]
    assert reparsed.all_records[0].training_history.validation_objective == [3.1, 2.1, None]


# ---------------------------------------------------------------------------
# The guards that must NOT have been widened along with the element type
# ---------------------------------------------------------------------------


def test_the_length_agreement_guard_still_fires_on_a_genuine_mismatch():
    """``TrainingHistory._consistent`` pins ``epochs_completed ==
    len(train_objective)``. A ``None`` element still OCCUPIES its position, so
    the storage image preserves the length and this guard is untouched by the
    repair.

    Fails if someone implements tolerance by dropping ``None`` elements —
    lengths would then shift and this guard would start rejecting healthy
    diverged records, or (worse) the drop would happen after the check and a
    shortened curve would be persisted as if complete.
    """
    with pytest.raises(ValidationError, match=r"must equal len\(train_objective\)"):
        TrainingHistory.model_validate(
            dict(_DIVERGED_HISTORY, epochs_completed=2, epochs_planned=3)
        )
    # Same guard, same message, when the storage image is the input.
    coerced = coerce_nonfinite_to_none(copy.deepcopy(_DIVERGED_HISTORY))
    assert coerced["train_objective"] == [3.0, 2.0, None]
    with pytest.raises(ValidationError, match=r"must equal len\(train_objective\)"):
        TrainingHistory.model_validate(dict(coerced, epochs_completed=2, epochs_planned=3))
    # R2/R3 length agreement likewise.
    with pytest.raises(ValidationError, match=r"len\(validation_objective\)"):
        TrainingHistory.model_validate(dict(coerced, validation_objective=[3.1, 2.1]))


def test_the_record_cross_check_still_rejects_a_genuinely_different_series(tmp_path):
    """``ExperimentRecord._training_history_agrees_with_the_legacy_keys`` must
    keep refusing a record whose R2 is not ``loss_history``.

    The widened element type routes through ``_same_score``, which was already
    written to treat "non-finite values and their storage image alike". This
    proves the widening did not turn that comparison into a no-op: a real
    disagreement at the SAME index that carries the divergence still raises.
    """
    summary = _persist(tmp_path, _diverged_record())
    stored = summary[0]
    # The storage image itself agrees and validates.
    ExperimentRecord.model_validate(copy.deepcopy(stored))
    # A tampered legacy series does not.
    tampered = copy.deepcopy(stored)
    tampered["loss_history"] = [3.0, 2.0, 0.5]
    with pytest.raises(ValidationError, match="disagrees with loss_history"):
        ExperimentRecord.model_validate(tampered)
    # Neither does a series that agrees on the diverged slot but differs on a
    # finite one — the None tolerance must not blanket the whole comparison.
    tampered2 = copy.deepcopy(stored)
    tampered2["loss_history"] = [3.0, 99.0, None]
    with pytest.raises(ValidationError, match="disagrees with loss_history"):
        ExperimentRecord.model_validate(tampered2)


# ---------------------------------------------------------------------------
# The reader census — a future reader may not join silently
# ---------------------------------------------------------------------------

#: Every PRODUCTION module that reads the elements of
#: ``ExperimentRecord.loss_history`` / ``TrainingHistory.train_objective`` /
#: ``TrainingHistory.validation_objective``, mapped to how it survives a
#: ``None`` element. Enumerated by reading each site, not by symbol grep.
#:
#: * ``refuses``   — a guard diverts before any arithmetic.
#: * ``none_safe`` — the comparison/predicate is explicitly ``None``-aware.
#: * ``opaque``    — the list is passed through (json/dict copy/len) and no
#:                   element is ever indexed or arithmetic-ed.
_ELEMENT_READERS: dict[str, str] = {
    "src/agent/schemas/training_diagnosis.py::_all_finite": "refuses",
    "src/agent/schemas/hyperparam_tuning.py::_same_score": "none_safe",
    "src/execute_tools/training_history.py::_same_float": "none_safe",
}


def test_the_only_element_level_readers_are_none_aware():
    """Reachability + census in one: each catalogued reader is CALLED here and
    shown to survive a ``None`` element without inventing a number.

    The failure this catches is the one a widened element type creates rather
    than fixes — a reader that quietly folds ``None`` into ``0`` (or drops it)
    and moves the defect from *record discarded* to *statistic silently
    wrong*, where nothing fails at all.

    If a new element-level reader appears, add it here WITH its behaviour, or
    this file stops describing the system.
    """
    from agent.schemas.hyperparam_tuning import _same_score
    from agent.schemas.training_diagnosis import _all_finite
    from execute_tools.training_history import _same_float

    assert set(_ELEMENT_READERS) == {
        "src/agent/schemas/training_diagnosis.py::_all_finite",
        "src/agent/schemas/hyperparam_tuning.py::_same_score",
        "src/execute_tools/training_history.py::_same_float",
    }

    # refuses — judged as the non-finite value it stands for, never skipped.
    assert _all_finite([3.0, 2.0, None]) is False
    assert _all_finite([3.0, 2.0, NAN]) is False
    assert _all_finite([3.0, 2.0, 1.0]) is True
    assert _all_finite(None) is True

    # none_safe — the storage image compares equal to what it stands for, and
    # unequal to a real number.
    assert _same_score(None, None) is True
    assert _same_score(None, NAN) is True
    assert _same_score(None, 0.0) is False
    assert _same_score(0.0, 0.0) is True

    assert _same_float(None, None) is True
    assert _same_float(NAN, NAN) is True
    assert _same_float(None, 0.0) is False
    assert _same_float(1.0, 1.0) is True


def test_no_production_module_averages_or_sums_the_objective_series():
    """Structural: the objective series are never reduced to a statistic in
    production, so a ``None`` element cannot shift a reported number.

    ``TrainingDiagnosis`` is the ONE summariser and it refuses non-finite
    curves wholesale (``state="invalid"``, no curve facts) — proven by
    ``test_the_diagnosis_reaches_the_same_invalid_verdict_from_the_storage_image``
    above. Everything else carries the list opaquely: the record builder
    copies it into a dict, the prompt layer serialises it as JSON, the planner
    hides the whole ``training_history`` key, and ``feedback.py`` reads only
    ``epochs_completed``.

    Fails when a new reduction (``mean`` / ``sum`` / ``min`` / ``max``) is
    written over these fields — the moment that happens the ``None`` element
    needs an explicit policy, and this test is where that decision gets
    recorded.
    """
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    assert (repo_root / "src/execute_tools" / "training_history.py").is_file(), (
        f"census anchored at the wrong root: {repo_root}"
    )

    # The FILE SET is the whole production tree; a census that names only the
    # files it expects to be clean cannot fail (F-12bc-9).
    production_dirs = (
        "src/agent",
        "src/core",
        "src/execute_tools",
        "src/nodes",
        "scripts",
        "src/workflows",
    )
    reducers = {"mean", "sum", "min", "max", "median", "average", "nanmean", "fsum", "sorted"}
    fields = {"loss_history", "train_objective", "validation_objective"}
    # No exemption list, deliberately. The census is green with ZERO
    # exemptions, which is a stronger statement than a green with a carve-out
    # — and an exemption that can never fire is how a census comes to be green
    # for the wrong reason (F-12bc-9).

    offenders: list[str] = []
    for directory in production_dirs:
        for path in sorted((repo_root / directory).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - not expected in-tree
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name not in reducers:
                    continue
                arg = node.args[0]
                # Three access shapes, because a census that sees only one of
                # them is green for the wrong reason:
                #   mean(record.loss_history)        -> Attribute
                #   mean(h["train_objective"])       -> Subscript with a str key
                #   mean(loss_history)               -> Name (a local holding it)
                referenced = None
                if isinstance(arg, ast.Attribute):
                    referenced = arg.attr
                elif (
                    isinstance(arg, ast.Subscript)
                    and isinstance(arg.slice, ast.Constant)
                    and isinstance(arg.slice.value, str)
                ):
                    referenced = arg.slice.value
                elif isinstance(arg, ast.Name):
                    referenced = arg.id
                if referenced not in fields:
                    continue
                rel = path.relative_to(repo_root).as_posix()
                offenders.append(f"{rel}:{node.lineno} {name}(...{referenced})")

    assert offenders == [], (
        "a production module now reduces an objective series to a statistic; a "
        "None element (the storage image of a diverged epoch) needs an explicit "
        f"policy there: {offenders}"
    )


def test_sanity_the_storage_image_is_what_python_cannot_express_as_json():
    """Guards the premise, so a future reader does not have to take it on
    faith that ``None`` is the only available image of ``NaN`` in JSON."""
    assert math.isfinite(NAN) is False
    assert coerce_nonfinite_to_none([1.0, NAN, float("inf"), float("-inf")]) == [
        1.0,
        None,
        None,
        None,
    ]
