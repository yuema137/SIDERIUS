"""Three resource failures, three different meanings. Keep them apart.

They all look like "not enough GPU memory" and they are not the same
event. Collapsing any two is the defect PR B spent commits #152/#153
undoing, and it is the merge a future test-consolidation pass is most
likely to propose, because the three families read as near-duplicates.

    LANE 1  preflight ESTIMATE refusal   status skipped_oom_risk
            The phase never started. A predicted footprint exceeded a
            budget. The prediction IS about the candidate, so shrink
            advice is legitimate here.

    LANE 2  runtime ADMISSION refusal    status skipped_resource_admission
            The phase never started. The DEVICE could not hold it right
            now -- a statement about the machine at this moment. Shrink
            advice is NEVER legitimate: the candidate may be exactly the
            right size and the neighbour's occupancy is not its fault.

    LANE 3  post-OOM ATTRIBUTION         status error_{phase}_oom
            The phase RAN and died. Whether the candidate is to blame
            depends on the runtime verdict; only `candidate_gpu_capacity`
            authorises shrink advice.

The V19 collapse was lane 2 read as lane 3: a CUDA OOM raised while a
neighbouring chain held the card became "reduce model size", and the
campaign shrank to toy models.

This file is the tripwire. Mutating any two lanes into the same
behaviour must fail here.
"""

from __future__ import annotations

import pytest

from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    RESOURCE_ADMISSION_STATUS,
    _build_resource_admission_record,
    _may_advise_resource_reduction,
    _oom_memory_wording,
)

#: Lane 1's status. Not imported as a constant because production spells
#: it inline; that is itself worth pinning.
PREFLIGHT_ESTIMATE_STATUS = "skipped_oom_risk"

#: Phrasings that ADVISE shrinking. Lane 2's record legitimately contains
#: the words "reduce model capacity" inside its PROHIBITION, so a crude
#: word ban would fail on the very sentence that makes it safe. What must
#: never appear is the advisory form.
SHRINK_ADVICE = ("try smaller", "exceeds gpu memory", "reduce batch_size or model size")


def _admission_record(reason_code: str = "insufficient_headroom") -> dict:
    return _build_resource_admission_record(
        resource_type="gpu_memory",
        reason_code=reason_code,
        detail="31,500 MiB held by another process",
        exp_id="e1",
        model_type="punet",
        file_index=6,
        record_params={"batch_size": 4},
        expert_advice_str="none",
        hypothesis="fixture",
        round_index=2,
        attempt_in_round=1,
        admission_evidence={},
    )


class TestTheThreeStatusesAreDistinct:
    """One status per lane. A shared string makes every downstream
    consumer -- records, statistics, planner feedback -- unable to tell
    the three apart."""

    def test_all_three_differ(self):
        statuses = {
            PREFLIGHT_ESTIMATE_STATUS,
            RESOURCE_ADMISSION_STATUS,
            "error_training_oom",
        }
        assert len(statuses) == 3

    def test_admission_is_not_the_preflight_estimate_status(self):
        """The merge most likely to be proposed: both are "skipped before
        the phase ran"."""
        assert RESOURCE_ADMISSION_STATUS != PREFLIGHT_ESTIMATE_STATUS

    def test_admission_is_not_a_time_skip_either(self):
        """`skipped_time_risk` already carries three meanings; a fourth
        producer would pollute statistics that mean something else."""
        assert RESOURCE_ADMISSION_STATUS != "skipped_time_risk"

    def test_the_admission_record_carries_its_own_status(self):
        assert _admission_record()["status"] == RESOURCE_ADMISSION_STATUS


class TestWhetherThePhaseRan:
    """Lanes 1 and 2 refuse BEFORE launch; lane 3 is a post-mortem. The
    distinction decides whether any runtime evidence exists at all."""

    def test_an_admission_refusal_has_no_runtime_verdict(self):
        """Nothing ran, so there is no attribution to read -- and the
        absence must not be filled in with a guess."""
        record = _admission_record()
        assert record.get("failure_attribution") is None

    def test_an_admission_refusal_scores_nothing(self):
        assert _admission_record().get("denoising_score") is None


