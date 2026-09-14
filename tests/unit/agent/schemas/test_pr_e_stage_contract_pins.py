"""V21 PR E — E1: pin the stage schema contracts BEFORE any field is added.

**Why this module exists, and why it was written first.** D1 (and B1 before
it) established that a parity claim written *after* a change cannot
distinguish "unchanged" from "changed, and the expectations were written to
match the new behaviour". E2 adds ``candidate_id`` to five schemas and E3
adds two measurement fields to ``ValidatorOutput``; this module pins the
before-state so each of those additions is a deliberate, visible edit to a
test that names the fact it changes.

**Every expected key set below is a hardcoded literal**, transcribed from
the schemas at `aace4abb` — never read back from ``model_fields`` of the
class under test (CLAUDE.md: a schema compared with itself passes for any
schema).

Churn note (design §E1.6, invoked explicitly): ``HyperparamTuningInput``
(68 fields) and ``ExperimentRecord`` (53 fields) are shared surfaces that
grow for reasons unrelated to PR E, so they are pinned on the
**funnel-relevant facts only** — presence/absence of the exact fields PR E
touches or must not touch — not on their full key sets. The three
proposal-chain schemas PR E owns hops through are pinned exactly.

Design doc: ``docs/design/v21_priorities/pr_e_proposal_scale_funnel.md``
Commit E1.

**Step 04a (2026-08-13)** added ``model_io_contract`` to
``ImplementorOutput`` and ``ValidatorInput`` — the normalized Model-I/O
transport — and ``hardware_context`` / ``vram_budget_gb`` to
``ImplementorInput``, the OD-S4-1 capacity authority (mirroring the fields
``ProposalInput`` already carries). The pins below were edited in the SAME commit as the field, which
is the discipline this module exists to enforce: the guard fired, and the
expectation was updated deliberately rather than the guard relaxed. See
``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §16 C2.
"""

from __future__ import annotations

import typing

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningInput
from agent.schemas.implementor import ImplementorInput, ImplementorOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.validator import ValidatorInput, ValidatorOutput

#: The five hop schemas of the candidate_id transport (E2) — plus the two
#: measurement surfaces (E3). Transcribed by hand from source.
PROPOSAL_OUTPUT_KEYS = {
    "candidate_id",  # V21 PR E2 — deliberate addition, this pin forced it
    "baseline_config",
    "custom_loss_spec",
    "expert_advice",
    "falsifiable_prediction",
    "inherited_components",
    "mathematical_definition",
    "memo_consistency_notes",
    "model_description",
    "model_name",
    "motivation",
    "output_type",
    "parameter_count_estimate",
    "preflight_estimated_minutes",
    "preflight_factor",
    "proposed_discoveries",
    "proposed_vocab_candidates",
    "proposed_vocab_links",
}

IMPLEMENTOR_INPUT_KEYS = {
    "candidate_id",  # V21 PR E2 — deliberate addition, this pin forced it
    # P0 / 01A3b — the composed task projection now enters through
    # ImplementorInput construction instead of a post-validation assignment.
    "task_composition_ref",
    "hardware_context",  # Step 04a / OD-S4-1 — deliberate, this pin forced it
    "vram_budget_gb",  # Step 04a / OD-S4-1 — deliberate, this pin forced it
    # Step 12 / PR-12a C7-4 (D-12a-9) — the operator-ratified additive carrier
    # for task-owned implementor science. Deliberate, and this pin forced the
    # acknowledgement: the field landed in C7-4 and the pin caught it in the
    # broader run, exactly as its docstring promises.
    "implementor_blocks",
    "model_name",
    "output_type",
    "model_description",
    "mathematical_definition",
    "baseline_config",
    "task_description",
    "forward_contract",
    "plugin_dir",
    "test_dir",
    "loss_dir",
    "custom_loss_spec",
    "max_retries",
    "reference_code",
    "expert_advice",
    "human_advice",
    "previous_validation_failure",
    "storage",
}

IMPLEMENTOR_OUTPUT_KEYS = {
    "candidate_id",  # V21 PR E2 — deliberate addition, this pin forced it
    "model_io_contract",  # Step 04a — deliberate addition, this pin forced it
    "baseline_config_adjustments",
    "capability_metadata",
    "config_fields",
    "description_file_path",
    "loss_provenance",
    "loss_capability_metadata",
    "mathematical_definition",
    "model_description",
    "model_file_path",
    "model_type",
    "test_file_path",
}

VALIDATOR_INPUT_KEYS = {
    "candidate_id",  # V21 PR E2 — deliberate addition, this pin forced it
    "model_io_contract",  # Step 04a — deliberate addition, this pin forced it
    "config_fields",
    "description_file_path",
    "expert_advice",
    "human_advice",
    "inherited_components",
    "llm_model_id",
    "llm_provider",
    "mathematical_definition",
    "model_description",
    "model_file_path",
    "model_type",
    "storage",
    "test_file_path",
}

