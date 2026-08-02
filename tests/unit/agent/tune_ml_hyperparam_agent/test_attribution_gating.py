"""B-C3b — a wrong signal must not reach the planner.

V19's collapse was not a bad measurement, it was a correct measurement
read as a statement about the wrong thing: a CUDA OOM raised while a
neighbouring chain held the card became "reduce model size", and the
campaign shrank to toy models.

So the assertions here are about the *rendered prompt string*, not about
a record field. A record can carry the right verdict and the prompt can
still tell the agent to shrink — which is precisely the failure.

Fixture note: every "absent" assertion targets the exact production
literal rather than a loose phrase like "reduce batch". Four existing
tuner fixtures inject `"suggestion": "Reduce batch_size."` through the
*pre-flight* path, so a loose substring would match text this feature
never touches and pass for the wrong reason.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from agent.prompts import get_planner_user_prompt
from agent.schemas.hyperparam_tuning import ExperimentRecord
from core.runtime_control.failure_attribution import (
    AttributionResult,
    may_recommend_resource_reduction,
)
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    RESOURCE_ADMISSION_STATUS,
    _attach_runtime_evidence,
    _attribution_reason,
    _handle_admission_refusal,
    _may_advise_resource_reduction,
    _oom_memory_wording,
)

#: ASCII-only fragments of the exact production shrink strings.
#:
#: The full literals contain an em-dash, and `get_planner_user_prompt`
#: renders history through `json.dumps(..., indent=2)` with the default
#: `ensure_ascii=True`, which escapes it to `\u2014`. Asserting the full
#: literal is *absent* from the prompt would therefore always pass — a
#: vacuous guard over exactly the behaviour that matters. These fragments
#: survive JSON escaping, and `test_the_fragments_still_match_production`
#: pins them to the real source so they cannot drift into vacuity again.
TRAIN_SHRINK = "reduce model size, batch_size, or segmentation_size."
TRAIN_SHRINK_MEMORY = "This config exceeds GPU memory. Try smaller architecture."
INFER_SHRINK = "reduce batch_size or model size."

TUNER_SOURCE = (
    Path(__file__).resolve().parents[4]
    / "nodes"
    / "ml_hyperparameter_tune_agent"
    / "ml_hyperparameter_tune_agent.py"
)

ALL_OUTCOMES = [
    "candidate_gpu_capacity",
    "gpu_contention",
    "host_memory_pressure",
    "external_termination",
    "unknown",
]


def _verdict(attribution: str) -> dict:
    return AttributionResult(
        attribution=attribution,
        may_recommend_resource_reduction=may_recommend_resource_reduction(attribution),
        reason=f"fixture reason for {attribution}",
        evidence={"attempted_allocation_mib": 11_581.0},
    ).model_dump(mode="json")


def _oom_record(attribution: str | None, status: str = "error_training_oom") -> dict:
    record = {
        "exp_id": "e1",
        "status": status,
        "model_type": "wavenet",
        "timestamp": "2026-08-01 00:00:00",
        "file_index": 0,
        "params": {},
        "denoising_score": None,
        "memory": {
            "expert_advice_followed": "none",
            "hypothesis": "fixture",
            "conclusion": "Training failed",
            "discovery": "",
            "memory_update": "",
        },
    }
    if attribution is not None:
        record["failure_attribution"] = _verdict(attribution)
    return record


class TestAuthorityHelper:
    @pytest.mark.parametrize("attribution", ALL_OUTCOMES)
    def test_only_candidate_capacity_authorises_shrink_advice(self, attribution):
        expected = attribution == "candidate_gpu_capacity"
        assert _may_advise_resource_reduction({"failure_attribution": _verdict(attribution)}) is (
            expected
        )

    @pytest.mark.parametrize(
        "status",
        [{}, {"failure_attribution": None}, {"failure_attribution": {}}],
    )
    def test_a_missing_attribution_is_unknown_and_carries_no_authority(self, status):
        """Legacy records, and failures the runtime declined to classify."""
        assert _may_advise_resource_reduction(status) is False

    def test_an_unrecognised_outcome_is_denied_authority(self):
        status = {"failure_attribution": {"attribution": "something_new"}}
        assert _may_advise_resource_reduction(status) is False

    def test_the_reason_reaches_the_task_layer(self):
        reason = _attribution_reason({"failure_attribution": _verdict("gpu_contention")})
        assert "gpu_contention" in reason
        assert "fixture reason for gpu_contention" in reason

    def test_a_missing_reason_says_so_rather_than_inventing_one(self):
        assert "no attribution was recorded" in _attribution_reason({})


class TestOomWording:
    """The wording the tuner actually writes onto a failure record.

    The prompt tests below build records by hand, so on their own they
    cannot see the tuner's gate at all — reverting it left them green.
    This class exercises the decision itself.
    """

    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_a_candidate_capacity_verdict_asks_for_a_smaller_config(self, phase):
        discovery, memory = _oom_memory_wording(
            {"failure_attribution": _verdict("candidate_gpu_capacity")}, phase=phase
        )
        expected = INFER_SHRINK if phase == "inference" else TRAIN_SHRINK
        assert expected in discovery
        assert "Do NOT reduce" not in memory

    @pytest.mark.parametrize(
        "attribution",
        ["gpu_contention", "host_memory_pressure", "external_termination", "unknown"],
    )
    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_no_other_verdict_may_ask_for_a_smaller_config(self, attribution, phase):
        discovery, memory = _oom_memory_wording(
            {"failure_attribution": _verdict(attribution)}, phase=phase
        )
        assert TRAIN_SHRINK not in discovery
        assert INFER_SHRINK not in discovery
        assert TRAIN_SHRINK_MEMORY not in memory
        assert "Do NOT reduce model capacity" in memory
        assert attribution in discovery

    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_a_legacy_status_without_attribution_gets_no_shrink_advice(self, phase):
        discovery, memory = _oom_memory_wording({}, phase=phase)
        assert TRAIN_SHRINK not in discovery
        assert INFER_SHRINK not in discovery
        assert "Do NOT reduce model capacity" in memory

    def test_it_says_so_rather_than_staying_silent(self):
        """Silence lets the agent infer the instruction anyway."""
        discovery, _ = _oom_memory_wording(
            {"failure_attribution": _verdict("gpu_contention")}, phase="training"
        )
        assert "not evidence that the model was too large" in discovery


class TestProductionReachability:
    """A gate the production path can bypass is not a gate.

    `TestOomWording` proves the decision is right; nothing there proves
    the tuner asks it. Replacing a call site with the shrink literal
    inline left the whole suite green, which is the recurring failure
    mode this codebase keeps hitting: a component built, tested, and
    never actually called.
    """

    @staticmethod
    def _functions_containing(fragment: str) -> set[str]:
        """Which functions hold this string. Adjacent literals are joined
        by the parser, so source wrapping does not hide one."""
        tree = ast.parse(TUNER_SOURCE.read_text())
        found = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and fragment in node.value
                ):
                    found.add(fn.name)
        return found

    @pytest.mark.parametrize("fragment", [TRAIN_SHRINK, TRAIN_SHRINK_MEMORY, INFER_SHRINK])
    def test_the_shrink_wording_lives_only_behind_the_gate(self, fragment):
        assert self._functions_containing(fragment) == {"_oom_memory_wording"}

    def test_the_gate_is_asked_from_exactly_one_place(self):
        """After B-C4a0 both failure paths share one record builder.

        The guarantee is now a chain: the builder is the only caller of
        the gate, and both production sites reach the builder. Asserting
        only the second half would let a new site emit shrink wording
        without ever consulting the attribution.
        """
        tree = ast.parse(TUNER_SOURCE.read_text())
        callers = {
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_oom_memory_wording"
                for n in ast.walk(fn)
            )
        }
        assert callers == {"_build_execution_failure_record"}

    def test_both_failure_sites_reach_the_builder(self):
        tree = ast.parse(TUNER_SOURCE.read_text())
        phases = [
            kw.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_build_execution_failure_record"
            for kw in node.keywords
            if kw.arg == "phase" and isinstance(kw.value, ast.Constant)
        ]
        assert sorted(phases) == ["inference", "training"]

    def test_every_persisted_record_goes_through_the_validating_emitter(self):
        """`save_record` must never be reached without validation.

        One unvalidated write makes the whole iteration unresumable, so
        the pairing is structural rather than a convention repeated at
        nine call sites.
        """
        tree = ast.parse(TUNER_SOURCE.read_text())
        direct = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "save_record"
            and not (isinstance(node.func.value, ast.Name) and node.func.value.id == "sandbox")
        ]
        emitter = [
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "save_record"
                for n in ast.walk(fn)
            )
        ]
        assert direct == []
        # Every remaining save_record lives in a function that also
        # validates, or in the emitter itself.
        for name in emitter:
            fn = next(
                n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name
            )
            validates = any(
                isinstance(n, ast.Attribute) and n.attr == "model_validate" for n in ast.walk(fn)
            )
            assert validates or name == "_emit_record", name


class TestRuntimeEvidenceAttachment:
    def test_both_keys_are_carried_when_present(self):
        record: dict = {}
        _attach_runtime_evidence(
            record,
            {"gpu_evidence": {"valid_sample_count": 3}, "failure_attribution": _verdict("unknown")},
        )
        assert record["gpu_evidence"] == {"valid_sample_count": 3}
        assert record["failure_attribution"]["attribution"] == "unknown"

    @pytest.mark.parametrize("status", [{}, {"gpu_evidence": None, "failure_attribution": None}])
    def test_absent_keys_are_not_written_as_null(self, status):
        """An absent key must stay absent: a null verdict on the record
        would be indistinguishable from a captured one that said nothing."""
        record: dict = {}
        _attach_runtime_evidence(record, status)
        assert record == {}

    def test_one_present_one_absent(self):
        record: dict = {}
        _attach_runtime_evidence(record, {"failure_attribution": _verdict("gpu_contention")})
        assert "gpu_evidence" not in record
        assert record["failure_attribution"]["attribution"] == "gpu_contention"


class TestRecordCompatibility:
    def test_a_legacy_record_without_attribution_still_validates(self):
        ExperimentRecord.model_validate(_oom_record(None))

    @pytest.mark.parametrize("attribution", ALL_OUTCOMES)
    def test_a_record_carrying_an_attribution_validates(self, attribution):
        rec = ExperimentRecord.model_validate(_oom_record(attribution))
        assert rec.failure_attribution is not None
        assert rec.failure_attribution["attribution"] == attribution

    def test_the_field_defaults_to_none_not_to_a_verdict(self):
        rec = ExperimentRecord.model_validate(_oom_record(None))
        assert rec.failure_attribution is None


class TestPlannerPromptGating:
    """Asserted on the rendered string — the record is not the product."""

    def test_the_fragments_still_match_production(self):
        """Without this, an edit to the tuner silently voids every
        "shrink text absent" assertion below: they would keep passing
        against a string production no longer emits."""
        # Rejoin implicitly concatenated literals: the formatter wraps a
        # long string across lines, and a fragment that spans the wrap is
        # absent from the raw text while being very much present in the
        # value the tuner emits.
        source = re.sub(r'"\s*\n\s*"', "", TUNER_SOURCE.read_text())
        for fragment in (TRAIN_SHRINK, TRAIN_SHRINK_MEMORY, INFER_SHRINK):
            assert fragment in source, fragment

    @pytest.mark.parametrize(
        "attribution", ["gpu_contention", "host_memory_pressure", "external_termination", "unknown"]
    )
    def test_an_unattributed_oom_gets_the_suppression_note(self, attribution):
        prompt = get_planner_user_prompt(memory_history=[_oom_record(attribution)])
        assert "OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG" in prompt
        assert "Do NOT reduce model" in prompt
        assert attribution in prompt

    def test_a_candidate_attributed_oom_gets_no_suppression_note(self):
        prompt = get_planner_user_prompt(memory_history=[_oom_record("candidate_gpu_capacity")])
        assert "OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG" not in prompt

    def test_a_legacy_oom_record_is_treated_as_unattributed(self):
        """Absence must not read as candidate blame."""
        prompt = get_planner_user_prompt(memory_history=[_oom_record(None)])
        assert "OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG" in prompt

    def test_an_inference_oom_is_covered_too(self):
        prompt = get_planner_user_prompt(
            memory_history=[_oom_record("gpu_contention", status="error_inference_oom")]
        )
        assert "OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG" in prompt

    def test_a_non_oom_failure_does_not_trigger_the_note(self):
        prompt = get_planner_user_prompt(
            memory_history=[_oom_record(None, status="error_training")]
        )
        assert "OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG" not in prompt

    def test_no_records_no_note(self):
        assert "OUT-OF-MEMORY NOT ATTRIBUTED" not in get_planner_user_prompt(memory_history=[])

    @pytest.mark.parametrize("attribution", ["gpu_contention", "unknown"])
    def test_the_shrink_literals_are_absent_for_an_unattributed_oom(self, attribution):
        """The whole point, stated on the exact production strings.

        A contention-attributed record carries the suppressing wording
        the tuner wrote, so neither shrink literal can appear.
        """
        record = _oom_record(attribution)
        record["memory"]["discovery"] = (
            "CUDA OOM, but the measurement does NOT attribute it to this config "
            "(gpu_contention: a peer held the card). This is not evidence that "
            "the model was too large."
        )
        record["memory"]["memory_update"] = (
            "OOM not attributed to this config. Do NOT reduce model capacity, "
            "batch size or segmentation size in response to it."
        )
        prompt = get_planner_user_prompt(memory_history=[record])
        assert TRAIN_SHRINK not in prompt
        assert TRAIN_SHRINK_MEMORY not in prompt
        assert INFER_SHRINK not in prompt

    def test_a_candidate_attributed_oom_may_still_carry_the_shrink_literal(self):
        """The gate suppresses a wrong signal, not every signal.

        A measured capacity failure must still reach the planner, or the
        fix would trade one silent failure for another.
        """
        record = _oom_record("candidate_gpu_capacity")
        record["memory"]["discovery"] = TRAIN_SHRINK
        record["memory"]["memory_update"] = TRAIN_SHRINK_MEMORY
        prompt = get_planner_user_prompt(memory_history=[record])
        assert TRAIN_SHRINK in prompt
        assert "OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG" not in prompt

    def test_one_candidate_record_does_not_suppress_the_note_for_another(self):
        """Mixed history: the note is per-record, not per-run."""
        prompt = get_planner_user_prompt(
            memory_history=[
                _oom_record("candidate_gpu_capacity"),
                _oom_record("gpu_contention"),
            ]
        )
        assert "OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG (1 attempt(s))" in prompt


def _refusal() -> dict:
    return {
        "status": RESOURCE_ADMISSION_STATUS,
        "message": "9.00 GiB predicted against a 8.00 GiB effective ceiling",
        "admission": {
            "admitted": False,
            "reason_code": "insufficient_headroom",
            "detail": None,
            "requirement_source": "measured",
            "reason": "short by 1.00 GiB",
            "evidence": {"other_mib": 20000},
        },
    }


class TestAdmissionRefusalConsumption:
    """B-C4c — a refusal reaches the record, and says the right thing.

    Five properties are separable and all must hold: it consumes the
    attempt slot, it is not a candidate failure, it carries no shrink
    advice, it does not update the incumbent, and it triggers no retry.
    Collapsing any one is how an environment problem becomes a
    scientific conclusion about a model.
    """

    class _Sandbox:
        def __init__(self):
            self.saved = []

        def save_record(self, record):
            self.saved.append(record)

    def _handle(self, status):
        sandbox = self._Sandbox()
        handled = _handle_admission_refusal(
            status,
            phase="training",
            sandbox=sandbox,
            exp_id="e1",
            model_type="wavenet",
            file_index=0,
            record_params={},
            expert_advice_str="none",
            hypothesis="fixture",
            round_index=2,
            attempt_in_round=1,
        )
        return handled, sandbox.saved

    def test_a_non_refusal_status_is_not_handled(self):
        for status in ({"status": "error"}, {"status": "success"}, {}):
            handled, saved = self._handle(status)
            assert handled is False
            assert saved == []

    def test_a_refusal_is_recorded_and_short_circuits_the_attempt(self):
        handled, saved = self._handle(_refusal())
        assert handled is True
        assert len(saved) == 1
        assert saved[0]["status"] == RESOURCE_ADMISSION_STATUS

    def test_it_consumes_the_attempt_slot_but_not_a_round(self):
        _, saved = self._handle(_refusal())
        assert saved[0]["counts_toward_attempt_budget"] is True
        assert saved[0]["counts_toward_completed_rounds"] is False

    def test_it_is_not_a_candidate_failure(self):
        """No score, no failure_type, and a status outside the error
        family — a reader counting failures must not count this."""
        _, saved = self._handle(_refusal())
        rec = saved[0]
        assert rec["denoising_score"] is None
        assert not rec["status"].startswith("error")
        assert rec.get("failure_type") is None

    def test_it_carries_no_shrink_advice(self):
        _, saved = self._handle(_refusal())
        memory = saved[0]["memory"]
        blob = f"{memory['discovery']} {memory['memory_update']}"
        assert TRAIN_SHRINK not in blob
        assert INFER_SHRINK not in blob
        assert "Do NOT reduce model" in memory["memory_update"]

    def test_the_admission_evidence_is_preserved_for_audit(self):
        _, saved = self._handle(_refusal())
        memory = saved[0]["memory"]
        assert memory["reason_code"] == "insufficient_headroom"
        assert memory["resource_type"] == "gpu_memory"
        assert memory["admission_evidence"]["evidence"]["other_mib"] == 20000

    def test_a_missing_reason_code_does_not_become_a_capacity_claim(self):
        _, saved = self._handle({"status": RESOURCE_ADMISSION_STATUS})
        assert saved[0]["memory"]["reason_code"] == "policy_unavailable"

    def test_the_record_validates_and_reads_as_unattributed(self):
        _, saved = self._handle(_refusal())
        rec = ExperimentRecord.model_validate(saved[0])
        assert rec.status == RESOURCE_ADMISSION_STATUS
        assert rec.failure_attribution is None
        assert _may_advise_resource_reduction(saved[0]) is False

    def test_it_never_re_invokes_the_phase(self):
        """Behavioural, not structural: the handler must not run the
        skill again. Asserting only that the source has no `while` or
        `sleep` would miss a retry expressed as a second call."""
        from unittest.mock import patch

        with patch(
            "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent._run_skill"
        ) as run_skill:
            handled, saved = self._handle(_refusal())
        assert handled is True
        assert run_skill.call_count == 0
        assert len(saved) == 1

    def test_one_refusal_writes_exactly_one_record(self):
        """A retry would show up as a second record for the same slot."""
        _, saved = self._handle(_refusal())
        assert len(saved) == 1
        assert saved[0]["memory"]["attempt_in_round"] == 1

    def test_each_refusal_consumes_a_distinct_attempt_slot(self):
        """The slot advances; the same attempt is never re-run. This is
        what "consumes the budget" means operationally — without it a
        busy device could refuse forever inside one round."""
        sandbox = self._Sandbox()
        for attempt in (1, 2, 3):
            _handle_admission_refusal(
                _refusal(),
                phase="training",
                sandbox=sandbox,
                exp_id=f"e{attempt}",
                model_type="wavenet",
                file_index=0,
                record_params={},
                expert_advice_str="none",
                hypothesis="fixture",
                round_index=2,
                attempt_in_round=attempt,
            )
        slots = [r["memory"]["attempt_in_round"] for r in sandbox.saved]
        assert slots == [1, 2, 3]
        assert all(r["counts_toward_attempt_budget"] is True for r in sandbox.saved)

    def test_it_contains_no_loop_or_sleep(self):
        """Structural backstop to the behavioural tests above."""
        import ast as _ast
        import inspect

        tree = _ast.parse(inspect.getsource(_handle_admission_refusal).lstrip())
        called = {
            n.func.attr if isinstance(n.func, _ast.Attribute) else getattr(n.func, "id", "")
            for n in _ast.walk(tree)
            if isinstance(n, _ast.Call)
        }
        assert "sleep" not in called
        assert not any(isinstance(n, _ast.While | _ast.For) for n in _ast.walk(tree))

    def test_a_round_of_refusals_produces_no_authoritative_result(self):
        sandbox = self._Sandbox()
        for attempt in (1, 2, 3):
            _handle_admission_refusal(
                _refusal(),
                phase="training",
                sandbox=sandbox,
                exp_id=f"e{attempt}",
                model_type="wavenet",
                file_index=0,
                record_params={},
                expert_advice_str="none",
                hypothesis="fixture",
                round_index=2,
                attempt_in_round=attempt,
            )
        assert len(sandbox.saved) == 3
        # No authoritative result: nothing scored, nothing succeeded.
        assert all(r["denoising_score"] is None for r in sandbox.saved)
        assert not any(r["status"] == "success" for r in sandbox.saved)
        # No completed round, so the incumbent has nothing to update from.
        assert all(r["counts_toward_completed_rounds"] is False for r in sandbox.saved)
        # No negative candidate evidence: not in the error family, no
        # failure_type, and no shrink advice anywhere in the memory.
        assert all(r["status"] == RESOURCE_ADMISSION_STATUS for r in sandbox.saved)
        assert all(r.get("failure_type") is None for r in sandbox.saved)
        for r in sandbox.saved:
            blob = f"{r['memory']['discovery']} {r['memory']['memory_update']}"
            assert TRAIN_SHRINK not in blob
            assert INFER_SHRINK not in blob
        # And every one of them is a valid record, so the round is
        # resumable rather than a hole in the run output.
        for r in sandbox.saved:
            ExperimentRecord.model_validate(r)


class TestAdmissionRefusalPrompt:
    def test_the_planner_sees_no_shrink_instruction(self):
        record = {
            "exp_id": "e1",
            "status": RESOURCE_ADMISSION_STATUS,
            "model_type": "wavenet",
            "timestamp": "2026-08-02 00:00:00",
            "file_index": 0,
            "params": {},
            "denoising_score": None,
            "memory": {
                "expert_advice_followed": "none",
                "hypothesis": "fixture",
                "conclusion": "Skipped before starting",
                "discovery": "This is a statement about the machine",
                "memory_update": "Do NOT reduce model capacity, batch size or "
                "segmentation size in response to it.",
                "reason_code": "insufficient_headroom",
            },
        }
        prompt = get_planner_user_prompt(memory_history=[record])
        assert TRAIN_SHRINK not in prompt
        assert TRAIN_SHRINK_MEMORY not in prompt
        assert INFER_SHRINK not in prompt

    def test_it_does_not_trigger_the_unattributed_oom_note(self):
        """That note is for a MEASURED out-of-memory. A refusal means no
        phase ran, so there is no OOM to explain away."""
        record = {
            "exp_id": "e1",
            "status": RESOURCE_ADMISSION_STATUS,
            "model_type": "wavenet",
            "timestamp": "2026-08-02 00:00:00",
            "file_index": 0,
            "params": {},
            "denoising_score": None,
            "memory": {"expert_advice_followed": "n", "hypothesis": "h"},
        }
        prompt = get_planner_user_prompt(memory_history=[record])
        assert "OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG" not in prompt