class TestBudgetAccounting:
    """A refusal costs an attempt but not a round. Without the first, a
    busy device could refuse forever inside one round; without the
    second, an environment problem would consume the scientific budget."""

    def test_an_admission_refusal_consumes_an_attempt(self):
        assert _admission_record()["counts_toward_attempt_budget"] is True

    def test_an_admission_refusal_does_not_complete_a_round(self):
        assert _admission_record()["counts_toward_completed_rounds"] is False


class TestFeedbackAuthority:
    """The axis that matters most, and the one a merged table would
    flatten first."""

    @pytest.mark.parametrize("reason_code", ["insufficient_headroom", "policy_unavailable"])
    def test_lane_2_never_advises_shrinking(self, reason_code):
        record = _admission_record(reason_code)
        memory = record["memory"]
        blob = f"{memory['conclusion']} {memory['discovery']} {memory['memory_update']}".lower()
        for advice in SHRINK_ADVICE:
            assert advice not in blob, f"lane 2 leaked shrink ADVICE: {advice!r}"
        # And it carries the prohibition, which is the control itself.
        assert "do not reduce" in blob

    def test_lane_2_says_the_machine_not_the_model(self):
        """The sentence IS the control."""
        discovery = _admission_record()["memory"]["discovery"].lower()
        assert "about the machine" in discovery
        assert "not about" in discovery and "candidate" in discovery

    def test_lane_2_has_no_reduction_authority(self):
        assert _may_advise_resource_reduction(_admission_record()) is False

    @pytest.mark.parametrize(
        "attribution,authorised",
        [
            ("candidate_gpu_capacity", True),
            ("gpu_contention", False),
            ("host_memory_pressure", False),
            ("external_termination", False),
            ("unknown", False),
        ],
    )
    def test_lane_3_authority_depends_on_the_verdict(self, attribution, authorised):
        """Only a candidate-capacity verdict may reach the planner as a
        reason to shrink. This is the V19 lesson."""
        status = {"failure_attribution": {"attribution": attribution}}
        assert _may_advise_resource_reduction(status) is authorised

    def test_lane_3_without_a_verdict_defaults_to_no_authority(self):
        """A missing verdict costs one piece of feedback; a wrong one
        costs a scientific conclusion."""
        for absent in ({}, {"failure_attribution": None}, {"failure_attribution": {}}):
            assert _may_advise_resource_reduction(absent) is False

    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_lane_3_may_carry_shrink_wording_when_authorised(self, phase):
        """The positive control. The gate suppresses a WRONG signal, not
        every signal -- otherwise the fix trades one silent failure for
        another."""
        status = {"failure_attribution": {"attribution": "candidate_gpu_capacity"}}
        # Returns (conclusion, memory_update) -- both are agent-facing.
        wording = " ".join(_oom_memory_wording(status, phase=phase)).lower()
        assert any(w in wording for w in ("reduce", "smaller", "lower"))

    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_lane_3_suppresses_shrink_wording_when_unattributed(self, phase):
        status = {"failure_attribution": {"attribution": "gpu_contention"}}
        wording = " ".join(_oom_memory_wording(status, phase=phase)).lower()
        assert "do not reduce" in wording
        assert "not evidence that the model was" in wording


class TestTheLanesCannotBeMergedSilently:
    """Cross-lane assertions. Each fails if two lanes are given the same
    treatment, which is exactly what a consolidation pass would do."""

    def test_lane_2_and_lane_3_do_not_share_an_authority_answer(self):
        """If they did, either a contention OOM could shrink the model, or
        a legitimate capacity OOM could not."""
        lane2 = _may_advise_resource_reduction(_admission_record())
        lane3_authorised = _may_advise_resource_reduction(
            {"failure_attribution": {"attribution": "candidate_gpu_capacity"}}
        )
        assert lane2 is False
        assert lane3_authorised is True
        assert lane2 != lane3_authorised

    def test_lane_3_phases_keep_distinct_wording(self):
        """`_oom_memory_wording` differs by phase. Collapsing the phase
        parameter would delete the only proof the two texts differ."""
        status = {"failure_attribution": {"attribution": "candidate_gpu_capacity"}}
        assert _oom_memory_wording(status, phase="training") != _oom_memory_wording(
            status, phase="inference"
        )
