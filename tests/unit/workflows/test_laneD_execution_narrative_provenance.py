"""Lane D / F15 — downstream narrative must derive from RESOLVED execution.

**The defect.** A research-memory reflection described a run as *"using
kernel_size=15 with custom Smooth L1 beta=0.5"* when the task-declared
objective had actually executed and ``beta`` was null. Nothing was corrupt:
``plan.hypothesis`` is free prose the planner authors, and the framework then
overrules parts of the plan — operator overrides, the round-mode chain, the
task-declared objective, partial-scope normalization, the epoch bound, the
forced model type — without ever revisiting the prose. The reflector was handed
that stale prose under the heading "Original Hypothesis" and nothing else
describing the configuration, so it narrated a proposal as though it had run.

The rule, and the whole point of this module::

    DOWNSTREAM NARRATIVE DESCRIBING A RUN MUST DERIVE FROM
    RESOLVED EXECUTION PROVENANCE, NOT FROM STALE PROPOSAL ASSUMPTIONS.

**Why these tests can go RED.** The planted disagreement is REAL, not
synthetic: DAVIS's shipped manifest declares an exact-L1 objective, and the
planner in the witnessed runs chose ``smooth_l1`` — the same overrule, through
the same production authority (``_apply_declared_objective``), that produced
F15. The positive witness fails if the narrative stops naming the executed
objective. Its indispensable partner is
:class:`TestNoDisagreementEmitsNothing`: a fix that simply printed the
configuration unconditionally would satisfy every positive assertion while
proving nothing about *following* the executed authority, and would move the
prompt bytes of every run that was never overruled. One test asserts the
correction appears when the two disagree; the other asserts it is ABSENT when
they agree. Neither alone is evidence.
"""

from __future__ import annotations

import importlib
import pathlib
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DAVIS = str(REPO_ROOT / "configs" / "task_composition" / "davis.yaml")

#: The prose the planner wrote, in the shape F15 witnessed. It names a loss and
#: a beta that the declared objective is about to overrule.
STALE_PROSE = "Using kernel_size=15 with custom Smooth L1 beta=0.5 for sharper edges."


def _davis_objective_ref() -> Any:
    from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings

    return build_task_composition_ref(compose_run_task_bindings(DAVIS))


def _metric_spec() -> Any:
    """DAVIS's OWN declared spec — a real lower-is-better metric.

    Taken from the composition rather than hand-built, so this test cannot
    drift away from a spec shape production would refuse.
    """
    from workflows.task_composition import compose_run_task_bindings

    return compose_run_task_bindings(DAVIS).metric.spec


def _planning():
    return importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")


def _plan(**overrides: Any):
    from agent.schemas.hyperparam_tuning import ExperimentPlan

    base: dict[str, Any] = {
        "hypothesis": STALE_PROSE,
        "loss_cfg": {"loss_type": "smooth_l1", "beta": 0.5},
        "train_cfg": {"epochs": 3, "lr": 5e-4},
        "model_cfg": {"model_type": "wavenet", "kernel_size": 15},
    }
    base.update(overrides)
    return ExperimentPlan(**base)


def _resolved_through_production(plan: Any) -> Any:
    """Drive the REAL tracker across the REAL declared-objective authority.

    Deliberately not a hand-built provenance object. A test that constructs the
    expected events and then renders them asserts the renderer against itself
    and would stay green if the production resolution stopped being tracked at
    all.
    """
    from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

    tracker = ResolutionTracker(plan)
    plan = _planning()._apply_declared_objective(plan, _davis_objective_ref())
    tracker.record(plan, "task_declared_objective")
    return plan, tracker.finish(plan)


def _reflector_prompt(hypothesis: str, provenance: Any) -> str:
    from agent.prompts import get_reflector_user_prompt

    return get_reflector_user_prompt(
        "davis_run_001",
        hypothesis,
        {"denoising_score": 0.31, "final_loss": 0.017},
        {"current_loss_type": "custom"},
        execution_provenance=provenance,
    )


