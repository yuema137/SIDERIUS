"""V21 PR D3 — the seam PR D created, and the history it must not rewrite.

**This module is deliberately small, and the reason is a finding.** The
D3 plan called for downstream-consumer tests; auditing the suite first
showed the consumers are already covered, and CLAUDE.md forbids a test
that names no defect only it can catch. Already covered, and NOT
duplicated here:

```text
resume's real predicate admits an authoritative record
    tests/unit/core/test_resume_incumbent.py::test_an_authoritative_record_becomes_the_incumbent
...and refuses a non-authoritative one
    ::test_a_non_authoritative_record_never_becomes_the_incumbent
an undeclared legacy record is excluded as unreconstructable_legacy
    ::test_an_undeclared_legacy_record_is_excluded
a declared iteration reconstructs as reconstructed_legacy
    ::test_a_record_whose_iteration_declared_its_policy_is_usable
a trial record is never a formal incumbent
    ::test_a_trial_record_is_never_a_formal_incumbent
partition_for_aggregation includes/excludes and states the reason
    tests/integration/workflows/test_pr_d_positive_path_deterministic.py
```

Two properties are genuinely new, because PR D created the seam they
cross:

1. **The joint.** Every existing test starts from a hand-built verdict.
   None starts from a *launcher declaration* and follows it through the
   real transport into the consumers' admission rule. That whole-chain
   assertion is what PR D actually claims.
2. **History is not rewritten.** PR D makes new iterations declare their
   posture. It must not thereby confer authority on records written
   before it, which recorded none.

Design doc: ``docs/design/v21_priorities/pr_d_scientific_authority_reachable.md``
§0.F and Commit D3.
"""

from __future__ import annotations

import pytest

from agent.schemas.proposal import ExpertAdvice, ProposalOutput
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import ValidatorOutput
from core.scientific_authority import ScientificAuthority, resolve_record_authority
from execute_tools.scientific_aggregation import partition_for_aggregation
from tests.helpers.tuner_source import tuner_node_source


class _Summary:
    """The shape `partition_for_aggregation` consumes."""

    def __init__(self, model_type: str, verdict) -> None:
        self.model_type = model_type
        self.scientific_authority = verdict


def _tuning_input(tmp_path, **declaration):
    """Launcher declaration -> the REAL protocol -> HyperparamTuningInput."""
    return local_validated_model(
        ValidatorOutput(
            passed=True,
            model_type="punet",
            plugin_registered=True,
            tests_passed=True,
            description_valid=True,
            config_fields_valid=True,
            instantiation_passed=True,
            gradient_check_passed=True,
            llm_review_passed=True,
        ),
        ProposalOutput(
            model_name="punet",
            model_description="end-to-end authority probe",
            mathematical_definition="not exercised",
            motivation="follow a declaration into the consumers",
            expert_advice=ExpertAdvice(
                focus_areas=["authority"],
                constraints=[],
                known_failures=[],
                suggested_directions=[],
                rationale="deterministic fixture",
            ),
            baseline_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        ),
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="pr_d_e2e"),
        ),
        **declaration,
    )


def _formal_record(tmp_path, **declaration) -> dict:
    """A formal record stamped exactly as the tuner stamps one.

    Mirrors `ml_hyperparameter_tune_agent.py:5745-5752`: the verdict is
    built by `from_context` from the INPUT's two fields plus the record's
    own validity, and stored under `scientific_authority`.
    """
    tuning_input = _tuning_input(tmp_path, **declaration)
    verdict = ScientificAuthority.from_context(
        healthgate_mode=tuning_input.healthgate_mode,
        declared_result_authority=tuning_input.result_authority,
        formal_validity="valid",
    )
    return {
        "exp_id": "e2e_001",
        "model_type": "punet",
        "is_trial": False,
        "denoising_score": 1.0,
        "scientific_authority": verdict.model_dump(mode="json"),
    }


