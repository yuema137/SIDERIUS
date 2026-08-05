"""Every formal record carries its authority verdict; no trial record does.

V20 PR D, checkpoint D-C2b — wiring only. Consumers are unchanged:
incumbent selection, aggregation and reporting all still behave exactly as
before, so the accurate description is **selection Behavior Delta none,
formal-record schema/provenance delta present**.

Two asymmetries are deliberate and are what these tests protect:

- **every** formal record gets a verdict — valid, invalid, diagnostic and
  validity-unknown alike. A field present only on successes would make its
  absence ambiguous.
- **no** trial record gets one. Writing ``authoritative: False`` on a trial
  would conflate *"formal authority does not apply here"* with *"this
  formal result was judged untrustworthy"*, and those call for opposite
  operator responses.
"""

from __future__ import annotations

import json

import pytest

from core.scientific_authority import ScientificAuthority
from execute_tools.health_checks.candidate_eligibility import formal_validity_of

BLOCKING = "configs/health_checks.yaml"
SCIENTIFIC_GATES = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)


def _record(*, passed: bool = True, gates: bool = True) -> dict:
    """A completed record. ``gates=False`` omits the verdicts entirely,
    which is how validity becomes UNKNOWN rather than a pass."""
    record: dict = {"status": "success", "denoising_score": 1.23}
    record["health_gate_results"] = (
        [
            {
                "gate_name": gate,
                "execution_status": "passed",
                "check_passed": passed,
                "would_invalidate_under_production_policy": not passed,
            }
            for gate in SCIENTIFIC_GATES
        ]
        if gates
        else []
    )
    return record


def _verdict_for(record: dict, mode: str | None, authority: str | None) -> ScientificAuthority:
    """Exactly what the production wiring computes, through the same two
    public helpers — so a drift in either is visible here."""
    return ScientificAuthority.from_context(
        healthgate_mode=mode,
        declared_result_authority=authority,
        formal_validity=formal_validity_of(record, config_path=BLOCKING),
    )


class TestTheMatrix:
    @pytest.mark.parametrize(
        ("mode", "authority", "passed", "gates", "authoritative", "basis"),
        [
            ("blocking", "scientific", True, True, True, "blocking_scientific_formal_valid"),
            ("blocking", "scientific", False, True, False, "gate_invalidated"),
            ("blocking", "scientific", True, False, False, "formal_validity_unknown"),
            ("blocking", "diagnostic", True, True, False, "declared_diagnostic"),
            ("blocking", "diagnostic", False, True, False, "declared_diagnostic"),
            ("observe_only", "diagnostic", True, True, False, "declared_diagnostic"),
            ("observe_only", "diagnostic", False, True, False, "declared_diagnostic"),
        ],
    )
    def test_a_formal_record_gets_the_right_verdict(
        self, mode, authority, passed, gates, authoritative, basis
    ):
        verdict = _verdict_for(_record(passed=passed, gates=gates), mode, authority)
        assert verdict.authoritative is authoritative
        assert verdict.primary_basis == basis

    def test_validity_comes_from_this_record_not_from_a_trial(self):
        """MUTATION TARGET: sourcing validity from the trial winner.

        A failing formal record must stay invalid even when a perfect
        trial exists — they are different questions.
        """
        failing_formal = _record(passed=False)
        assert formal_validity_of(failing_formal, config_path=BLOCKING) == "invalid"
        assert not _verdict_for(failing_formal, "blocking", "scientific").authoritative


