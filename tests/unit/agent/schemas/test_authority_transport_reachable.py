"""V21 PR D2 — the declared posture survives every transport hop.

PR D's whole defect was a **correct rule nothing reached**: the authority
verdict is derived properly, and no production launcher supplied the two
declarations it derives from. So the tests that matter here are
reachability tests, and they drive the **real** production transport
functions rather than re-implementing them.

That is not a stylistic preference. B1b's `P2` mutation survived precisely
because a test re-implemented the production expression it claimed to
guard; the mutation deleted production's behaviour and the test, checking
its own copy, stayed green.

```text
run_one_iteration.py:1846   -> run_workflow(...)                 hop 7
run_workflow                -> local_validated_model(...)        hop 8
local_validated_model       -> HyperparamTuningInput             hop 9
                            -> ScientificAuthority.from_context  (existing)
```

Hops 8 and 9 are exercised in-process below. Hop 7's call site lives
inside `run_one_iteration.__main__`, which no deterministic fixture
executes, so it is covered by a source assertion plus mutations
`M-D1`/`M-D2` — the same treatment B1b gave its clamp inside `run()`.

**Absence is information.** `None` is a legitimate declared-nothing state
for every dev/test/diagnostic launcher (design §0.C.1), and it must stay
distinguishable from a real declaration. Two distinct harms are guarded:

```text
one axis defaulted   -> still legacy_authority_unknown, but the record now
                        carries a declaration the launcher never made
both axes defaulted  -> AUTHORITY FABRICATED for a valid formal round
```

Design doc: ``docs/design/v21_priorities/pr_d_scientific_authority_reachable.md``
Commit D2.
"""

from __future__ import annotations

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.proposal import ExpertAdvice, ProposalOutput
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from core.scientific_authority import ScientificAuthority


def _validator_output(model_type: str = "punet") -> ValidatorOutput:
    return ValidatorOutput(
        passed=True,
        model_type=model_type,
        plugin_registered=True,
        tests_passed=True,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=True,
        gradient_check_passed=True,
        llm_review_passed=True,
    )


def _proposal(model_name: str = "punet") -> ProposalOutput:
    return ProposalOutput(
        model_name=model_name,
        model_description="authority transport probe",
        mathematical_definition="not exercised by this test",
        motivation="prove the declared posture survives the protocol hop",
        expert_advice=ExpertAdvice(
            focus_areas=["transport"],
            constraints=[],
            known_failures=[],
            suggested_directions=[],
            rationale="deterministic fixture, no LLM",
        ),
        baseline_config={"model_config": {}, "train_config": {}, "loss_config": {}},
    )


def _storage(tmp_path) -> StorageConfig:
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="pr_d_transport"),
    )


def _through_protocol(tmp_path, **declaration) -> HyperparamTuningInput:
    """Hops 8->9 through the REAL protocol function."""
    return local_validated_model(
        _validator_output(), _proposal(), _storage(tmp_path), **declaration
    )


class TestTheProtocolCarriesTheDeclaration:
    def test_a_declared_posture_arrives_unchanged(self, tmp_path):
        got = _through_protocol(tmp_path, healthgate_mode="blocking", result_authority="scientific")
        assert got.healthgate_mode == "blocking"
        assert got.result_authority == "scientific"

    @pytest.mark.parametrize(
        ("mode", "authority"),
        [
            ("blocking", "scientific"),
            ("blocking", "diagnostic"),
            ("observe_only", "diagnostic"),
        ],
    )
    def test_every_legal_posture_is_carried_verbatim(self, tmp_path, mode, authority):
        """No normalisation, mapping or case-folding anywhere on the hop.

        `observe_only + scientific` is deliberately absent: it is refused
        at the launcher by `validate_formal_launch`, and the transport
        must NOT duplicate that check — a second copy of a rule is a
        second thing to keep in sync.
        """
        got = _through_protocol(tmp_path, healthgate_mode=mode, result_authority=authority)
        assert (got.healthgate_mode, got.result_authority) == (mode, authority)

    def test_an_undeclared_caller_produces_None_on_both_axes(self, tmp_path):
        """The three dev/test/diagnostic launchers rely on this.

        They call `run_workflow` without the new keywords and must keep
        their current behaviour with no edit at all.
        """
        got = _through_protocol(tmp_path)
        assert got.healthgate_mode is None
        assert got.result_authority is None

    def test_an_invalid_literal_is_refused_by_the_schema(self, tmp_path):
        """Fail loudly at the typed boundary; never coerce."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            _through_protocol(tmp_path, healthgate_mode="enforcing")
        with pytest.raises(pydantic.ValidationError):
            _through_protocol(tmp_path, result_authority="Scientific")


class TestTheDeclarationReachesTheAuthorityRule:
    """Hop 9 -> the existing rule, exactly as the tuner calls it.

    The tuner's call is
    `ScientificAuthority.from_context(healthgate_mode=agent_input.healthgate_mode,
    declared_result_authority=agent_input.result_authority, formal_validity=...)`
    (`ml_hyperparameter_tune_agent.py:5745-5752`). These drive the same
    two-step with the input the protocol actually built.
    """

    @staticmethod
    def _verdict(tuning_input: HyperparamTuningInput, validity: str = "valid"):
        return ScientificAuthority.from_context(
            healthgate_mode=tuning_input.healthgate_mode,
            declared_result_authority=tuning_input.result_authority,
            formal_validity=validity,
        )

    def test_declared_blocking_scientific_becomes_authoritative(self, tmp_path):
        """The property PR D exists to restore."""
        verdict = self._verdict(
            _through_protocol(tmp_path, healthgate_mode="blocking", result_authority="scientific")
        )
        assert verdict.authoritative is True
        assert verdict.primary_basis == "blocking_scientific_formal_valid"
        assert verdict.enters_incumbent_selection is True
        assert verdict.enters_scientific_aggregation is True

    def test_undeclared_remains_legacy_authority_unknown(self, tmp_path):
        """Pins the pre-D2 behaviour for callers that declare nothing.

        This is also the test that catches **M-D5b**: if the transport
        ever defaulted both axes to `blocking`/`scientific`, an undeclared
        caller's valid formal round would become authoritative — authority
        fabricated from silence.
        """
        verdict = self._verdict(_through_protocol(tmp_path))
        assert verdict.authoritative is False
        assert verdict.primary_basis == "legacy_authority_unknown"

    @pytest.mark.parametrize(
        ("mode", "authority"),
        [("blocking", None), (None, "scientific")],
    )
    def test_a_partial_declaration_still_blocks(self, tmp_path, mode, authority):
        """The either-axis rule, at the transport boundary.

        Catches **M-D5a**: defaulting one axis cannot manufacture
        authority — but it does destroy absence semantics, so the arriving
        value must still be exactly what the caller supplied.
        """
        got = _through_protocol(tmp_path, healthgate_mode=mode, result_authority=authority)
        assert (got.healthgate_mode, got.result_authority) == (mode, authority)
        verdict = self._verdict(got)
        assert verdict.authoritative is False
        assert verdict.primary_basis == "legacy_authority_unknown"

    def test_a_declared_posture_does_not_override_the_records_own_validity(self, tmp_path):
        """Declaring `scientific` does not make an invalid round valid.

        Authority is a conjunct on top of the record's own gate verdict,
        never a replacement for it (`core/resume.py:1350-1356`).
        """
        declared = _through_protocol(
            tmp_path, healthgate_mode="blocking", result_authority="scientific"
        )
        assert self._verdict(declared, "invalid").primary_basis == "gate_invalidated"
        assert self._verdict(declared, "unknown").primary_basis == "formal_validity_unknown"
