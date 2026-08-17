"""A gate result says what the gate WAS, not what its id is spelled like.

V20 PR D, checkpoint D-C7b.

Gate ids carry a historical `_blocking` suffix that names the ROLE the gate
was written for. Under an observe-only config such a gate resolves
`continue` and blocks nothing — yet every report echoing its id said
"blocking", which is the 08:17-class lie one level down: the artifact reads
enforced, the run was not.

**Ids are never rewritten.** They are the join key for
`health_gate_results` and for archived artifacts, so renaming would break
comparison against history. The honest label is added BESIDE the id and
derived from what was actually configured.

The five fields recorded together: `gate_name` (stable), `gate_role`,
`configured_action`, `healthgate_mode`, `result_authority` — plus
`resolved_action`, which already existed.
"""

from __future__ import annotations

import pytest

from execute_tools.health_checks.schemas import GateAction, PersistedHealthGateResult
from tests.helpers.tuner_source import tuner_lifecycle_source


def _result(**overrides) -> PersistedHealthGateResult:
    base = {
        "gate_name": "output_diversity_blocking",
        "execution_status": "passed",
        "check_passed": True,
        "would_invalidate_under_production_policy": False,
        "resolved_action": GateAction.CONTINUE,
    }
    base.update(overrides)
    return PersistedHealthGateResult(**base)


class TestTheLabelStopsLying:
    def test_a_blocking_named_gate_that_enforces_nothing_reads_observational(self):
        """THE DEFECT. Its id says blocking; under an observe-only config it
        cannot invalidate anything, and the label must say so."""
        result = _result(
            configured_action=GateAction.CONTINUE,
            gate_role="observational",
            healthgate_mode="observe_only",
        )
        assert result.display_label == "output_diversity_blocking (observational)"
        assert "blocking)" not in result.display_label

    def test_a_gate_that_really_enforces_reads_enforcing(self):
        result = _result(
            configured_action=GateAction.INVALIDATE_ROUND,
            gate_role="blocking",
            healthgate_mode="blocking",
        )
        assert result.display_label == "output_diversity_blocking (enforcing)"

    def test_an_unestablished_role_says_so_rather_than_guessing(self):
        """MUTATION TARGET: defaulting a legacy result to enforcing.

        A result predating the declaration cannot have its posture
        reconstructed, and `role-unknown` is the honest answer — the same
        rule the authority boundary applies.
        """
        assert _result().display_label == "output_diversity_blocking (role-unknown)"

    def test_the_label_is_derived_from_the_action_not_the_id(self):
        """MUTATION TARGET: reading the id's suffix.

        A gate named without any suffix that DOES enforce must still read
        enforcing, and one named `_blocking` that does not must not.
        """
        enforcing = _result(gate_name="quiet_name", configured_action=GateAction.SKIP_ITER)
        observational = _result(gate_name="loud_blocking", configured_action=GateAction.CONTINUE)
        assert "enforcing" in enforcing.display_label
        assert "observational" in observational.display_label

    def test_the_gate_id_itself_is_never_rewritten(self):
        """It is the join key for archived artifacts."""
        result = _result(configured_action=GateAction.CONTINUE, gate_role="observational")
        assert result.gate_name == "output_diversity_blocking"
        assert result.display_label.startswith("output_diversity_blocking")


class TestTheFiveFieldsAreRecordedTogether:
    @pytest.mark.parametrize(
        "field",
        ["gate_name", "gate_role", "configured_action", "healthgate_mode", "result_authority"],
    )
    def test_each_field_is_declared(self, field):
        assert field in PersistedHealthGateResult.model_fields

    def test_configured_and_resolved_actions_are_distinct_facts(self):
        """`resolved_action: continue` alone is ambiguous: it means either
        'the check passed, so nothing to do' or 'configured to do nothing'.
        Only both together distinguish them."""
        passed_but_enforcing = _result(
            check_passed=True,
            resolved_action=GateAction.CONTINUE,
            configured_action=GateAction.INVALIDATE_ROUND,
        )
        assert passed_but_enforcing.resolved_action is GateAction.CONTINUE
        assert passed_but_enforcing.configured_action is GateAction.INVALIDATE_ROUND
        assert "enforcing" in passed_but_enforcing.display_label

    def test_legacy_results_still_validate(self):
        """Backward compatibility: every new field is optional, so an
        archived result parses unchanged."""
        legacy = PersistedHealthGateResult.model_validate(
            {
                "gate_name": "amplitude_collapse_blocking",
                "execution_status": "passed",
                "check_passed": True,
                "would_invalidate_under_production_policy": False,
                "resolved_action": "continue",
            }
        )
        assert legacy.gate_role is None
        assert legacy.configured_action is None

    def test_the_label_survives_serialisation(self):
        import json

        result = _result(configured_action=GateAction.CONTINUE, gate_role="observational")
        restored = json.loads(json.dumps(result.model_dump(mode="json"), allow_nan=False))
        assert restored["display_label"] == "output_diversity_blocking (observational)"
        assert restored["gate_name"] == "output_diversity_blocking"


class TestTheProducerRecordsThem:
    def test_the_evaluator_threads_the_declaration(self):
        import inspect

        from execute_tools.health_checks import evaluation

        src = inspect.getsource(evaluation)
        assert "healthgate_mode=healthgate_mode" in src
        assert "result_authority=result_authority" in src
        assert "configured_action=gate_config.on_fail.action" in src

    def test_the_tuner_supplies_its_declared_posture(self):
        """MUTATION TARGET: recording the fields but never populating them.

        Asserted on the GATE-EVALUATION call specifically. An earlier
        version searched the whole of `run()`, where
        `healthgate_mode=agent_input.healthgate_mode` appears three times
        (D-C2b's authority block, D-C6's trial feedback, and this call) —
        so deleting it here still passed. A mutation proved that, which is
        the only reason it was caught.
        """
        import inspect

        from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent

        src = tuner_lifecycle_source()
        start = src.find("evaluate_and_persist_health_gates(")
        assert start != -1, "the gate-evaluation call site disappeared"
        # A bounded window rather than a balanced-paren match: the call
        # contains a nested `os.path.join(...)`, so a non-greedy regex stops
        # at the WRONG closing paren and silently truncates the body.
        body = src[start : start + 1400]
        assert "healthgate_mode=agent_input.healthgate_mode" in body
        assert "result_authority=agent_input.result_authority" in body

    def test_the_role_is_read_from_config_never_inferred(self):
        """The predecessor hotfix `af5339ce` removed action-derived role
        inference; it must not return here."""
        import inspect

        from execute_tools.health_checks import evaluation

        src = inspect.getsource(evaluation)
        assert 'gate_role=getattr(gate_config, "gate_role", None)' in src


class TestNoConfigWasTouched:
    def test_the_audited_config_shas_are_unchanged(self):
        """ACCEPTANCE CRITERION: recording the fields must not shift
        `health_config_sha256`, or every workspace invariant lock would
        break at the boundary. These are the exact pre-hotfix values in the
        audited compatibility map.
        """
        from execute_tools.health_checks.candidate_eligibility import legacy_config_body_sha

        assert legacy_config_body_sha("configs/health_checks.yaml") == (
            "3b5521180f5460a4a7aa67ad0ff67701633d75ed8fdcac4277c222b713655b74"
        )
        assert legacy_config_body_sha("configs/health_checks_baseline_observe_mode.yaml") == (
            "d133a12d3133fb20d632383aa010b1a861fe0fdb6fb6436874b2142d6b5ef58d"
        )