class TestTheProductionWiring:
    """Reachability: the block must be on the real record path, formal
    only, and built from `from_context` rather than assembled locally."""

    SRC = None

    @classmethod
    def setup_class(cls):
        from pathlib import Path

        cls.SRC = (
            Path(__file__).resolve().parents[4]
            / "nodes"
            / "ml_hyperparameter_tune_agent"
            / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")

    def test_the_verdict_is_attached_to_formal_records_only(self):
        """MUTATION TARGET: deleting the guard, or inverting it."""
        assert "if not trial_config.is_trial:" in self.SRC
        assert (
            'final_record["scientific_authority"] = ScientificAuthority.from_context(' in self.SRC
        )

    def test_the_exit_path_never_assembles_the_conclusions_itself(self):
        """MUTATION TARGET: hand-writing a verdict.

        `authoritative`, `primary_basis` and `blocking_reasons` are
        computed by D-C2a. A literal assignment anywhere in the tuner
        would be a second, divergent authority.
        """
        for field in ('"authoritative"', '"primary_basis"', '"blocking_reasons"'):
            assert f"final_record[{field}]" not in self.SRC

    def test_validity_is_sourced_from_the_shared_helper(self):
        """MUTATION TARGET: re-deriving validity from gate ids, actions,
        suffixes or filenames instead of the shared role-aware path."""
        assert "formal_validity=formal_validity_of(" in self.SRC


class TestPersistenceKeepsEveryReason:
    def test_all_blockers_survive_the_json_round_trip(self):
        """A diagnostic run whose formal record ALSO failed its gates keeps
        both facts. `primary_basis` is `declared_diagnostic`, but the gate
        failure is a diagnostic fact that must not be dropped."""
        verdict = _verdict_for(_record(passed=False), "blocking", "diagnostic")

        restored = json.loads(json.dumps(verdict.model_dump()))

        assert restored["primary_basis"] == "declared_diagnostic"
        assert restored["blocking_reasons"] == ["declared_diagnostic", "gate_invalidated"]
        assert restored["authoritative"] is False
        assert restored["enters_incumbent_selection"] is False
        assert restored["enters_scientific_aggregation"] is False

    def test_the_facts_survive_too_so_the_verdict_is_recomputable(self):
        dumped = _verdict_for(_record(), "blocking", "scientific").model_dump()
        assert dumped["healthgate_mode"] == "blocking"
        assert dumped["declared_result_authority"] == "scientific"
        assert dumped["formal_validity"] == "valid"


class TestNewRunsCannotProduceAnUndeclaredVerdict:
    def test_legacy_authority_unknown_is_not_reachable_from_a_declared_run(self):
        """D-C1b refuses an undeclared launch, so a NEW record cannot carry
        this reason. It exists for historical reconstruction, not as a
        fallback for new records."""
        for mode in ("blocking", "observe_only"):
            for authority in ("scientific", "diagnostic"):
                verdict = _verdict_for(_record(), mode, authority)
                assert "legacy_authority_unknown" not in verdict.blocking_reasons


class TestTheTwoValidityVocabulariesAgree:
    def test_the_classifier_enum_and_the_authority_literal_are_the_same_set(self):
        """`formal_validity_of` returns the classifier enum's values and
        `ScientificAuthority` accepts a Literal. They are declared in two
        modules, so a change to either must be caught here rather than at
        a call site."""
        from core.scientific_authority import FormalValidity
        from execute_tools.health_checks.schemas import CandidateHealthValidity

        assert {m.value for m in CandidateHealthValidity} == set(FormalValidity.__args__)  # type: ignore[attr-defined]


class TestNoFormalProducedMeansNoVerdict:
    """The matrix's last row: an iteration that produced no formal record
    must not carry a fabricated authority block.

    A verdict invented where no formal round ran would be worse than a
    missing one — it would look like evidence.
    """

    def test_a_no_records_manifest_has_no_authority_block(self, tmp_path):
        from sdsc_submission_scripts.run_one_iteration import write_manifest

        manifest = write_manifest(iter_dir=str(tmp_path), run_name="r", results=[])

        assert manifest["status"] == "no_records"
        assert "scientific_authority" not in manifest

    def test_a_failed_manifest_has_no_authority_block(self, tmp_path):
        from sdsc_submission_scripts.run_one_iteration import write_manifest

        manifest = write_manifest(iter_dir=str(tmp_path), run_name="r", results=[], crashed=True)

        assert manifest["status"] == "failed"
        assert "scientific_authority" not in manifest

    def test_those_branches_still_record_the_declaration_as_null(self, tmp_path):
        """D-C1a's rule, re-asserted here because it is what makes the
        absence above readable: `null` says "no tuner output", which is
        different from "authority was refused"."""
        from sdsc_submission_scripts.run_one_iteration import write_manifest

        manifest = write_manifest(iter_dir=str(tmp_path), run_name="r", results=[])

        assert manifest["healthgate_mode"] is None
        assert manifest["result_authority"] is None


class TestThePersistedVerdictIsTamperEvident:
    """The record layer holds a plain dict, so nothing can stop a later
    writer mutating it. What CAN be guaranteed is that tampering is
    detectable: the facts are persisted alongside the conclusions, so the
    verdict is recomputable from its own record.
    """

    def test_the_persisted_conclusions_match_a_recomputation_from_its_facts(self):
        persisted = _verdict_for(_record(passed=False), "blocking", "diagnostic").model_dump()

        recomputed = ScientificAuthority.from_context(
            healthgate_mode=persisted["healthgate_mode"],
            declared_result_authority=persisted["declared_result_authority"],
            formal_validity=persisted["formal_validity"],
        ).model_dump()

        assert persisted == recomputed

    def test_a_tampered_conclusion_no_longer_matches_its_facts(self):
        """MUTATION TARGET, in the data rather than the code: flipping
        `authoritative` in a persisted record is detectable precisely
        because the facts travel with it."""
        persisted = _verdict_for(_record(passed=False), "blocking", "diagnostic").model_dump()
        persisted["authoritative"] = True

        recomputed = ScientificAuthority.from_context(
            healthgate_mode=persisted["healthgate_mode"],
            declared_result_authority=persisted["declared_result_authority"],
            formal_validity=persisted["formal_validity"],
        )

        assert recomputed.authoritative is False
        assert persisted["authoritative"] != recomputed.authoritative

    def test_the_tuner_never_writes_into_the_persisted_block(self):
        """Structural: the verdict is assigned once, whole. A later
        `final_record["scientific_authority"][...] = ...` would be a second
        authority editing the first."""
        # Read the source directly rather than reaching into another
        # class's `setup_class` attribute — that would make this test
        # depend on collection order, which is how a guard silently
        # becomes a no-op against `None`.
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[4]
            / "nodes"
            / "ml_hyperparameter_tune_agent"
            / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")
        assert 'final_record["scientific_authority"][' not in src
