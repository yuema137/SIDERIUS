"""Non-executed attempts must not be labelled as legacy artifacts.

Found by the V19 PR 2 Gate 2 smoke: two ``skipped_time_risk`` attempts —
rejected at pre-flight in a CURRENT run — were being read as
``legacy_default``, whose meaning is "this artifact predates the ordering
feature". A reader of that manifest would conclude the run was partly
produced by pre-V19 code, which is false.

The round-keyed manifest is what exposed this. A single iteration-level
ordering value would have hidden it entirely.

Five provenance states, three of which mean an ordering actually ran:

    operator_override / agent_proposal / default   -> something executed
    legacy_default                                 -> pre-PR2 artifact
    not_executed                                   -> current attempt that
                                                      never reached training
"""

import pytest

from agent.schemas.hyperparam_tuning import (
    ExperimentMemory,
    ExperimentRecord,
    HyperparamTuningOutput,
)
from agent.schemas.ordering import NOT_EXECUTED_STATUSES, ResolvedOrdering
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary

PERMUTATION = [9, 7, 5, 4, 8, 6]


def _record(**overrides) -> ExperimentRecord:
    base = {
        "exp_id": "e1",
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-07-28T00:00:00Z",
        "params": {},
    }
    return ExperimentRecord(**{**base, **overrides})


# ---- 1. current non-executed attempt ----


@pytest.mark.parametrize("status", sorted(NOT_EXECUTED_STATUSES))
def test_preflight_rejected_attempt_is_not_executed(status):
    """No ordering ran, so none is reported — and it is NOT called legacy."""
    ordering = ResolvedOrdering.from_record(_record(status=status))

    assert ordering.resolution_source == "not_executed"
    assert ordering.resolved_strategy is None
    assert ordering.resolved_file_order is None
    assert ordering.resolution_source != "legacy_default"


def test_not_executed_does_not_invent_a_shuffle_value():
    """The specific bug: 'shuffle' must not be fabricated for something that
    never visited any data."""
    ordering = ResolvedOrdering.from_record(_record(status="skipped_time_risk"))
    assert ordering.resolved_strategy != "shuffle"
    assert ordering.resolved_strategy is None


# ---- 2. genuine legacy artifact ----


def test_pre_ordering_artifact_is_still_legacy_default():
    """A record from before the feature existed keeps the compatibility
    reading. Its status is a normal executed one — it simply has no ordering
    fields, because the code that would have written them did not exist."""
    ordering = ResolvedOrdering.from_record(_record(status="success"))

    assert ordering.resolution_source == "legacy_default"
    assert ordering.resolved_strategy == "shuffle"
    assert ordering.resolved_file_order is None


def test_legacy_and_not_executed_are_distinguishable():
    """The whole point of the fix."""
    legacy = ResolvedOrdering.from_record(_record(status="success"))
    skipped = ResolvedOrdering.from_record(_record(status="skipped_oom_risk"))

    assert legacy.resolution_source != skipped.resolution_source
    assert legacy.resolved_strategy == "shuffle"
    assert skipped.resolved_strategy is None


# ---- 3. executed override round ----


def test_executed_override_round_is_unchanged():
    ordering = ResolvedOrdering.from_record(
        _record(
            status="success",
            override_order_strategy="sequential",
            override_file_order=PERMUTATION,
            resolved_order_strategy="sequential",
            resolved_file_order=PERMUTATION,
            ordering_resolution_source="operator_override",
        )
    )
    assert ordering.resolution_source == "operator_override"
    assert ordering.resolved_strategy == "sequential"
    assert ordering.resolved_file_order == PERMUTATION


# ---- 4. executed default round ----


def test_executed_default_round_is_unchanged():
    ordering = ResolvedOrdering.from_record(
        _record(
            status="success",
            resolved_order_strategy="shuffle",
            resolved_file_order=None,
            ordering_resolution_source="default",
        )
    )
    assert ordering.resolution_source == "default"
    assert ordering.resolved_strategy == "shuffle"
    assert ordering.resolved_file_order is None


# ---- 5. rejected-proposal provenance survives non-execution ----


def test_a_rejected_proposal_survives_on_a_non_executed_attempt():
    """What the agent DID is independent of whether the attempt was admitted.
    The source still says not_executed — it describes what EXECUTED, never
    what would have been selected."""
    ordering = ResolvedOrdering.from_record(
        _record(
            status="skipped_time_risk",
            proposed_order_strategy="sequential",
            proposed_file_order=[4, 4, 4],
            ordering_proposal_rejected=True,
            ordering_proposal_rejection_reason="duplicate file indices [4]",
        )
    )
    assert ordering.proposal_rejected is True
    assert "duplicate" in ordering.proposal_rejection_reason
    assert ordering.proposed_strategy == "sequential"
    assert ordering.resolution_source == "not_executed"
    assert ordering.resolved_strategy is None


def test_an_override_is_not_claimed_as_executed_on_a_skipped_attempt():
    """An override in force does NOT mean it ran on an attempt that was never
    admitted."""
    ordering = ResolvedOrdering.from_record(
        _record(
            status="skipped_oom_risk",
            override_order_strategy="sequential",
            override_file_order=PERMUTATION,
        )
    )
    assert ordering.override_strategy == "sequential"
    assert ordering.resolution_source == "not_executed"
    assert ordering.resolution_source != "operator_override"
    assert ordering.resolved_strategy is None


# ---- 6. interpreter read-path compatibility ----


def _output(*records) -> HyperparamTuningOutput:
    return HyperparamTuningOutput(
        run_name="not_executed_test",
        model_type="punet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        started_at="2026-07-28T00:00:00Z",
        finished_at="2026-07-28T01:00:00Z",
        all_records=list(records),
    )


def test_interpreter_summary_distinguishes_the_three_absence_cases():
    """A mixture must retain distinct labels and never be collapsed."""
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                exp_id="executed",
                status="success",
                memory=ExperimentMemory(expert_advice_followed="n/a", hypothesis="n/a"),
                override_order_strategy="sequential",
                override_file_order=PERMUTATION,
                resolved_order_strategy="sequential",
                resolved_file_order=PERMUTATION,
                ordering_resolution_source="operator_override",
            ),
            _record(
                exp_id="skipped",
                status="skipped_time_risk",
                memory=ExperimentMemory(expert_advice_followed="n/a", hypothesis="n/a"),
            ),
            _record(
                exp_id="legacy",
                status="success",
                memory=ExperimentMemory(expert_advice_followed="n/a", hypothesis="n/a"),
            ),
        )
    )
    executed, skipped, legacy = summary.round_ordering

    assert executed.resolution_source == "operator_override"
    assert executed.resolved_order_strategy == "sequential"

    # The skipped attempt is NOT described as having run anything.
    assert skipped.resolution_source == "not_executed"
    assert skipped.resolved_order_strategy is None

    # The legacy artifact keeps its compatibility reading.
    assert legacy.resolution_source == "legacy_default"
    assert legacy.resolved_order_strategy == "shuffle"

    assert len({e.resolution_source for e in summary.round_ordering}) == 3
