"""An iteration that ran no formal round must not report a trial score.

F-SCANB-3 (release blocker). ``run_one_iteration.write_manifest`` derived
BOTH the iteration status and the reported ``best_score`` from
``tune_output.best_denoising_score``, which is ``top_record`` over ALL
records — trial and formal mixed
(``nodes/ml_hyperparameter_tune_agent/records.py``). The honest fields
``best_formal_denoising_score`` and ``best_valid_formal_denoising_score``
were written into the manifest beside it and decided nothing.

The historical event the row records: all ten v20 attempt-3 manifests read
``best_valid_formal_score: null``, ``raw_best_formal_score: null``,
``result_authority: "scientific"`` and ``best_score`` between 0.479 and
10.708 — every one a TRIAL score, from seven success records that were all
``is_trial: true`` with zero formal. An operator, and any published
trajectory built from these manifests, read those as the campaign's
results while ``status: "completed"`` concealed that no formal round had
run.

WHAT THESE TESTS DRIVE, and why it matters here specifically. Every case
builds a real ``HyperparamTuningOutput`` whose ``all_records`` are
``ExperimentRecord`` models, so the role rule is applied to
``model_dump()`` — the serialization production writes, which MATERIALIZES
``is_trial: False`` onto every formal record. A helper that hand-built
record dicts would test a shape production never emits, which is exactly
how the sibling ``"is_trial" in rec`` defect (#316 B2) survived: under it
every real formal record was silently discarded.

WHAT THEY DELIBERATELY DO NOT PIN. The manifest ``status`` vocabulary is
FROZEN at ``completed|failed|no_records``
(the persisted iteration contract) and is the
chain-control token ``core/resume.py``, Stage 3 and the inspector branch
on. A trial-only iteration DID produce a consumable ``run_output`` and a
restorable plugin, so its status stays ``completed`` and the chain is
unchanged; the honesty lives in the evidence posture stamped beside it.
The row itself records that selection was already honest
(``core/resume.py`` takes the incumbent from
``chain_best_valid_formal_score``) and must not be widened.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_spec = importlib.util.spec_from_file_location(
    "run_one_iteration_for_fscanb3",
    _REPO / "src" / "workflows" / "run_one_iteration.py",
)
assert _spec is not None and _spec.loader is not None
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)

from agent.schemas.hyperparam_tuning import (  # noqa: E402
    ExperimentMemory,
    ExperimentRecord,
    HyperparamTuningOutput,
)
from core import record_role  # noqa: E402
from core.record_role import RecordRoleError, is_formal_role  # noqa: E402

RUN_NAME = "fscanb3_witness"

#: The v20 attempt-3 shape: the mixed pool's top score is a TRIAL score.
TRIAL_TOP_SCORE = 10.708
FORMAL_SCORE = -3.221148


def _record(exp_id: str, *, is_trial: bool, score: float, status: str = "success"):
    """One record, built through the model so ``model_dump()`` is real."""
    return ExperimentRecord(
        exp_id=exp_id,
        status=status,
        model_type="wavenet",
        timestamp="2026-08-27T00:00:00Z",
        params={},
        denoising_score=score,
        is_trial=is_trial,
        trial_portion=0.1 if is_trial else None,
        memory=ExperimentMemory(
            expert_advice_followed="n/a",
            hypothesis="n/a",
            round_index=1,
        ),
    )


def _output(*records, best: float | None, best_formal: float | None) -> HyperparamTuningOutput:
    """The tuning output an iteration hands ``write_manifest``.

    ``best`` and ``best_formal`` mirror what
    ``records.finalize_run_output`` computes: the mixed top record's score
    and the formal top record's score.
    """
    return HyperparamTuningOutput(
        run_name=RUN_NAME,
        model_type="wavenet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        started_at="2026-08-27T00:00:00Z",
        finished_at="2026-08-27T01:00:00Z",
        best_denoising_score=best,
        best_formal_denoising_score=best_formal,
        all_records=list(records),
    )


def _trial_only_output() -> HyperparamTuningOutput:
    return _output(
        _record("t1", is_trial=True, score=0.479),
        _record("t2", is_trial=True, score=TRIAL_TOP_SCORE),
        _record("t3", is_trial=True, score=1.2),
        best=TRIAL_TOP_SCORE,
        best_formal=None,
    )


def _mixed_output() -> HyperparamTuningOutput:
    return _output(
        _record("t1", is_trial=True, score=TRIAL_TOP_SCORE),
        _record("f1", is_trial=False, score=FORMAL_SCORE),
        best=TRIAL_TOP_SCORE,
        best_formal=FORMAL_SCORE,
    )


class TestTheManifestNoLongerReportsATrialScore:
    """The reported headline number is the FORMAL one, or nothing."""

    def test_a_trial_only_iteration_reports_no_best_score(self, tmp_path: Path) -> None:
        """FAILS by reporting ``best_score: 10.708`` when the fix is removed.

        This is the defect verbatim: seven trial successes, zero formal, and
        the mixed pool's top score presented as the iteration's result.
        """
        manifest = roi.write_manifest(str(tmp_path), RUN_NAME, [_trial_only_output()])

        assert manifest["best_score"] is None, (
            "an iteration with zero formal records has no authoritative score; "
            f"got {manifest['best_score']!r}"
        )
        assert manifest["raw_best_score"] == TRIAL_TOP_SCORE, (
            "the mixed top score is still recorded — under the key that says so"
        )

    def test_a_formal_iteration_reports_the_formal_score(self, tmp_path: Path) -> None:
        """The formal score wins even when a trial score tops the mixed pool."""
        manifest = roi.write_manifest(str(tmp_path), RUN_NAME, [_mixed_output()])

        assert manifest["best_score"] == FORMAL_SCORE
        assert manifest["raw_best_score"] == TRIAL_TOP_SCORE

    def test_the_headline_is_read_from_the_persisted_manifest(self, tmp_path: Path) -> None:
        """Through the real write-once publish, not just the returned dict."""
        roi.write_manifest(str(tmp_path), RUN_NAME, [_trial_only_output()])
        on_disk = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

        assert on_disk["best_score"] is None
        assert on_disk["formal_evidence"]["has_formal_evidence"] is False


class TestTheEvidencePostureIsStampedOnEveryBranch:
    """``status: completed`` can no longer conceal zero formal rounds."""

    def test_a_trial_only_iteration_states_zero_formal_success(self, tmp_path: Path) -> None:
        """FAILS with a KeyError when the stamp is removed."""
        manifest = roi.write_manifest(str(tmp_path), RUN_NAME, [_trial_only_output()])

        evidence = manifest["formal_evidence"]
        assert evidence["record_count"] == 3
        assert evidence["formal_record_count"] == 0
        assert evidence["formal_success_count"] == 0
        assert evidence["has_formal_evidence"] is False
        # The status is deliberately unchanged: it is the chain-control
        # token, and the vocabulary is frozen at three values.
        assert manifest["status"] == "completed"

    def test_a_formal_iteration_states_its_formal_success(self, tmp_path: Path) -> None:
        manifest = roi.write_manifest(str(tmp_path), RUN_NAME, [_mixed_output()])

        evidence = manifest["formal_evidence"]
        assert evidence["record_count"] == 2
        assert evidence["formal_record_count"] == 1
        assert evidence["formal_success_count"] == 1
        assert evidence["has_formal_evidence"] is True

    def test_a_crashed_iteration_carries_an_all_zero_posture(self, tmp_path: Path) -> None:
        """A crash produced no formal evidence either, and says so."""
        manifest = roi.write_manifest(str(tmp_path), RUN_NAME, [], crashed=True)

        assert manifest["status"] == "failed"
        assert manifest["formal_evidence"] == {
            "record_count": 0,
            "formal_record_count": 0,
            "formal_success_count": 0,
            "has_formal_evidence": False,
        }

    def test_a_record_less_iteration_carries_an_all_zero_posture(self, tmp_path: Path) -> None:
        manifest = roi.write_manifest(str(tmp_path), RUN_NAME, [])

        assert manifest["status"] == "no_records"
        assert manifest["formal_evidence"]["has_formal_evidence"] is False

    def test_a_formal_round_that_failed_is_not_formal_evidence(self, tmp_path: Path) -> None:
        """Present-but-failed is a third state, and must not read as success.

        The count uses the frozen winner rule's own two conditions — formal
        role AND ``status == "success"`` — so "no formal round ran" and "the
        formal round errored" stay distinguishable.
        """
        output = _output(
            _record("f1", is_trial=False, score=0.0, status="error_training"),
            best=None,
            best_formal=None,
        )
        manifest = roi.write_manifest(str(tmp_path), RUN_NAME, [output])

        evidence = manifest["formal_evidence"]
        assert evidence["formal_record_count"] == 1
        assert evidence["formal_success_count"] == 0
        assert evidence["has_formal_evidence"] is False


class TestTheRoleRuleReadsTheMaterializedDump:
    """The shape production writes, not the builder's in-memory dict."""

    def test_a_formal_record_carries_is_trial_false_after_model_dump(self) -> None:
        """The regression that made every real formal record invisible.

        ``ExperimentRecord.model_dump()`` MATERIALIZES ``is_trial: False``,
        so a predicate testing ``"is_trial" in rec`` classifies every
        persisted formal record as a trial. This asserts the materialization
        itself, hardcoded — never read back from the model's own default.
        """
        dumped = _record("f1", is_trial=False, score=FORMAL_SCORE).model_dump()

        assert dumped["is_trial"] is False, "the persisted shape carries the key"
        assert is_formal_role(dumped, "f1") is True

    def test_the_absence_case_is_still_formal(self) -> None:
        """A pre-materialization dict (no key at all) is FORMAL, not trial."""
        assert is_formal_role({"exp_id": "legacy"}, "legacy") is True

    def test_an_anomalous_role_shape_refuses_loudly(self) -> None:
        """A silent classification here could silently move a winner."""
        with pytest.raises(RecordRoleError, match="non-bool role"):
            is_formal_role({"is_trial": "yes"}, "bad")
        with pytest.raises(RecordRoleError, match="trial_portion"):
            is_formal_role({"is_trial": False, "trial_portion": 0.1}, "bad")


class TestTheProductionPathGoesThroughTheOneAuthority:
    """Reachability: no private copy of the role rule may be introduced."""

    def test_write_manifest_resolves_the_role_through_record_role(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Severing the shared authority must break the manifest writer.

        A second predicate written inline in ``run_one_iteration`` would
        leave this green only if it stopped calling the authority — which is
        the thing being forbidden.
        """

        def _severed(record, where):  # type: ignore[no-untyped-def]
            raise AssertionError("severed authority")

        monkeypatch.setattr(record_role, "is_formal_role", _severed)
        with pytest.raises(AssertionError, match="severed authority"):
            roi.write_manifest(str(tmp_path), RUN_NAME, [_trial_only_output()])
