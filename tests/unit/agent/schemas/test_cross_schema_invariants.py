"""Rules the system relies on that live in no single schema.

The schema suite was written per-field-as-declared: one test per field,
asserting what the field's own `Field(...)` already says. That shape
cannot express the rules that actually break runs, because those rules
span models -- the same concept declared in four places with four
different constraints, or a default in one model that only matters
because another model consumes it.

A consolidation audit (2026-08-02) found ten such divergences and eleven
production defaults pinned by nothing. This file covers the ones where
the authoritative contract is established by production behaviour rather
than by guesswork; the rest are recorded in the PR description as open
questions.

Each test names the concept, not the field, and asserts across every
model that declares it. When a new model gains the same concept, it
belongs in the list here.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    HyperparamTuningInput,
    HyperparamTuningOutput,
    TrialConfig,
)
from agent.schemas.proposal import ProposalInput
from agent.schemas.score_table import PerFileRow
from execute_tools.dataset_config import NUM_FILES

_INPUT = {"model_type": "punet", "run_name": "r", "workspace": "/tmp/w"}


def _trial_config(**overrides):
    """A minimally valid TrialConfig; overrides drive the field under test."""
    base = {
        "is_trial": True,
        "mode": "trial",
        "train_sampling_seed": 42,
        "eval_sampling_seed": 42,
        "train_base_seed": 42,
    }
    return TrialConfig(**{**base, **overrides})


class TestTrialPortionMeansTheSameThingEverywhere:
    """`trial_portion` is the fraction of each file used for training.

    Three of the four models that declare it require `ge=0.01`; the
    intake schema alone accepted `ge=0.0`. Zero is not a smaller trial,
    it is *no training data*, and nothing in the codebase treats 0.0 as a
    sentinel -- `grep` finds no comparison against it anywhere in core/,
    nodes/, execute_tools/ or workflows/. So the intake bound was the
    outlier, not the contract.

    The divergence mattered because intake is the only one an operator
    types into: a run configured with `--trial_portion 0` passed intake
    and was rejected later by the plan schema, mid-run.
    """

    #: Every model that declares the concept, with a constructor.
    DECLARERS: ClassVar[list] = [
        ("HyperparamTuningInput", lambda v: HyperparamTuningInput(**_INPUT, trial_portion=v)),
        ("ExperimentPlan", lambda v: ExperimentPlan(trial_portion=v)),
        ("TrialConfig", lambda v: _trial_config(trial_portion=v)),
        ("ProposalInput", None),  # constructed below; needs a full interpretation
    ]

    @pytest.mark.parametrize("name,build", [(n, b) for n, b in DECLARERS if b])
    def test_zero_training_data_is_rejected_by_every_layer(self, name, build):
        with pytest.raises(ValidationError):
            build(0.0)

    @pytest.mark.parametrize("name,build", [(n, b) for n, b in DECLARERS if b])
    def test_the_smallest_legal_trial_is_accepted_by_every_layer(self, name, build):
        assert build(0.01) is not None

    def test_the_proposal_schema_agrees(self):
        """Declared separately in proposal.py with its own docstring
        saying it mirrors the tuner input -- so it must actually mirror
        it."""
        field = ProposalInput.model_fields["trial_portion"]
        bounds = {type(m).__name__: getattr(m, "ge", None) for m in field.metadata}
        assert 0.01 in bounds.values()


class TestAttemptBudgetsCannotRecordAnImpossibleRun:
    """The output fields are documented as "Echo of the input".

    An echo that can hold values the original forbids is not an echo. All
    three intake fields require `ge=1`; the output copies had no bound,
    so a persisted run record could claim `attempts_per_round=0` -- a
    round that executed attempts while reporting it was allowed none.
    Anything reading that record to reconstruct the budget is then
    reading a number that cannot be true.
    """

    FIELDS = ("attempts_per_round", "attempts_per_formal_round", "max_fail_rounds")

    @pytest.mark.parametrize("field", FIELDS)
    def test_intake_rejects_zero(self, field):
        with pytest.raises(ValidationError):
            HyperparamTuningInput(**_INPUT, **{field: 0})

    @pytest.mark.parametrize("field", FIELDS)
    def test_the_persisted_echo_rejects_zero_too(self, field):
        with pytest.raises(ValidationError):
            HyperparamTuningOutput(
                run_name="r",
                model_type="punet",
                file_index=6,
                status="completed",
                completed_rounds=1,
                total_attempts=1,
                started_at="2026-08-02T00:00:00",
                finished_at="2026-08-02T00:00:01",
                **{field: 0},
            )

    @pytest.mark.parametrize("field", FIELDS)
    def test_the_two_layers_share_a_default(self, field):
        """A divergent default would make the echo silently wrong for
        every run that did not set the field explicitly."""
        assert (
            HyperparamTuningInput.model_fields[field].default
            == HyperparamTuningOutput.model_fields[field].default
        )


class TestFileIndexStaysInsideTheDataset:
    """`file_index` selects a validation file.

    `PerFileRow` bounds it correctly at `le=NUM_FILES-1`. The intake
    schema had `ge=0` and no upper bound, and its description claimed the
    range was "(0-39)" -- there are 20 files. `ExperimentRecord` had no
    bound at all.

    The upper bound is dataset-owned, so it is read from the dataset
    config rather than written as a literal; hardcoding 19 here would put
    a TIDMAD file count into a schema the project is deliberately making
    task-generic.
    """

    def test_the_row_schema_knows_the_dataset_size(self):
        with pytest.raises(ValidationError):
            PerFileRow(file_index=NUM_FILES, gt_score=1.0)

    def test_a_negative_index_is_rejected_at_intake(self):
        with pytest.raises(ValidationError):
            HyperparamTuningInput(**_INPUT, file_index=-1)

    def test_the_intake_description_no_longer_claims_a_wrong_range(self):
        """The description said "(0-39)". An operator reading it would
        configure a file that does not exist."""
        description = HyperparamTuningInput.model_fields["file_index"].description or ""
        assert "0-39" not in description


class TestSeedAlignmentIsActuallyExercised:
    """`train_validation_align=True` requires the two seeds to match.

    The validator existed and was never exercised in either direction:
    every fixture in the schema suite passed both seeds as 42, so the
    aligned case never proved anything and the misaligned case was never
    constructed. A validator no test can distinguish from its own absence
    is not covered.

    It matters because misaligned seeds silently decorrelate the training
    and validation scopes -- the run completes and the score means
    something else.
    """

    def test_aligned_seeds_are_accepted(self):
        cfg = _trial_config(
            train_validation_align=True, train_sampling_seed=7, eval_sampling_seed=7
        )
        assert cfg.train_sampling_seed == cfg.eval_sampling_seed

    def test_misaligned_seeds_are_rejected_when_alignment_is_claimed(self):
        with pytest.raises(ValidationError) as exc:
            _trial_config(train_validation_align=True, train_sampling_seed=7, eval_sampling_seed=8)
        message = str(exc.value)
        assert "train_validation_align" in message
        # The operator needs both values to diagnose it.
        assert "7" in message and "8" in message

    def test_misaligned_seeds_are_fine_when_alignment_is_not_claimed(self):
        """The negative control. Without it, a validator that rejected
        *every* seed pair would still pass the test above."""
        cfg = _trial_config(
            train_validation_align=False, train_sampling_seed=7, eval_sampling_seed=8
        )
        assert cfg.train_sampling_seed != cfg.eval_sampling_seed


class TestAdmissionEnforcementHasOneVocabulary:
    """The posture vocabulary is declared twice.

    `GpuAdmissionPolicy.enforcement` is a Literal; the intake field was a
    bare `str`. A typo therefore passed intake and failed later, inside
    the tuner's attempt loop, where the run has already spent a planning
    call.

    Not the silent disarm it first appears to be -- the inner Literal
    does reject it -- but the failure arrives at the wrong layer, and
    three modules re-declare the default string with nothing keeping them
    in sync.
    """

    def test_intake_rejects_a_typo(self):
        with pytest.raises(ValidationError):
            HyperparamTuningInput(**_INPUT, gpu_admission_enforcement="enfroce")

    @pytest.mark.parametrize("value", ["observe_only", "enforce"])
    def test_intake_accepts_exactly_the_approved_postures(self, value):
        cfg = HyperparamTuningInput(**_INPUT, gpu_admission_enforcement=value)
        assert cfg.gpu_admission_enforcement == value

    def test_the_two_declarations_share_one_vocabulary(self):
        """If either side gains a value the other lacks, a configuration
        becomes acceptable at one layer and impossible at the next."""
        from typing import get_args

        from core.runtime_control.admission import ACCEPTED_ENFORCEMENT, GpuAdmissionPolicy

        inner = set(get_args(GpuAdmissionPolicy.model_fields["enforcement"].annotation))
        outer = set(
            get_args(HyperparamTuningInput.model_fields["gpu_admission_enforcement"].annotation)
        )
        assert inner == outer == set(ACCEPTED_ENFORCEMENT)