class TestTheWholeChainFromDeclarationToConsumer:
    """Launcher declaration -> transport -> verdict -> both consumers.

    Fails if ANY hop is severed, which is the point: the individual hops
    have their own tests, and this one asserts they are joined.
    """

    def test_a_declared_campaign_posture_ends_as_an_admissible_record(self, tmp_path):
        record = _formal_record(tmp_path, healthgate_mode="blocking", result_authority="scientific")

        resolution = resolve_record_authority(
            record,
            declared_healthgate_mode="blocking",
            declared_result_authority="scientific",
            commit_time_validity="valid",
        )
        assert resolution.basis == "stored_verdict"
        assert resolution.verdict is not None
        assert resolution.authoritative is True
        assert resolution.verdict.enters_incumbent_selection is True

        scope = partition_for_aggregation([_Summary("punet", record["scientific_authority"])])
        assert scope.included_count == 1
        assert scope.excluded_count == 0

    def test_an_undeclared_run_ends_excluded_by_both_consumers(self, tmp_path):
        """The pre-PR-D behaviour, still reachable and still correct.

        This is what the three dev/test/diagnostic launchers produce, and
        what `run_comparison` will keep producing per O-D-1.
        """
        record = _formal_record(tmp_path)
        assert record["scientific_authority"]["primary_basis"] == "legacy_authority_unknown"

        resolution = resolve_record_authority(
            record,
            declared_healthgate_mode=None,
            declared_result_authority=None,
            commit_time_validity="valid",
        )
        assert resolution.authoritative is False

        scope = partition_for_aggregation([_Summary("punet", record["scientific_authority"])])
        assert scope.included_count == 0
        assert scope.all_excluded is True

    @pytest.mark.parametrize(
        ("mode", "authority", "expected_basis"),
        [
            ("blocking", "diagnostic", "declared_diagnostic"),
            ("observe_only", "diagnostic", "declared_diagnostic"),
            ("blocking", None, "legacy_authority_unknown"),
            (None, "scientific", "legacy_authority_unknown"),
        ],
    )
    def test_other_postures_reach_their_own_blocker_not_a_generic_one(
        self, tmp_path, mode, authority, expected_basis
    ):
        """Transport carries the posture faithfully enough to be judged.

        A declared-diagnostic run must be excluded *as diagnostic*, not as
        unknown: the operator reading the exclusion reason needs to know
        the run was deliberately not promoted, rather than that its
        declaration was lost in transit — which is precisely the confusion
        PR D removes.
        """
        record = _formal_record(tmp_path, healthgate_mode=mode, result_authority=authority)
        assert record["scientific_authority"]["primary_basis"] == expected_basis


class TestPRDConfersNoRetroactiveAuthority:
    """A record written before PR D recorded no posture. It keeps none.

    The risk is specific and worth naming: `resolve_record_authority`
    reconstructs a verdict-less record from an OUTPUT-level declaration
    (`core/scientific_authority.py:290-302`). If that declaration were the
    *current* run's, then simply declaring a posture today would make
    every historical record authoritative retroactively.

    It is not the current run's. `core/resume.py:299` loads each
    iteration's own persisted `HyperparamTuningOutput`, so a pre-PR-D
    artifact still carries `None` and still resolves
    `unreconstructable_legacy`.
    """

    @staticmethod
    def _legacy_record() -> dict:
        """A formal record from before the authority contract existed."""
        return {"exp_id": "legacy_001", "model_type": "punet", "is_trial": False}

    def test_a_pre_contract_record_stays_unreconstructable(self):
        resolution = resolve_record_authority(
            self._legacy_record(),
            declared_healthgate_mode=None,
            declared_result_authority=None,
            commit_time_validity="valid",
        )
        assert resolution.basis == "unreconstructable_legacy"
        assert resolution.authoritative is False

    def test_reconstruction_uses_the_ITERATIONS_declaration_not_todays(self):
        """The load-bearing distinction, asserted directly.

        Reconstruction to `reconstructed_legacy` is an EXISTING, deliberate
        rule (§12A) and PR D does not remove it — but it is keyed to the
        declaration passed in, and `resume` passes the *resumed
        iteration's own* output. This test pins the function's contract;
        `core/resume.py:299` is what guarantees the argument's provenance.
        """
        legacy = self._legacy_record()

        # The iteration itself declared nothing -> unknown, whatever today does.
        assert (
            resolve_record_authority(
                legacy,
                declared_healthgate_mode=None,
                declared_result_authority=None,
                commit_time_validity="valid",
            ).basis
            == "unreconstructable_legacy"
        )

        # Only when THAT iteration's own output carried a declaration does
        # the existing §12A ladder reconstruct it.
        reconstructed = resolve_record_authority(
            legacy,
            declared_healthgate_mode="blocking",
            declared_result_authority="scientific",
            commit_time_validity="valid",
        )
        assert reconstructed.basis == "reconstructed_legacy"

    def test_resume_reads_each_iterations_own_output(self):
        """Provenance of the declaration `resume` supplies.

        Asserted on source because the alternative — a chain fixture with
        two iterations of differing posture — would test the same single
        fact far more expensively. If this line ever read the current
        run's declaration instead, historical records would silently gain
        authority.
        """
        import inspect

        from core import resume

        src = inspect.getsource(resume)
        assert "HyperparamTuningOutput.model_validate_json(text)" in src, (
            "resume no longer parses each iteration's own persisted output; "
            "verify it cannot be passing the CURRENT run's declaration into "
            "resolve_record_authority"
        )


class TestTrialRecordsAreUntouched:
    def test_the_stamp_is_guarded_by_the_formal_branch(self):
        """Trials carry no authority block, by design.

        Writing `authoritative: False` on a trial would conflate "formal
        authority does not apply here" with "this formal result was judged
        untrustworthy". PR D transports a declaration; it must not start
        stamping trials.
        """
        import inspect

        import nodes.ml_hyperparameter_tune_agent as tuner

        src = tuner_node_source()
        stamp = 'final_record["scientific_authority"] = ScientificAuthority.from_context('
        assert stamp in src
        preceding = src[: src.index(stamp)]
        assert preceding.rstrip().endswith("if not trial_config.is_trial:"), (
            "the authority stamp is no longer guarded by the formal-only "
            "branch; trial records would acquire an authority block"
        )