# --------------------------------------------------------------- the witness
class TestPlantedDisagreementFollowsTheExecutedAuthority:
    """A REAL overrule is planted; the narrative surface must follow execution."""

    def test_the_production_authority_actually_overrules_the_prose(self):
        """Precondition. If DAVIS ever stopped overruling `smooth_l1`, every
        assertion below would pass vacuously — so the disagreement is proven to
        exist before anything is asserted about how it is narrated."""
        plan, provenance = _resolved_through_production(_plan())
        assert plan.loss_cfg["loss_type"] == "custom"
        assert plan.loss_cfg["loss_name"] == "davis_exact_l1"
        assert provenance.diverged, "no disagreement was planted — the witness is vacuous"

    def test_the_narrative_names_the_executed_objective(self):
        """THE witness. Pre-fix the reflector never saw `davis_exact_l1` at
        all: the prompt carried the stale prose plus a `current_loss_type`
        ranking key. It now carries the executed identity."""
        _, provenance = _resolved_through_production(_plan())
        prompt = _reflector_prompt(STALE_PROSE, provenance)
        assert "davis_exact_l1" in prompt

    def test_the_stale_value_is_never_presented_as_what_ran(self):
        """The proposed value is not censored — it is DEMOTED. Every surviving
        occurrence must sit inside the proposal label or on the line that
        explicitly renders it as overruled; an unqualified `smooth_l1` is the
        F15 sentence returning."""
        _, provenance = _resolved_through_production(_plan())
        prompt = _reflector_prompt(STALE_PROSE, provenance)
        carrying = [ln for ln in prompt.splitlines() if "smooth_l1" in ln]
        assert carrying, "the overruled value vanished entirely — this test would be vacuous"
        for line in carrying:
            assert "proposed" in line or "PROPOSAL" in line, (
                f"`smooth_l1` appears un-demoted, as if it had run: {line!r}"
            )

    def test_the_hypothesis_is_relabelled_as_a_proposal(self):
        """The heading itself lied. "Original Hypothesis" reads as a
        description of the experiment; a reflector told only the corrected
        values still trusts that heading."""
        _, provenance = _resolved_through_production(_plan())
        prompt = _reflector_prompt(STALE_PROSE, provenance)
        assert "PROPOSAL" in prompt
        assert "RESOLVED EXECUTION AUTHORITY" in prompt

    def test_the_block_states_which_side_governs(self):
        """Values alone let a model average the two accounts. The block must
        say the executed configuration is the fact."""
        _, provenance = _resolved_through_production(_plan())
        prompt = _reflector_prompt(STALE_PROSE, provenance)
        assert "EXECUTED" in prompt
        assert "governs" in prompt


