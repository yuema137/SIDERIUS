"""Rejected ordering proposals must be recorded, never silently dropped.

Recovering from a malformed LLM proposal is acceptable — the established
``ExperimentPlan.with_defaults`` contract already does that for any bad
trial field, so one malformed token cannot kill a round. But the fallback
must not be SILENT: a rejected proposal is materially different from no
proposal, and downstream interpretation has to be able to tell them apart
(operator requirement, 2026-07-28).

Every rejection must expose:
  1. that an ordering proposal was present;
  2. that it was invalid and rejected;
  3. the rejection reason;
  4. the resolved ordering actually used;
  5. whether that came from an operator override or the default.
"""

import pytest

from agent.schemas.hyperparam_tuning import ExperimentPlan, ExperimentRecord
from agent.schemas.ordering import RejectedOrderingProposal, resolve_ordering

SCOPE = [4, 5, 6, 7, 8, 9]
PERMUTATION = [4, 6, 5, 9, 7, 8]


def _record(**overrides) -> ExperimentRecord:
    base = {
        "exp_id": "e1",
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-07-28T00:00:00Z",
        "params": {},
    }
    return ExperimentRecord(**{**base, **overrides})


# ---- scenario 1: invalid proposal + NO override ----


def test_invalid_proposal_without_override_falls_back_to_default_and_records_it():
    plan, rejected = ExperimentPlan.parse_with_fallback(
        {
            "model_type": "wavenet",
            "order_strategy": "sequential",
            "file_order": [4, 4, 4],  # duplicates
        }
    )
    assert plan.order_strategy is None, "the bad proposal must not reach execution"
    assert rejected is not None, "but it must not vanish either"

    resolved = resolve_ordering(resolved_scope=SCOPE, rejected_proposal=rejected)

    # 1. a proposal was present
    assert resolved.proposed_strategy == "sequential"
    assert resolved.proposed_file_order == [4, 4, 4]
    # 2. it was rejected
    assert resolved.proposal_rejected is True
    # 3. with a reason
    assert "duplicate" in resolved.proposal_rejection_reason
    # 4. and this is what actually ran
    assert resolved.resolved_strategy == "shuffle"
    assert resolved.resolved_file_order is None
    # 5. from the default, not from the agent
    assert resolved.resolution_source == "default"


def test_scenario_1_survives_into_the_record():
    _plan, rejected = ExperimentPlan.parse_with_fallback(
        {"model_type": "wavenet", "order_strategy": "sequential", "file_order": [4, 4, 4]}
    )
    resolved = resolve_ordering(resolved_scope=SCOPE, rejected_proposal=rejected)
    record = _record(
        proposed_order_strategy=resolved.proposed_strategy,
        proposed_file_order=resolved.proposed_file_order,
        ordering_proposal_rejected=resolved.proposal_rejected,
        ordering_proposal_rejection_reason=resolved.proposal_rejection_reason,
        resolved_order_strategy=resolved.resolved_strategy,
        resolved_file_order=resolved.resolved_file_order,
        ordering_resolution_source=resolved.resolution_source,
    )
    assert record.ordering_proposal_rejected is True
    assert record.proposed_order_strategy == "sequential"
    assert record.resolved_order_strategy == "shuffle"
    assert record.ordering_resolution_source == "default"
    # Round-trips, so a reader of the persisted artifact sees the same facts.
    assert ExperimentRecord.model_validate_json(record.model_dump_json()) == record


# ---- scenario 2: invalid proposal + VALID override ----


def test_invalid_proposal_with_override_still_records_the_rejection():
    _plan, rejected = ExperimentPlan.parse_with_fallback(
        {
            "model_type": "wavenet",
            "order_strategy": "sequential",
            "file_order": [],  # empty
        }
    )
    assert rejected is not None

    resolved = resolve_ordering(
        resolved_scope=SCOPE,
        rejected_proposal=rejected,
        override_strategy="sequential",
        override_file_order=PERMUTATION,
    )

    # The rejection is still recorded even though an override won.
    assert resolved.proposal_rejected is True
    assert "empty" in resolved.proposal_rejection_reason
    assert resolved.proposed_strategy == "sequential"
    # The override executed...
    assert resolved.resolved_strategy == "sequential"
    assert resolved.resolved_file_order == PERMUTATION
    assert resolved.resolution_source == "operator_override"


