"""An infrastructure failure is not a resource refusal, and is not retried.

V20 attempt 2, layers 2 and 3. When the pre-phase measurement worker
failed, the tuner:

* persisted the record as `skipped_resource_admission` — which reads as
  "the candidate was refused for resources" while the GPU sat at 1.6 of
  32.6 GiB; and
* treated it as an ordinary attempt failure and retried, burning
  `attempts_per_round` fifteen times against an identical deterministic
  condition.

Both are guarded here. The `reason_code` vocabulary is unchanged — only
the top-level status and the control flow.
"""

from __future__ import annotations

import ast

import pytest

from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _STATUS_FOR_REASON,
    INFRASTRUCTURE_FAILURE_STATUS,
    RESOURCE_ADMISSION_REASONS,
    RESOURCE_ADMISSION_STATUS,
    PrephaseOutcome,
    _build_resource_admission_record,
)

COMMON = dict(
    resource_type="gpu_memory",
    exp_id="exp_001",
    model_type="generated_candidate",
    file_index=0,
    record_params={},
    expert_advice_str="",
    hypothesis="",
    round_index=1,
    attempt_in_round=1,
)


class TestStatusHonesty:
    def test_a_measurement_failure_is_not_filed_as_a_resource_refusal(self):
        rec = _build_resource_admission_record(
            reason_code="measurement_unavailable",
            detail="worker returned CONFIG_REJECTED",
            **COMMON,
        )
        assert rec["status"] == INFRASTRUCTURE_FAILURE_STATUS
        assert rec["status"] != RESOURCE_ADMISSION_STATUS, (
            "V20 attempt 2 wrote 15 of these while the GPU was idle; an "
            "auditor reading them would conclude the campaign hit resource "
            "limits"
        )

    def test_a_genuine_headroom_verdict_keeps_the_resource_status(self):
        rec = _build_resource_admission_record(
            reason_code="insufficient_headroom",
            detail="63.7 GiB predicted against a 12 GiB ceiling",
            **COMMON,
        )
        assert rec["status"] == RESOURCE_ADMISSION_STATUS

    def test_policy_unavailable_is_also_infrastructure(self):
        rec = _build_resource_admission_record(
            reason_code="policy_unavailable", detail="no authoritative requirement", **COMMON
        )
        assert rec["status"] == INFRASTRUCTURE_FAILURE_STATUS

    def test_every_reason_maps_to_a_status(self):
        # A new reason with no mapping would raise KeyError at the worst
        # possible moment — inside a live campaign's failure path.
        for reason in RESOURCE_ADMISSION_REASONS:
            assert reason in _STATUS_FOR_REASON

    def test_the_conclusion_does_not_blame_the_candidate(self):
        rec = _build_resource_admission_record(
            reason_code="measurement_unavailable", detail="worker died", **COMMON
        )
        conclusion = rec["memory"]["conclusion"]
        assert "says nothing about the candidate" in conclusion
        # The planner must not be told the environment "did not permit" the
        # phase — nothing was measured, so nothing was permitted or refused.
        assert "did not permit" not in conclusion

    def test_a_headroom_conclusion_still_reads_as_a_resource_decision(self):
        rec = _build_resource_admission_record(
            reason_code="insufficient_headroom", detail="short by 51 GiB", **COMMON
        )
        assert "did not permit" in rec["memory"]["conclusion"]

    def test_the_reason_vocabulary_was_not_expanded(self):
        # The fix is one extra STATUS, not a new taxonomy.
        assert RESOURCE_ADMISSION_REASONS == (
            "insufficient_headroom",
            "measurement_unavailable",
            "policy_unavailable",
        )


def _signals(node, keyword: str, statement: type) -> bool:
    """Does this branch issue the given attempt-loop control decision?

    Step 07 PR 07b, C7d moved the pre-phase branches out of ``run()`` into the
    node's ``execution`` module, where a phase cannot ``break``/``continue`` the
    loop it no longer contains — it RETURNS the decision and ``run()`` performs
    the jump. Both spellings are accepted because both are the same decision;
    what must never pass is a branch that issues NEITHER, or issues the other
    one. That is the property these tests were written to defend, and it is
    unchanged.
    """
    if any(isinstance(n, statement) for n in ast.walk(node)):
        return True
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == keyword
        for n in ast.walk(node)
    )


def _ends_the_round(node) -> bool:
    return _signals(node, "end_round", ast.Break)


def _consumes_the_attempt(node) -> bool:
    return _signals(node, "next_attempt", ast.Continue)


class TestRetrySemantics:
    def test_the_two_terminal_causes_are_distinguishable(self):
        # A bool could not express this, which is why the caller conflated
        # "does not fit" with "could not be measured".
        assert (
            PrephaseOutcome.TERMINAL_INFRASTRUCTURE_FAILURE
            != PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL
        )
        assert PrephaseOutcome.PROCEED not in (
            PrephaseOutcome.TERMINAL_INFRASTRUCTURE_FAILURE,
            PrephaseOutcome.TERMINAL_RESOURCE_REFUSAL,
        )

    def test_the_caller_ends_the_round_on_infrastructure_failure(self):
        # Reachability against the production call site, by AST: a `continue`
        # here is the V20 attempt-2 behaviour (retry the identical condition);
        # it must be a `break` so the round ends.
        import ast

        from tests.helpers.tuner_source import tuner_node_source

        src = tuner_node_source()
        tree = ast.parse(src)
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test_src = ast.get_source_segment(src, node.test) or ""
            if "TERMINAL_INFRASTRUCTURE_FAILURE" in test_src:
                found.append(_ends_the_round(node))
        assert found, "no production branch handles TERMINAL_INFRASTRUCTURE_FAILURE"
        assert all(found), (
            "the infrastructure branch must BREAK out of the attempt loop; a "
            "continue re-enters the identical deterministic failure, which is "
            "how attempt 2 burned 15 attempts"
        )

    def test_a_resource_refusal_still_consumes_the_attempt(self):
        # The guard must be narrow: a candidate that genuinely does not fit
        # should still let the next, possibly smaller, candidate try.
        import ast

        from tests.helpers.tuner_source import tuner_node_source

        src = tuner_node_source()
        tree = ast.parse(src)
        ok = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test_src = ast.get_source_segment(src, node.test) or ""
            if "TERMINAL_RESOURCE_REFUSAL" in test_src:
                ok.append(_consumes_the_attempt(node))
        assert ok and all(ok), "a resource refusal must still consume the attempt"

    @pytest.mark.parametrize(
        ("disposition", "expected_reason"),
        [
            ("STOP_OVER_CAP", "insufficient_headroom"),
            ("STOP_MEASURED_OOM", "insufficient_headroom"),
            ("STOP_INFRASTRUCTURE_FAILURE", "measurement_unavailable"),
            ("STOP_TIMEOUT", "measurement_unavailable"),
            ("STOP_MEASUREMENT_UNAVAILABLE", "measurement_unavailable"),
            ("STOP_PROBE_HOST_MEMORY_EXCEEDED", "measurement_unavailable"),
        ],
    )
    def test_disposition_reason_mapping_is_unchanged(self, disposition, expected_reason):
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _PREPHASE_REASON_CODE,
        )

        assert _PREPHASE_REASON_CODE[disposition] == expected_reason