# ------------------------------------------- the discriminator (must be RED-able)
class TestNoDisagreementEmitsNothing:
    """Without this, the witness above proves only that text was added.

    A run whose authored plan survived resolution intact has an accurate
    hypothesis and needs no correction. Emitting one anyway would move the
    prompt bytes of essentially every historical run and would mean the block
    is unconditional decoration rather than a record of divergence.
    """

    def test_an_unoverruled_plan_produces_no_events(self):
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan()
        tracker = ResolutionTracker(plan)
        # A task that declares no objective is a documented no-op.
        plan = _planning()._apply_declared_objective(plan, None)
        tracker.record(plan, "task_declared_objective")
        assert not tracker.finish(plan).diverged

    def test_no_correction_is_emitted_when_nothing_was_overruled(self):
        """The load-bearing assertion, stated ABSOLUTELY.

        An earlier version of this test compared three calls to the same
        function and asserted they matched. They always match — including when
        the block is emitted unconditionally, because then all three carry it.
        A mutation that made the renderer ignore divergence entirely passed
        that test. Comparing the code to itself proves nothing; the marker's
        ABSENCE is the fact.
        """
        from agent.prompts import get_reflector_user_prompt
        from agent.schemas.execution_provenance import ExecutionProvenance

        args = ("davis_run_001", STALE_PROSE, {"denoising_score": 0.31}, {})
        for provenance in (None, ExecutionProvenance()):
            prompt = get_reflector_user_prompt(*args, execution_provenance=provenance)
            assert "RESOLVED EXECUTION AUTHORITY" not in prompt
            assert "PROPOSAL" not in prompt
            # The legacy heading, byte-exact: an un-overruled run's hypothesis
            # is accurate and must not be demoted.
            assert f"- **Original Hypothesis**: {STALE_PROSE}" in prompt

    def test_the_three_no_divergence_callers_agree(self):
        """Absent, `None` and an empty provenance are the same run shape and
        must not diverge from each other either."""
        from agent.prompts import get_reflector_user_prompt
        from agent.schemas.execution_provenance import ExecutionProvenance

        args = ("davis_run_001", STALE_PROSE, {"denoising_score": 0.31}, {})
        legacy = get_reflector_user_prompt(*args)
        empty = get_reflector_user_prompt(*args, execution_provenance=ExecutionProvenance())
        none = get_reflector_user_prompt(*args, execution_provenance=None)
        assert legacy == empty == none

    def test_a_disagreeing_prompt_actually_differs(self):
        """Guards the guard: if the renderer emitted nothing in BOTH cases the
        test above would still pass."""
        from agent.prompts import get_reflector_user_prompt

        args = ("davis_run_001", STALE_PROSE, {"denoising_score": 0.31}, {})
        _, provenance = _resolved_through_production(_plan())
        assert get_reflector_user_prompt(*args) != get_reflector_user_prompt(
            *args, execution_provenance=provenance
        )


# ------------------------------------------------- the audit, made executable
class TestTheDriftIsNotLossSpecific:
    """§2 of the assignment: audit the ADJACENT values, not only the loss.

    Six resolution steps sit between the plan being authored and the prose
    being read. Each is a channel by which the narrative can describe a
    configuration that did not run.
    """

    def test_the_epoch_bound_is_a_drift_channel(self):
        """`--max_epochs` clamps the RESOLVED training config. The witnessed
        F15 sentence named an epoch count too."""
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker
        from nodes.ml_hyperparameter_tune_agent.runtime import _apply_epoch_bound

        plan = _plan()
        tracker = ResolutionTracker(plan)
        _apply_epoch_bound(plan.train_cfg, 1)
        tracker.record(plan, "max_epochs_bound")
        events = {e.field_path: e for e in tracker.finish(plan).events}
        assert "train_cfg.epochs" in events
        assert events["train_cfg.epochs"].proposed == "3"
        assert events["train_cfg.epochs"].executed == "1"
        assert events["train_cfg.epochs"].authority == "max_epochs_bound"

    def test_operator_overrides_are_a_drift_channel(self):
        """`plan_overrides` can replace ANY field, including ones the prose
        describes, and it runs before every other resolution step."""
        from nodes.ml_hyperparameter_tune_agent.policy import _apply_plan_overrides
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan()
        tracker = ResolutionTracker(plan)
        # The ALIAS form. `_apply_plan_overrides` merges over a
        # `model_dump(by_alias=True)`, and `HyperparamTuningInput` normalizes
        # operator keys to aliases before they ever reach here. Passing the
        # attribute name instead is silently ignored — see the Lane D report's
        # adjacent finding on that site's optimistic success message.
        plan = _apply_plan_overrides(plan, {"train_config": {"epochs": 7, "lr": 1e-3}})
        tracker.record(plan, "operator_plan_overrides")
        events = {e.field_path: e for e in tracker.finish(plan).events}
        assert events["train_cfg.epochs"].authority == "operator_plan_overrides"
        assert events["train_cfg.epochs"].executed == "7"

    def test_the_forced_model_type_is_a_drift_channel(self):
        """It is applied to a COPY of `model_cfg` after the plan stops
        changing, so a plan diff alone cannot see it — it travels as `extra`.
        A prose sentence naming an architecture is wrong the same way."""
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan()
        tracker = ResolutionTracker(plan)
        provenance = tracker.finish(
            plan,
            extra=(("model_cfg.model_type", "'wavenet'", "'punet'", "forced_model_type"),),
        )
        events = {e.field_path: e for e in provenance.events}
        assert events["model_cfg.model_type"].executed == "'punet'"
        assert events["model_cfg.model_type"].authority == "forced_model_type"

    def test_an_agreeing_extra_contributes_nothing(self):
        """A run whose planner already chose the forced model has no
        disagreement to report."""
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan()
        provenance = ResolutionTracker(plan).finish(
            plan,
            extra=(("model_cfg.model_type", "'wavenet'", "'wavenet'", "forced_model_type"),),
        )
        assert not provenance.diverged


