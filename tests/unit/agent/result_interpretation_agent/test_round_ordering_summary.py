"""The interpreter sees resolved ordering, per round, with rejections intact.

Two rules are pinned here
(``docs/design/v19_priorities/pr2_data_ordering.md`` §3.7):

- ``resolved_*`` is the only pair describing execution — an overridden
  proposal is never surfaced as what ran;
- a rejected proposal is visible AS rejected, never as agent silence.

Ordering is carried per round rather than collapsed for the run, because
it may legitimately differ between rounds when no override is in force.
"""

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import shipped_spec

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as a
#: REQUIRED keyword. The shipped TIDMAD spec is `higher`, so every expectation in
#: this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(shipped_spec())

PERMUTATION = [4, 6, 5, 9, 7, 8]


def _record(exp_id: str, **overrides) -> ExperimentRecord:
    base = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-07-28T00:00:00Z",
        "params": {},
        "denoising_score": 1.0,
    }
    return ExperimentRecord(**{**base, **overrides})


def _output(*records) -> HyperparamTuningOutput:
    return HyperparamTuningOutput(
        run_name="ordering_summary_test",
        model_type="wavenet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        started_at="2026-07-28T00:00:00Z",
        finished_at="2026-07-28T01:00:00Z",
        all_records=list(records),
    )


def test_resolved_ordering_is_carried_per_round():
    """Rounds may differ; the summary must keep them distinct and aligned
    with round_scores."""
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                resolved_order_strategy="sequential",
                resolved_file_order=PERMUTATION,
                ordering_resolution_source="agent_proposal",
                proposed_order_strategy="sequential",
            ),
            _record(
                "r2",
                resolved_order_strategy="shuffle",
                ordering_resolution_source="default",
            ),
        ),
        order=_STEP09A_ORDER,
    )
    assert len(summary.round_ordering) == len(summary.round_scores) == 2

    first, second = summary.round_ordering
    assert (first.exp_id, first.resolved_order_strategy) == ("r1", "sequential")
    assert first.resolved_file_order == PERMUTATION
    assert first.resolution_source == "agent_proposal"
    assert (second.exp_id, second.resolved_order_strategy) == ("r2", "shuffle")
    assert second.resolved_file_order is None
    assert second.resolution_source == "default"


def test_an_overridden_proposal_is_not_presented_as_what_ran():
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                proposed_order_strategy="sequential",
                proposed_file_order=PERMUTATION,
                override_order_strategy="shuffle",
                resolved_order_strategy="shuffle",
                resolved_file_order=None,
                ordering_resolution_source="operator_override",
            )
        ),
        order=_STEP09A_ORDER,
    )
    entry = summary.round_ordering[0]
    assert entry.resolved_order_strategy == "shuffle"
    assert entry.resolution_source == "operator_override"
    # The proposal is visible as context, and is clearly not the executed value.
    assert entry.proposed_order_strategy == "sequential"
    assert entry.proposed_order_strategy != entry.resolved_order_strategy


def test_a_rejected_proposal_is_visible_as_rejected():
    """Not as 'the agent proposed nothing'."""
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                proposed_order_strategy="sequential",
                proposed_file_order=[4, 4, 4],
                ordering_proposal_rejected=True,
                ordering_proposal_rejection_reason="duplicate file indices [4]",
                resolved_order_strategy="shuffle",
                ordering_resolution_source="default",
            )
        ),
        order=_STEP09A_ORDER,
    )
    entry = summary.round_ordering[0]
    assert entry.proposal_rejected is True
    assert "duplicate" in entry.proposal_rejection_reason
    assert entry.proposed_order_strategy == "sequential"
    assert entry.resolved_order_strategy == "shuffle"
    assert entry.resolution_source == "default"


def test_silence_and_rejection_are_distinguishable():
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "quiet",
                resolved_order_strategy="shuffle",
                ordering_resolution_source="default",
            ),
            _record(
                "overruled",
                proposed_order_strategy="sequential",
                ordering_proposal_rejected=True,
                ordering_proposal_rejection_reason="bad",
                resolved_order_strategy="shuffle",
                ordering_resolution_source="default",
            ),
        ),
        order=_STEP09A_ORDER,
    )
    quiet, overruled = summary.round_ordering
    # Same executed ordering, materially different agent behavior.
    assert quiet.resolved_order_strategy == overruled.resolved_order_strategy == "shuffle"
    assert quiet.proposal_rejected is False
    assert quiet.proposed_order_strategy is None
    assert overruled.proposal_rejected is True
    assert overruled.proposed_order_strategy == "sequential"


def test_pre_ordering_records_read_as_legacy_default():
    """A record written before the ordering option existed has no ordering
    fields. It is read explicitly, not guessed at."""
    summary = tuning_output_to_model_run_summary(_output(_record("legacy")), order=_STEP09A_ORDER)
    entry = summary.round_ordering[0]
    assert entry.resolved_order_strategy == "shuffle"
    assert entry.resolution_source == "legacy_default"
    assert entry.proposed_order_strategy is None
    assert entry.proposal_rejected is False


def test_summary_round_trips_through_json():
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                resolved_order_strategy="sequential",
                resolved_file_order=PERMUTATION,
                ordering_resolution_source="operator_override",
                override_order_strategy="sequential",
            )
        ),
        order=_STEP09A_ORDER,
    )
    from agent.schemas.interpretation import ModelRunSummary

    restored = ModelRunSummary.model_validate_json(summary.model_dump_json())
    assert restored.round_ordering == summary.round_ordering