def test_override_is_never_attributed_to_the_agent():
    """The agent proposed something unusable; the operator supplied the value
    that ran. Nothing may present that value as the agent's."""
    _plan, rejected = ExperimentPlan.parse_with_fallback(
        {"model_type": "wavenet", "order_strategy": "sequential", "file_order": [4, 4]}
    )
    resolved = resolve_ordering(
        resolved_scope=SCOPE,
        rejected_proposal=rejected,
        override_strategy="sequential",
        override_file_order=PERMUTATION,
    )
    assert resolved.resolution_source != "agent_proposal"
    assert resolved.override_file_order == PERMUTATION
    assert resolved.proposed_file_order == [4, 4]
    assert resolved.proposed_file_order != resolved.resolved_file_order


# ---- the two rejection kinds are distinguished ----


def test_reason_names_the_ordering_when_the_ordering_is_the_defect():
    _plan, rejected = ExperimentPlan.parse_with_fallback(
        {"model_type": "wavenet", "order_strategy": "shuffle", "file_order": [4, 5]}
    )
    assert rejected is not None
    assert "the ordering proposal itself was invalid" in rejected.reason
    assert "meaningful only for sequential" in rejected.reason


def test_reason_says_dropped_when_another_field_is_the_defect():
    """A well-formed ordering discarded because trial_portion was invalid must
    not be reported as an ordering defect."""
    _plan, rejected = ExperimentPlan.parse_with_fallback(
        {
            "model_type": "wavenet",
            "order_strategy": "sequential",
            "file_order": PERMUTATION,  # perfectly valid
            "trial_portion": 5.0,  # out of range — this is the real failure
        }
    )
    assert rejected is not None
    assert "well-formed but was discarded" in rejected.reason
    assert "the ordering proposal itself was invalid" not in rejected.reason
    # The valid proposal is preserved verbatim for the record.
    assert rejected.strategy == "sequential"
    assert rejected.file_order == PERMUTATION


def test_no_ordering_proposal_means_no_rejection_to_report():
    _plan, rejected = ExperimentPlan.parse_with_fallback(
        {"model_type": "wavenet", "trial_portion": 5.0}
    )
    assert rejected is None


def test_a_valid_plan_reports_no_rejection():
    plan, rejected = ExperimentPlan.parse_with_fallback(
        {"model_type": "wavenet", "order_strategy": "sequential", "file_order": PERMUTATION}
    )
    assert rejected is None
    assert plan.order_strategy == "sequential"


def test_with_defaults_still_returns_only_the_plan():
    """Back-compat: existing callers are untouched by the new reporting path."""
    plan = ExperimentPlan.with_defaults({"model_type": "wavenet", "order_strategy": "sequential"})
    assert isinstance(plan, ExperimentPlan)
    assert plan.order_strategy == "sequential"


# ---- resolver contract ----


def test_a_proposal_cannot_be_both_applied_and_rejected():
    with pytest.raises(ValueError) as exc:
        resolve_ordering(
            resolved_scope=SCOPE,
            proposed_strategy="sequential",
            rejected_proposal=RejectedOrderingProposal(strategy="shuffle", reason="x"),
        )
    assert "self-contradictory" in str(exc.value)


def test_rejection_reason_may_not_be_empty():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RejectedOrderingProposal(strategy="sequential", reason="")


def test_describes_execution_flags_a_rejected_proposal():
    resolved = resolve_ordering(
        resolved_scope=SCOPE,
        rejected_proposal=RejectedOrderingProposal(strategy="sequential", reason="bad"),
    )
    assert "proposed=sequential(REJECTED)" in resolved.describes_execution()
    assert "source=default" in resolved.describes_execution()