class TestTheTrackerCannotGoQuietlyBlind:
    """Detection is structural; attribution is best-effort.

    The obvious implementation records provenance at each KNOWN override site,
    and goes silently blind the day a seventh is added. This repository has
    been bitten by that census shape repeatedly, so the property is asserted
    rather than assumed.
    """

    def test_an_unregistered_resolution_step_is_still_reported(self):
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan()
        tracker = ResolutionTracker(plan)
        # A resolution step nobody wrapped — the seventh, added later.
        plan.train_cfg["lr"] = 1e-2
        events = {e.field_path: e for e in tracker.finish(plan).events}
        assert "train_cfg.lr" in events, "an unwrapped resolution step vanished"
        assert events["train_cfg.lr"].authority == "unattributed"

    def test_a_field_overruled_twice_reports_the_authored_value(self):
        """The prose describes what was AUTHORED. Reporting an intermediate
        value would name something no narrative ever claimed."""
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan()
        tracker = ResolutionTracker(plan)
        plan.train_cfg["epochs"] = 5
        tracker.record(plan, "operator_plan_overrides")
        plan.train_cfg["epochs"] = 1
        tracker.record(plan, "max_epochs_bound")
        event = next(e for e in tracker.finish(plan).events if e.field_path == "train_cfg.epochs")
        assert event.proposed == "3"
        assert event.executed == "1"
        assert event.authority == "operator_plan_overrides"


