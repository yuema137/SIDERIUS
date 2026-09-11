"""F-SCANE-3 — the validation term reaches the LLM that is told to attribute it.

Historical regression boundary retained after campaign evidence moved to external ownership.

    consequence: No LLM can see the term it is being asked to attribute to
    architecture. A candidate can be shrunk for time spent validating it.

The defect only this file catches
---------------------------------
``execution.run_training`` times the WHOLE training subprocess into
``timing.train_time_s``. ``train_engine_sandbox`` DOES split the 07a
validation pass out (it subtracts ``validation_seconds_total`` from the
training ACTUAL) — but that split reached only the calibration store, because
``validation_seconds`` lives inside ``training_history``, which is
PLANNER-HIDDEN (``agent/prompts.py::_PLANNER_HIDDEN_RECORD_KEYS``). The
planner prompt then rendered ``train=… min`` and instructed *"If the last run
exceeded it, reduce model complexity"*, and the interpreter's Discovery 3 —
whose own comment calls the number an "architectural resource cost" —
rendered the same unsplit figure beside *"consider reducing model or input
size"*.

Three properties, each with its own mutation:

* the RECORD carries the split (delete ``"validation_time_s"`` from the
  ``timing`` dict in ``records.py`` -> ``TestTheRecordCarriesTheSplit`` red);
* the split reaches the planner's INPUT — the ``memory_history`` the tuner
  really hands to ``bridge.plan`` (same mutation ->
  ``test_the_split_reaches_the_memory_history_the_planner_is_given`` red);
* the two LLM-facing renderers state it (revert either render ->
  ``TestThePlannerPromptStatesTheTerm`` /
  ``TestTheTimingDiscoveryStatesTheTerm`` red).

Byte parity is asserted against strings captured in a PRISTINE ``3995400b``
worktree: a record with no split renders exactly as before, and so does an
INCOHERENT split (validation > train, which production cannot produce).

N-4 — what the split MEANS
--------------------------
Making the term visible was necessary; the sentences F-SCANE-3 wrote about it
were false, in four places at once. ``TestTheAttributionClaimIsTrue`` and
``TestOneAuthorityForFourSurfaces`` at the end of this file own that: the
first pins the two corrected claims against hardcoded text, the second fails
when a surface states the split in its own words instead of consuming
``agent.prompt_templates.timing_attribution``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from agent.prompt_templates.timing_attribution import (
    TIMING_ATTRIBUTION_NOTE,
    TIMING_SPLIT_SEMANTICS,
)
from agent.prompts import get_planner_user_prompt
from agent.schemas.hyperparam_tuning import ExperimentPlan
from execute_tools.metric_order import MetricOrder
from nodes.interpretation_helpers import generate_discoveries
from tests.helpers.metric_fixtures import shipped_spec
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

_PREFLIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "step00_preflight_results.json"


@pytest.fixture(scope="module")
def pseudo_run(tmp_path_factory):
    """A REAL tuner iteration over the pseudo executor — the producer."""
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("fscane3")
    try:
        return run_bounded_pseudo_iteration(
            tmp,
            mp,
            preflight_results=json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"],
        )
    finally:
        mp.undo()


class TestTheRecordCarriesTheSplit:
    def test_every_success_record_states_the_validation_seconds_inside_train_time(self, pseudo_run):
        output, _bridge, _sandbox, _ws = pseudo_run
        successes = [r for r in output.all_records if r.status == "success"]
        assert successes, "the pseudo iteration must produce success records"

        for rec in successes:
            history = rec.training_history
            assert history is not None and history.validation_seconds
            assert rec.timing is not None
            assert rec.timing.validation_time_s is not None, (
                "the record's timing block carries no validation term — the "
                "split still reaches only the calibration store"
            )
            # The visible term IS the hidden one, summed. This is the whole
            # transport: `training_history` is planner-hidden, `timing` is not.
            assert rec.timing.validation_time_s == round(sum(history.validation_seconds), 1)
            assert rec.timing.validation_time_s > 0

    def test_a_record_with_no_training_history_states_no_split_rather_than_zero(self, pseudo_run):
        """`None` and `0.0` are different facts. A skip record ran no
        validation pass at all; reporting `0.0` would claim it ran one for
        free."""
        output, _bridge, _sandbox, _ws = pseudo_run
        others = [r for r in output.all_records if r.status != "success"]
        assert others, "the fixture must produce at least one non-success record"
        for rec in others:
            assert rec.training_history is None
            if rec.timing is not None:
                assert rec.timing.validation_time_s is None

    def test_the_split_reaches_the_memory_history_the_planner_is_given(self, pseudo_run):
        """Transport, at the exact boundary the row names.

        This is the argument PRODUCTION passed to the planner, taken off the
        recording bridge — not a dict assembled here. Before the fix the only
        carrier of the validation seconds was `training_history`, which
        `_PLANNER_HIDDEN_RECORD_KEYS` drops before serialization."""
        _output, bridge, _sandbox, _ws = pseudo_run
        plans = [c for c in bridge.calls if c[0] == "plan"]
        assert plans, "no planner call was recorded"

        with_timing = [
            rec
            for call in plans
            for rec in call[1]
            if rec.get("status") == "success" and rec.get("timing") is not None
        ]
        assert with_timing, (
            "no success record with timing ever reached the planner, so this "
            "assertion would be vacuous"
        )
        for rec in with_timing:
            assert "validation_time_s" in rec["timing"]
            assert rec["timing"]["validation_time_s"] is not None

    def test_a_real_record_renders_the_term_while_the_container_stays_hidden(self, pseudo_run):
        """The end of the transport, on a record the REAL tuner produced.

        The fix must lift the TERM out, not the container: the planner prompt
        must state the validation minutes and must still drop the per-epoch
        ``training_history`` payload that `_PLANNER_HIDDEN_RECORD_KEYS` names.

        ONE field is substituted — ``train_time_s``. Pseudo-mode training is a
        stubbed call with essentially zero wall clock, while its
        ``validation_seconds`` are canned values from a different clock, so the
        producer's own pair is incoherent (validation > train) and the renderer
        correctly refuses it. Substituting a realistic training wall time is
        the only way to reach the coherent branch through this harness; every
        other key, including ``validation_time_s`` itself, is the producer's.
        """
        _output, bridge, _sandbox, _ws = pseudo_run
        candidates = [
            rec
            for call in (c for c in bridge.calls if c[0] == "plan")
            for rec in call[1]
            if rec.get("status") == "success" and (rec.get("timing") or {}).get("validation_time_s")
        ]
        assert candidates, "no produced record carried a validation split"

        record = copy.deepcopy(candidates[-1])
        assert "training_history" in record, (
            "the raw history is not on the record here, so 'still hidden' would be vacuous"
        )
        validation_s = record["timing"]["validation_time_s"]
        record["timing"]["train_time_s"] = validation_s * 10

        prompt = get_planner_user_prompt([record], current_round=2, max_rounds=3)
        block = _timing_block(prompt)
        assert f"validation {validation_s / 60:.1f} min of that" in block
        assert "training+overhead" in block
        assert "training_history" not in prompt
        assert "validation_seconds" not in prompt


# ---------------------------------------------------------------------------
# The two LLM-facing renderers
# ---------------------------------------------------------------------------

#: Captured in a PRISTINE `3995400b` worktree before any part of this fix
#: existed. Hardcoded so the byte-parity claim is not read back from the
#: renderer under test.
_PRISTINE_PLANNER_TIMING_BLOCK = (
    "### ⏱  LAST EXPERIMENT TIMING:\n"
    "train=20.0 min, inference=5.0 min, total=25.0 min (segmentation_size=4096).\n"
    "The time budget is a HARD UPPER LIMIT, not a target. If the last "
    "run exceeded it, reduce model complexity. If it was well under, "
    "do NOT scale up just because there is headroom — smaller "
    "experiments are equally valid as long as they test the hypothesis."
)

_PRISTINE_TIMING_DISCOVERY = (
    "punet: 35.0 min/experiment (train=20.0, infer=15.0 min). "
    "High compute cost — consider reducing model or input size."
)


def _planner_record(timing: dict) -> dict:
    return {
        "exp_id": "e1",
        "status": "success",
        "model_type": "punet",
        "params": {"model_config": {"segmentation_size": 4096}},
        "denoising_score": 1.0,
        "timing": timing,
    }


def _timing_block(prompt: str) -> str:
    start = prompt.index("### ⏱")
    return prompt[start : prompt.index("\n\n", start)]


class TestThePlannerPromptStatesTheTerm:
    def test_the_split_is_rendered_with_the_residual_and_the_attribution(self):
        block = _timing_block(
            get_planner_user_prompt(
                [
                    _planner_record(
                        {
                            "train_time_s": 1200.0,
                            "validation_time_s": 180.0,
                            "inference_time_s": 300.0,
                            "scoring_time_s": 10.0,
                        }
                    )
                ],
                current_round=2,
                max_rounds=3,
            )
        )
        assert "validation 3.0 min of that" in block
        assert "training+overhead 17.0 min" in block
        assert TIMING_ATTRIBUTION_NOTE.strip() in block
        # The instruction the row objects to is still present — the fix is to
        # let the model apply it to the right number, not to remove it.
        assert "reduce model complexity" in block

    def test_a_record_without_the_split_renders_the_pristine_bytes(self):
        block = _timing_block(
            get_planner_user_prompt(
                [
                    _planner_record(
                        {
                            "train_time_s": 1200.0,
                            "inference_time_s": 300.0,
                            "scoring_time_s": 10.0,
                        }
                    )
                ],
                current_round=2,
                max_rounds=3,
            )
        )
        assert block == _PRISTINE_PLANNER_TIMING_BLOCK

    def test_an_incoherent_split_is_refused_rather_than_rendered_negative(self):
        """A part cannot exceed its whole. Production cannot produce this
        (the validation pass runs inside the timed subprocess), so it means
        two different clocks — and "training+overhead -2.0 min" at an LLM is
        worse than saying nothing."""
        block = _timing_block(
            get_planner_user_prompt(
                [
                    _planner_record(
                        {
                            "train_time_s": 60.0,
                            "validation_time_s": 180.0,
                            "inference_time_s": 300.0,
                            "scoring_time_s": 10.0,
                        }
                    )
                ],
                current_round=2,
                max_rounds=3,
            )
        )
        assert "training+overhead" not in block
        assert "-" not in block.split("\n")[1].split("—")[0]


class TestTheTimingDiscoveryStatesTheTerm:
    """Discovery 3 is the SAME failure class at a second site: its own header
    calls the figure an "architectural resource cost" and its remedy is
    "reduce the model". Fixing only the planner because the row cites that
    line number would leave the identical instruction standing next to the
    identical unsplit number."""

    @staticmethod
    def _timing_discovery(timing: dict) -> str:
        entries = generate_discoveries(
            prediction_eval=None,
            model_type="punet",
            best_score=1.0,
            inherited_components=[],
            proposed_vocab_links=[],
            timing=timing,
            overall_best_score=1.0,
            order=MetricOrder(shipped_spec()),
        )
        slow = [e for e in entries if e.name == "timing_punet_slow"]
        assert len(slow) == 1, "the timing discovery did not fire"
        return slow[0].description

    def test_the_split_is_stated_when_the_record_carries_it(self):
        desc = self._timing_discovery(
            {
                "train_time_s": 1200.0,
                "validation_time_s": 180.0,
                "inference_time_s": 900.0,
                "scoring_time_s": 10.0,
            }
        )
        assert "incl. validation 3.0" in desc
        assert "training+overhead 17.0" in desc

    def test_a_record_without_the_split_renders_the_pristine_bytes(self):
        assert (
            self._timing_discovery(
                {
                    "train_time_s": 1200.0,
                    "inference_time_s": 900.0,
                    "scoring_time_s": 10.0,
                }
            )
            == _PRISTINE_TIMING_DISCOVERY
        )

    def test_an_incoherent_split_renders_the_pristine_bytes(self):
        assert (
            self._timing_discovery(
                {
                    "train_time_s": 1200.0,
                    "validation_time_s": 5000.0,
                    "inference_time_s": 900.0,
                    "scoring_time_s": 10.0,
                }
            )
            == _PRISTINE_TIMING_DISCOVERY
        )


class TestTheSumIsTheProducersOwnNumber:
    def test_the_helper_sums_the_trainers_own_per_epoch_seconds(self):
        """Driven from the RAW results dict the training subprocess writes,
        through the production validation site (`interpret_training_results`),
        so the number is the trainer's — not one this test invented. The
        expectation is hardcoded arithmetic, never read back."""
        from execute_tools.training_history import interpret_training_results
        from nodes.ml_hyperparameter_tune_agent.records import _validation_time_s

        history = {
            "cadence": "per_epoch",
            "objective_kind": "focal",
            "objective_config_fingerprint": "f" * 64,
            "objective_reduction": "mean",
            "epoch_statistic": "sample_count_weighted_mean_of_batch_criterion",
            "comparability": "established",
            "comparability_reason": None,
            "epochs_planned": 3,
            "epochs_completed": 3,
            "train_objective": [3.0, 2.0, 1.0],
            "validation_objective": [3.1, 2.1, 1.1],
            "validation_requested_samples": 15000,
            "validation_samples": 15000,
            "validation_requested_samples_before_limit": None,
            # The two real TIDMAD per-epoch figures the row quotes, plus one.
            "validation_seconds": [37.99, 29.14, 30.0],
            "observations": {},
        }
        results = interpret_training_results(
            {
                "final_loss": 1.0,
                "loss_history": [3.0, 2.0, 1.0],
                "model_params": 10,
                "training_history": copy.deepcopy(history),
            },
            expected_validation=True,
        )
        assert _validation_time_s(results) == 97.1  # 37.99 + 29.14 + 30.0

    def test_no_history_is_an_absent_split_not_a_zero_one(self):
        from execute_tools.training_history import interpret_training_results
        from nodes.ml_hyperparameter_tune_agent.records import _validation_time_s

        results = interpret_training_results(
            {"final_loss": 1.0, "loss_history": [3.0], "model_params": 10},
            expected_validation=False,
        )
        assert _validation_time_s(results) is None
        assert _validation_time_s(None) is None


# ---------------------------------------------------------------------------
# N-4 — what the split MEANS, and the one place that owns the answer
# ---------------------------------------------------------------------------


class TestTheAttributionClaimIsTrue:
    """The defect only this class catches.

    F-SCANE-3 made the validation term visible and then told the LLM two
    things about it that the code contradicts:

    1. *"Validation time ... does not shrink when the model shrinks."*
       ``train_engine_sandbox._validation_pass`` runs
       ``output_seq = model(input_seq)`` per batch — a forward pass of the
       model under test.
    2. *"the architecture's own cost is ``train_time_s - validation_time_s``".*
       ``train_time_s`` is the PARENT's wall clock around the whole training
       subprocess, while the trainer's own analogue starts at
       ``t_train_start``, set AFTER setup. The residual also carries spawn,
       CUDA init, model/dataset construction and checkpoint save.

    Together, under a hard budget, the planner was told to ignore the one term
    that DOES respond to shrinking the model and to attribute to its own
    design a residual containing cost no design removes — under-pricing large
    candidates and over-pricing small ones.

    **N-4b — this class used to hold a defect in place.** The correction for
    (1) asserted the PRESENCE of *"a forward pass of the model under test over
    a FIXED evaluation scope, so it shrinks with a smaller model but not with
    fewer epochs or less training data"*, and both of those clauses are false:

    * the evaluation scope is the PLANNER's lever in a trial round —
      ``policy._resolve_sample_set_cfg``'s trial branch returns
      ``"eval_portion": plan.eval_portion``, which reaches
      ``build_eval_scope(portion=…)``, the attempt's ``eval_sample_set``, and
      the trainer as ``--eval_sample_set_json``; ``agent/prompts.py`` asks the
      model for the value and tells it to increase it, and on the campaign
      path it is ``AGENT_CONTROLLED``;
    * it is paid PER EPOCH — ``_validation_pass`` is called inside
      ``for ep in range(train_cfg.epochs)`` and ``records._validation_time_s``
      sums ``validation_seconds``. (``max_epochs=1`` on the real path today,
      so this clause has no range until D-BUD-6's ``trial_max_epochs: 2``
      lands; the trial-scope clause carries the finding alone.)

    A guard in a class named *the attribution claim is true*, asserting the
    false substring is present, goes RED on the repair. The assertions below
    now pin the CORRECTED wording, so they fail on the false sentence instead.

    Expectations here are HARDCODED, never read back from the module: a test
    that asserts ``NOTE == NOTE`` passes for any sentence, including the false
    one this class exists to keep out.
    """

    def test_the_note_does_not_claim_validation_is_model_independent(self):
        assert "does not shrink when the model shrinks" not in TIMING_SPLIT_SEMANTICS
        assert "fixed cost of the evaluation pass" not in TIMING_SPLIT_SEMANTICS
        assert (
            "`validation_time_s` is that pass, summed over epochs: once per epoch "
            "the model under test runs a forward pass over the round's EVALUATION "
            "scope. It therefore scales with the model, with the number of epochs, "
            "and with the size of that evaluation scope" in TIMING_SPLIT_SEMANTICS
        )

    def test_the_note_states_mechanics_and_never_who_owns_the_evaluation_scope(self):
        """The clause that carries the finding on its own — and the reason the
        repair states MECHANICS without asserting OWNERSHIP.

        Calling the evaluation scope FIXED, immediately before "reduce model
        complexity", steers an overrunning candidate toward capacity reduction.
        But naming the planner as the scope's owner is equally wrong in the
        other direction: SIDERIUS runs in two modes, and in the LOCKED mode a
        typed ``--eval_portion`` becomes a ``plan_overrides`` entry that
        overwrites the plan value before the resolver reads it (issue #372).
        The Gold campaign is locked. So one authority rendered for both modes
        must state what the cost RESPONDS TO and decline to say who sets it.
        """
        for banned in (
            "FIXED evaluation scope",  # false in unlocked mode
            "a lever you set",  # false in locked mode
            "the plan's own value",
            "you set",
            "the planner sets",
        ):
            assert banned not in TIMING_SPLIT_SEMANTICS, (
                f"the shared sentence asserts who owns the evaluation scope "
                f"({banned!r}); that is true in at most one operating mode"
            )
        assert (
            "Whether any of these is yours to set in THIS run is decided by "
            "the run's configuration, not by this note." in TIMING_SPLIT_SEMANTICS
        )
        # The levers validation genuinely does NOT respond to — named, so the
        # repair does not swing to "everything shrinks it".
        assert (
            "What it does NOT respond to is `trial_portion` / `train_portion` "
            "or the number of optimizer steps: those size the TRAINING scope "
            "only." in TIMING_SPLIT_SEMANTICS
        )

    def test_the_trial_evaluation_scope_is_the_plans_value_UNLESS_frozen(self):
        """Both halves of the mode distinction, driven through production.

        UNLOCKED: the trial branch sources ``eval_portion`` from the plan, so
        it really is an agent lever and a note calling it FIXED would be false.

        LOCKED: a typed ``--eval_portion`` becomes a ``frozen_portion_overrides``
        entry, and ``_apply_plan_overrides`` merges it OVER the plan
        (``plan.model_dump(by_alias=True) | overrides`` — the right operand of
        a dict union wins), so the frozen value reaches the resolver instead.
        The Gold campaign is locked this way.

        Stating only the first half is what made the previous wording false for
        the campaign that actually ships. Issue #372.
        """
        from nodes.ml_hyperparameter_tune_agent.policy import _resolve_sample_set_cfg

        class _Plan:
            trial_strategy = "snapshot"
            trial_portion = 0.05
            train_portion = 0.1
            eval_strategy = "snapshot"
            eval_portion = 0.37  # a value only the plan could have supplied

        class _Input:
            formal_strategy = "snapshot"
            formal_portion = 1.0
            formal_train_portion = 1.0
            formal_eval_portion = 1.0

        trial = _resolve_sample_set_cfg("trial", _Input(), _Plan())  # type: ignore[arg-type]
        assert trial["eval_portion"] == 0.37, (
            "the trial round no longer takes its evaluation scope from the plan"
        )
        # ...and the formal round genuinely does fix it, which is the other
        # half of what the sentence promises.
        formal = _resolve_sample_set_cfg("formal", _Input(), _Plan())  # type: ignore[arg-type]
        assert formal["eval_portion"] == 1.0
        assert formal["eval_strategy"] == "snapshot"

        # LOCKED mode: a frozen portion overrides the plan before the resolver
        # sees it, so the same trial round no longer carries the plan's value.
        from nodes.ml_hyperparameter_tune_agent.policy import _apply_plan_overrides

        plan = ExperimentPlan(
            trial_strategy="snapshot",
            trial_portion=0.05,
            train_portion=0.1,
            eval_strategy="snapshot",
            eval_portion=0.37,
        )
        locked = _apply_plan_overrides(plan, {"eval_portion": 0.01})
        assert locked.eval_portion == 0.01, (
            "a typed campaign portion no longer overrides the plan — the note "
            "must not then describe the evaluation scope as frozen"
        )
        assert _resolve_sample_set_cfg("trial", _Input(), locked)["eval_portion"] == 0.01

    def test_the_note_does_not_call_the_residual_the_architectures_cost(self):
        assert (
            "The remainder (`train_time_s - validation_time_s`) is NOT the "
            "architecture's own cost either" in TIMING_SPLIT_SEMANTICS
        )
        assert (
            "it still contains process start, CUDA init, model and dataset "
            "construction and checkpoint save" in TIMING_SPLIT_SEMANTICS
        )
        assert "UPPER BOUND" in TIMING_SPLIT_SEMANTICS
        # The instruction that made the false claim actionable.
        assert "Attribute only the architecture cost to your design" not in TIMING_SPLIT_SEMANTICS


class TestOneAuthorityForFourSurfaces:
    """Four copies of a sentence are four chances to drift, and F-SCANE-3
    shipped four copies that were wrong in the same two ways.

    These assertions fail when a surface re-inlines its own wording instead of
    consuming ``agent.prompt_templates.timing_attribution`` — which is the
    state that let one correction miss three sites.
    """

    #: Every surface that states what the split means.
    _CONSUMERS = (
        "src/agent/prompts.py",
        "src/nodes/interpretation_helpers.py",
        "src/agent/schemas/hyperparam_tuning.py",
        "src/agent/schemas/interpretation.py",
    )
    _REPO = Path(__file__).resolve().parents[4]

    def test_no_production_surface_still_calls_the_residual_an_architecture_cost(self):
        offenders = {
            rel: line
            for rel in self._CONSUMERS
            for line in (self._REPO / rel).read_text(encoding="utf-8").splitlines()
            if "architecture cost" in line or "architecture's own cost is" in line
        }
        assert offenders == {}, (
            f"a surface still names the residual as the architecture's cost: {offenders}"
        )

    def test_every_surface_consumes_the_authority(self):
        missing = [
            rel
            for rel in self._CONSUMERS
            if "timing_attribution" not in (self._REPO / rel).read_text(encoding="utf-8")
        ]
        assert missing == [], f"these surfaces state the split without the authority: {missing}"

    def test_the_two_schema_descriptions_carry_the_authority_verbatim(self):
        """A field description is read by pyright, by an operator AND by any
        model shown the record schema. Paraphrasing it is how the two halves
        of one claim start disagreeing."""
        from agent.schemas.hyperparam_tuning import ExperimentTiming
        from agent.schemas.interpretation import ModelRunSummary

        for model, field in ((ExperimentTiming, "train_time_s"), (ModelRunSummary, "best_timing")):
            description = model.model_fields[field].description or ""
            assert TIMING_SPLIT_SEMANTICS in description, (
                f"{model.__name__}.{field} states the split in its own words"
            )

    def test_the_planner_note_is_the_authority_and_not_a_copy(self):
        block = _timing_block(
            get_planner_user_prompt(
                [
                    _planner_record(
                        {
                            "train_time_s": 1200.0,
                            "validation_time_s": 180.0,
                            "inference_time_s": 300.0,
                            "scoring_time_s": 10.0,
                        }
                    )
                ],
                current_round=2,
                max_rounds=3,
            )
        )
        assert TIMING_ATTRIBUTION_NOTE.strip() in block


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