VALIDATOR_OUTPUT_KEYS = {
    "candidate_id",  # V21 PR E2 — deliberate addition, this pin forced it
    "realized_total_parameter_count",  # V21 PR E3 — O-E-6 FINAL
    "realized_trainable_parameter_count",  # V21 PR E3 — O-E-6 FINAL
    "config_fields_valid",
    "description_valid",
    "error_message",
    "forbidden_patterns_check_passed",
    "gradient_check_passed",
    "inheritance_check_notes",
    "inheritance_check_passed",
    "inheritance_deviation_notes",
    "instantiation_passed",
    "llm_review_implementation_issues",
    "llm_review_notes",
    "llm_review_passed",
    "llm_review_spec_alignment",
    "llm_review_trainability_concerns",
    "model_type",
    "output_type_valid",
    "passed",
    "plugin_registered",
    "spec_deviation_notes",
    "test_output",
    "tests_passed",
    "unverified_inherited_components",
}


class TestExactKeySets:
    """E2/E3 must edit these expectations in the same commit as the field.

    A key-set drift in either direction fails: a silently added field is
    an unpinned downstream-visible fact; a silently removed one breaks a
    documented hop.
    """

    def test_proposal_output(self):
        assert set(ProposalOutput.model_fields) == PROPOSAL_OUTPUT_KEYS

    def test_implementor_input(self):
        assert set(ImplementorInput.model_fields) == IMPLEMENTOR_INPUT_KEYS

    def test_implementor_output(self):
        assert set(ImplementorOutput.model_fields) == IMPLEMENTOR_OUTPUT_KEYS

    def test_validator_input(self):
        assert set(ValidatorInput.model_fields) == VALIDATOR_INPUT_KEYS

    def test_validator_output(self):
        assert set(ValidatorOutput.model_fields) == VALIDATOR_OUTPUT_KEYS


class TestTheFactsE2Changed:
    """E1 pinned candidate_id absent everywhere; E2 added it — deliberately —
    to exactly the transport surfaces and nowhere else."""

    def test_candidate_id_present_on_every_hop_schema(self):
        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

        for model in (
            ProposalOutput,
            ImplementorInput,
            ImplementorOutput,
            ValidatorInput,
            ValidatorOutput,
            HyperparamTuningInput,
            HyperparamTuningOutput,
            ExperimentRecord,
        ):
            field = model.model_fields.get("candidate_id")
            assert field is not None, f"{model.__name__} lost candidate_id"
            assert field.default is None, (
                f"{model.__name__}.candidate_id default must stay None — a "
                "non-None default would synthesise identity (O-E-4)"
            )


class TestTheFactsE3Changed:
    """E1 pinned ValidatorOutput as measuring nothing; E3 added exactly the
    two O-E-6 counts — and nothing else numeric."""

    def test_the_only_numeric_fields_are_the_two_measurements(self):
        numeric = []
        for name, field in ValidatorOutput.model_fields.items():
            args = typing.get_args(field.annotation) or (field.annotation,)
            if any(a in (int, float) for a in args):
                numeric.append(name)
        assert sorted(numeric) == [
            "realized_total_parameter_count",
            "realized_trainable_parameter_count",
        ], "a numeric field beyond the two O-E-6 measurements appeared unpinned"

    def test_both_measurement_fields_default_none(self):
        for name in (
            "realized_total_parameter_count",
            "realized_trainable_parameter_count",
        ):
            field = ValidatorOutput.model_fields[name]
            assert field.default is None, (
                f"{name} must default None — a numeric default would turn "
                "measurement absence into a fake measurement (§E.3d.4)"
            )


class TestMeasurementOwnershipFacts:
    """O-E-3: measurements live with their native owners — and only there."""

    def test_parameter_count_estimate_lives_on_proposal_only(self):
        assert "parameter_count_estimate" in ProposalOutput.model_fields
        for model in (
            ImplementorInput,
            ImplementorOutput,
            ValidatorInput,
            ValidatorOutput,
            HyperparamTuningInput,
            ExperimentRecord,
        ):
            assert "parameter_count_estimate" not in model.model_fields, (
                f"{model.__name__} carries the proposal's measurement — "
                "O-E-3 forbids copying a measurement past its native owner"
            )

    def test_trained_count_lives_on_the_record(self):
        """ExperimentRecord.model_params — the trained-stage native
        measurement (TRAINABLE-only semantics, frozen by O-E-6)."""
        assert "model_params" in ExperimentRecord.model_fields

    def test_no_stored_stop_stage_anywhere(self):
        """O-E-2: stopped_at_stage is DERIVED ON READ, never persisted."""
        for model in (
            ProposalOutput,
            ImplementorOutput,
            ValidatorOutput,
            HyperparamTuningInput,
            ExperimentRecord,
        ):
            assert "stopped_at_stage" not in model.model_fields