# ---------------------------------------------------------------- reachability
class TestProductionActuallyRoutesThroughTheBoundary:
    """A boundary nothing calls is decoration (CLAUDE.md decomposition rule)."""

    def test_the_bridge_threads_it_into_the_reflector_prompt(self):
        """Exercises the REAL `LLMBridge.reflect` body, not a re-implementation
        of what it is supposed to do."""
        from agent.llm_bridge import LLMBridge

        captured: dict[str, str] = {}

        class _Spy:
            reflect_client = object()
            reflect_model_name = "m"
            reflect_provider = "openai"

            def _chat_json(self, client, model, system, user, label, provider):
                captured["user"] = user
                return {}

        _, provenance = _resolved_through_production(_plan())
        LLMBridge.reflect(
            _Spy(),
            "davis_run_001",
            STALE_PROSE,
            {"denoising_score": 0.31},
            {},
            # Required since 07b: the reflector is never allowed to assume a
            # direction. Supplying it here keeps this test on the production
            # path rather than around it.
            metric_spec=_metric_spec(),
            execution_provenance=provenance,
        )
        assert "davis_exact_l1" in captured["user"]

    def test_the_reflection_call_forwards_the_prepared_value_unrebuilt(self):
        """The production reflect call must forward `prepared`'s OWN provenance.

        Rebuilding it at the call site would re-derive it from whatever the plan
        looks like by then, and could not see a divergence the planning window
        introduced — the `feedback_test_captures_what_production_recomputes`
        shape. Exercises the real `invoke_reflection`, so it is a behavioural
        reachability check rather than a grep over source text.
        """
        from nodes.ml_hyperparameter_tune_agent.feedback import invoke_reflection

        _, provenance = _resolved_through_production(_plan())
        sentinel = object()
        seen: dict[str, Any] = {}

        class _Prepared:
            hypothesis = STALE_PROSE
            execution_provenance = provenance

        class _Brain:
            def reflect(self, exp_id, hypothesis, results, context, **kwargs):
                seen.update(kwargs)
                seen["hypothesis"] = hypothesis
                return {}

        invoke_reflection(
            _Brain(),
            exp_id="davis_run_001",
            prepared=_Prepared(),
            reflect_results={},
            reflection_context=None,
            metric_spec=sentinel,
            training_diagnosis=None,
            task_render=None,
        )
        assert seen["execution_provenance"] is provenance
        # Both narrative inputs travel together: the proposal AND what
        # overruled it. Sending the prose alone is the F15 defect.
        assert seen["hypothesis"] == STALE_PROSE

    def test_the_tuner_routes_its_reflection_through_that_one_boundary(self):
        """`run()` must not regain a second, un-provenanced reflect call."""
        source = (
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")
        assert "brain.reflect(" not in source
        assert source.count("invoke_reflection(") == 1

    def test_planning_cannot_forget_to_populate_it(self):
        """`PreparedAttempt` declares the field with no default, so a planning
        path that skipped it fails at construction rather than shipping a
        silently un-provenanced attempt downstream."""
        from nodes.ml_hyperparameter_tune_agent.contracts import PreparedAttempt

        assert "execution_provenance" in PreparedAttempt.__dataclass_fields__
        with pytest.raises(TypeError):
            PreparedAttempt(  # type: ignore[call-arg]
                plan=None,
                trial_config=None,
                active_params=None,
                record_params=None,
                exp_id=None,
                hypothesis=None,
                model_type=None,
                model_config=None,
                memory_history=None,
                train_sample_set=None,
                eval_sample_set=None,
                task_scopes=None,
                train_psd_segments=None,
                eval_psd_segments=None,
                ordering=None,
                planned_trial_strategy=None,
                planned_eval_strategy=None,
                strategy_normalization_reason=None,
                cfg_trial_portion=None,
                cfg_train_portion=None,
                cfg_eval_portion=None,
                _planned_portions=None,
            )


class TestTheBlockIsNotDilutedByDefaultMaterialization:
    """Signal quality is part of correctness here.

    Plan sub-configs are raw dicts, so a wholesale replacement swaps a partial
    authored dict for a full schema dump. The first working version of this
    block rendered EIGHT lines for the DAVIS overrule, four of them
    ``<absent> -> None``. Burying `loss_type` and `epochs` in default noise
    weakens exactly the instruction the reflector is meant to follow.
    """

    def test_falsy_defaults_for_unauthored_keys_are_suppressed(self):
        _, provenance = _resolved_through_production(_plan())
        paths = {e.field_path for e in provenance.events}
        assert "loss_cfg.alpha" not in paths
        assert "loss_cfg.gamma" not in paths
        assert "loss_cfg.use_class_weights" not in paths

    def test_a_real_new_value_is_still_reported(self):
        """The suppression must not swallow the most useful line in the block.
        `loss_name` was never authored by the planner, and it is the identity
        of what actually trained."""
        _, provenance = _resolved_through_production(_plan())
        by_path = {e.field_path: e for e in provenance.events}
        assert by_path["loss_cfg.loss_name"].executed == "'davis_exact_l1'"

    def test_the_two_values_f15_got_wrong_are_both_present(self):
        """The regression, named: F15 reported a Smooth L1 beta that did not
        run. Both the overruled beta and the overruled loss type appear."""
        _, provenance = _resolved_through_production(_plan())
        by_path = {e.field_path: e for e in provenance.events}
        assert by_path["loss_cfg.beta"].proposed == "0.5"
        assert by_path["loss_cfg.beta"].executed == "None"
        assert by_path["loss_cfg.loss_type"].proposed == "'smooth_l1'"

    def test_suppression_never_hides_a_change_the_planner_authored(self):
        """The rule keys on the planner NOT having authored the field. A value
        the planner did author, overruled to None, must still be reported."""
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan()
        tracker = ResolutionTracker(plan)
        plan.loss_cfg["beta"] = None
        assert any(e.field_path == "loss_cfg.beta" for e in tracker.finish(plan).events)


class TestTheProductionProducerEntryPointIsWitnessed:
    """Carry-home (#319). The suite above drives ``ResolutionTracker.finish``.

    Production does not call ``finish``. It calls ``finish_with_model``
    (``planning.py``, its sole call site), the wrapper that adds the model
    channel — the one resolution a plan diff structurally cannot see, because
    the executed model type is written onto a copy of ``model_cfg`` after the
    plan stops changing.

    Nothing above calls that wrapper. ``test_the_forced_model_type_is_a_drift
    _channel`` comes closest and hand-builds the very ``extra=`` tuple the
    wrapper exists to compose, which is the
    ``feedback_test_captures_what_production_recomputes`` shape in its
    composition form: *a test that re-implements what production composes
    cannot see a composition defect.*

    Demonstrated, not argued. Replacing ``finish_with_model``'s body with
    ``return ExecutionProvenance(events=())`` — the whole provenance channel
    severed at the producer, so every reflector prompt silently reverts to the
    stale hypothesis F15 exists to correct — left all 23 tests GREEN. The
    consumer half was already witnessed (dropping the rendered block turns 6
    RED). This closes the producer half.

    ``test_planning_cannot_forget_to_populate_it`` does not cover it: it proves
    ``PreparedAttempt`` REQUIRES the field, which an empty provenance satisfies.
    Required and populated are different properties.
    """

    def _forced(self, planned: str, executed: str):
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan(model_type=planned)
        tracker = ResolutionTracker(plan)
        return tracker.finish_with_model(plan, executed_model_type=executed)

    def test_the_model_channel_survives_the_production_entry_point(self):
        """RED under the severing mutation above."""
        provenance = self._forced("wavenet", "pe_wavenet_delta")

        events = {e.field_path: e for e in provenance.events}
        assert "model_type" in events, (
            "the forced model type did not reach the provenance through the "
            "entry point production actually calls -- the reflector would "
            "narrate the architecture the planner proposed, not the one that ran"
        )
        assert events["model_type"].executed == repr("pe_wavenet_delta")
        assert events["model_type"].proposed == repr("wavenet")
        assert events["model_type"].authority == "forced_model_type"
        assert provenance.diverged

    def test_an_unforced_model_contributes_nothing_through_it(self):
        """Vacuity guard, and a real property: the wrapper must not manufacture
        a divergence on the ordinary run where nothing was overruled.

        Without this the assertion above would pass against a wrapper that
        emitted a model event unconditionally.
        """
        provenance = self._forced("wavenet", "wavenet")

        assert not any(e.field_path == "model_type" for e in provenance.events)

    def test_the_recorded_steps_survive_it_too(self):
        """The wrapper delegates rather than replacing.

        Severing it returned an EMPTY provenance, which drops the registered
        resolution steps as well as the model channel. This fails on that, so
        the witness does not depend on the model event alone.
        """
        from nodes.ml_hyperparameter_tune_agent.provenance import ResolutionTracker

        plan = _plan()
        tracker = ResolutionTracker(plan)
        plan = _planning()._apply_declared_objective(plan, _davis_objective_ref())
        tracker.record(plan, "task_declared_objective")

        provenance = tracker.finish_with_model(plan, executed_model_type=plan.model_type)

        assert provenance.events, (
            "the production entry point reported no resolution at all, though "
            "the declared objective overruled the planner's loss"
        )
        assert any(e.authority == "task_declared_objective" for e in provenance.events)

    def test_it_is_the_call_planning_makes(self):
        """Reachability for the pairing itself.

        The behavioural tests above would keep passing if planning switched to
        `finish`, silently dropping the model channel -- so the pairing is
        pinned. A source census is the honest instrument here: the alternative
        is executing `prepare_attempt`, whose fixture cost buys no extra
        confidence about which method name appears at one line.
        """
        source = (REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "planning.py").read_text(
            encoding="utf-8"
        )

        assert source.count("finish_with_model(") == 1
        assert "resolution.finish(" not in source
