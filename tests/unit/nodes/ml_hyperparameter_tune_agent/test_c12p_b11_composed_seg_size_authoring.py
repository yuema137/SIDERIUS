"""C12-P / B11 — the framework AUTHORS ``seg_size`` into an OPAQUE channel.

CLOSED. Expected GREEN. This file began as a falsifier against the expression
below and now guards the repair; the header said "Expected RED on this
checkout" until B11 and then F-C12P-B11-2 landed, and leaving that claim in
place would tell a future reader the suite is supposed to be failing.

The original defect, ``planning.py``::

    task_parameters={"seg_size": plan.model_cfg.get("segmentation_size", 10000)}

Three separate things are wrong with that expression and only the last one is
about a number:

1. ``task_parameters`` is declared OPAQUE to the framework
   (``execute_tools/task_data_path.py``: "a framework site that reads inside
   it fails the genericity census"). Passing the PLAN's stated value through
   is the declared design; INVENTING one when the plan is silent is the
   framework writing task vocabulary it does not speak.
2. The only production reader of that key,
   ``execute_tools/tidmad_data_path.py:383-395``, explicitly REFUSES to guess
   it -- "the framework has no vocabulary for it, so it must be declared by
   the caller rather than guessed here". The literal defeats that refusal from
   outside, which is why the refusal has never once been observed in
   production.
3. ``10000`` is not TIDMAD's declared default either. ``WaveNetConfig``
   declares ``40000`` (``ml_models/models_format_sandbox.py:25``), and that is
   what the model is CONSTRUCTED with. So a plan that simply omits the key
   scopes its data at 10000 and trains at 40000 -- silently, with no error and
   a plausible-looking number on both sides.

Point 3 is why this is a CORRECTION and not a preservation: removing the
literal CHANGES behaviour for a legacy TIDMAD run whose plan omits
``segmentation_size``. That run is already wrong today; it is not being kept
byte-identical, it is being fixed.

WHAT LANDED, AND THE STEP IN BETWEEN (F-C12P-B11-2, operator rulings 1/1C).
B11's first repair simply dropped the literal, so an omitted key stayed
omitted and the task refused. The refusal was right; dropping the literal with
NOTHING in its place was not. ``segmentation_size`` is LEGITIMATELY optional
(``agent/schemas/proposal.py:1247`` -- "some architectures don't have one"), so
every run whose plan omitted it then died at scope construction on every
attempt and never reached the reflector. A plan omitting the key does not mean
the MODEL declares no geometry.

The landed chain is::

    explicit plan value -> resolve_model_field(...) -> legitimate absence

so the three regimes below are all reachable, and the refusal fires on the
state that actually warrants it -- nothing, anywhere, declares a value:

    regime A  the plan states it              -> that value
    regime B  plan omits, model declares      -> the declared default
    regime C  no authority declares           -> the task refuses, by name
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, TaskCompositionRef
from execute_tools.dataset_config import TIDMAD_PROFILE
from execute_tools.task_data_path import bind_task_data_path
from nodes.ml_hyperparameter_tune_agent.contracts import RunBindings
from nodes.ml_hyperparameter_tune_agent.planning import prepare_attempt

#: What ``WaveNetConfig`` DECLARES (`ml_models/models_format_sandbox.py:25`).
#: Hardcoded on purpose: read back from the config class it would compare the
#: schema to itself and pass for any default.
WAVENET_DECLARED_SEG_SIZE = 40_000

#: The literal the framework invents today.
AUTHORED_LITERAL = 10_000


class _ScopeRecorder:
    """A composed task that records the request it is asked to build from.

    Only the scope capability is real; nothing here materializes data, which
    is what keeps this a unit test of the AUTHORING and not of TIDMAD.
    """

    task_data_path_id = "c12p_b11_recorder"

    def __init__(self):
        self.requests: list = []

    def training_dataset(self, scope, params):  # pragma: no cover
        raise AssertionError("this test never materializes")

    def validation_dataset(self, scope, params):  # pragma: no cover
        raise AssertionError("this test never materializes")

    def write_deliverable(self, outputs, request):  # pragma: no cover
        raise AssertionError("this test never writes")

    def read_evaluation_payload(self, request):  # pragma: no cover
        raise AssertionError("this test never reads")

    def build_training_scope(self, request):
        self.requests.append(request)
        return {"leg": "training"}

    def build_eval_scope(self, request):
        self.requests.append(request)
        return {"leg": "evaluation"}

    def serialize_scope(self, scope):  # pragma: no cover
        raise AssertionError("this test never serializes")

    def deserialize_scope(self, payload):  # pragma: no cover
        raise AssertionError("this test never deserializes")


class _RefusingScope(_ScopeRecorder):
    """TIDMAD's OWN refusal, quoted rather than re-implemented.

    ``tidmad_data_path.TidmadDataPath._build_scope`` raises exactly this when
    ``seg_size`` is absent or non-positive. Reproducing the check here (rather
    than binding the real implementation) keeps the test free of TIDMAD's data
    root while asserting against the message TIDMAD actually emits -- the file
    is quoted in this module's docstring so a divergence is visible.
    """

    task_data_path_id = "c12p_b11_refusing"

    def build_training_scope(self, request):
        seg_size = request.task_parameters.get("seg_size")
        if not isinstance(seg_size, int) or seg_size <= 0:
            raise ValueError(
                "TIDMAD scope construction requires a positive 'seg_size' in "
                "the request's task_parameters (the planner's ML segmentation "
                f"size); got {seg_size!r}. The framework has no vocabulary for "
                "it, so it must be declared by the caller rather than guessed "
                "here."
            )
        self.requests.append(request)
        return {"leg": "training"}

    build_eval_scope = build_training_scope


class _Brain:
    """A planner that returns a plan with NO ``segmentation_size``.

    That is the whole fixture: a legal ``ExperimentPlan`` whose ``model_cfg``
    is silent about the field, which is the case ``planning.py:447``'s
    ``.get(..., 10000)`` exists to paper over.
    """

    def plan(self, memory_history, **kwargs):
        return {
            "model_type": "wavenet",
            "hypothesis": "c12p b11",
            "reasoning": "the plan deliberately omits segmentation_size",
            "model_cfg": {"multi": 16, "depth": 2, "embedding_dim": 8},
            "train_cfg": {"batch_size": 1, "epochs": 1},
            "loss_cfg": {"loss_type": "ce"},
            "is_trial": True,
            "trial_strategy": "snapshot",
            "trial_portion": 0.01,
            "train_portion": 1.0,
            "eval_strategy": "snapshot",
            "eval_portion": 0.01,
            "train_validation_align": True,
        }


class _Sandbox:
    """Empty history and a real ``configs`` directory.

    ``prepare_attempt`` persists the validated ``TrialConfig`` before it
    returns; ``tmp_path`` keeps that write inside the test's own directory
    rather than a shared location.
    """

    def __init__(self, configs_dir):
        self.dirs = {"configs": str(configs_dir)}

    def get_summary(self):
        return []


def _bindings(agent_input, configs_dir) -> RunBindings:
    from execute_tools.evaluation_metric import derive_tidmad_metric
    from execute_tools.metric_order import MetricOrder

    metric = derive_tidmad_metric(TIDMAD_PROFILE)
    return RunBindings(
        agent_input=agent_input,
        sandbox=_Sandbox(configs_dir),
        brain=_Brain(),
        registry=None,
        run_profile=TIDMAD_PROFILE,
        run_model_io=None,
        run_deliverable_spec=None,
        run_metric=metric,
        run_secondary_metrics=(),
        run_order=MetricOrder(metric.spec),
        run_task_render=None,
        run_name="c12p_b11",
        workspace=str(configs_dir),
        file_index=0,
        max_rounds=1,
        model_type_setting="wavenet",
        trial_allowed=True,
        resolved_data_scope=[0, 1],
        scope_is_partial=False,
        expert_advice_str="",
        config_manual_data=None,
        model_description=None,
        trial_vram_budget=None,
        formal_vram_budget=None,
        trial_time_budget=None,
        formal_time_budget=None,
        attempts_per_round_setting=1,
        attempts_per_formal_round_setting=1,
        max_fail_rounds_setting=1,
        formal_reference_score=None,
        formal_reference_source=None,
        resolved_skip_formal_threshold=None,
        resolved_bypass_formal_threshold=None,
        hardware_context=None,
        device_identity=None,
        time_data_dir=None,
        anchor_map_data=None,
        reference_scores=None,
        started_at=0.0,
        health_checks_config_source=None,
        health_config_sha256=None,
    )


def _composed_input() -> HyperparamTuningInput:
    return HyperparamTuningInput(
        model_type="wavenet",
        task_composition_ref=TaskCompositionRef(
            semantic_fingerprint="c12p-b11-fingerprint",
            task_data_path_id="c12p_b11_recorder",
            task_health_binding=None,
        ),
    )


def _prepare(impl, configs_dir):
    agent_input = _composed_input()
    assert agent_input.task_composition_ref is not None, "fixture must be composed"
    with bind_task_data_path(impl):
        return prepare_attempt(
            _bindings(agent_input, configs_dir),
            iteration=1,
            attempt_in_round=1,
            total_attempts=1,
            attempts_this_round=1,
            is_formal_round=False,
            formal_trial_winner=None,
        )


class TestTheFrameworkNeverAuthorsTaskVocabulary:
    def test_an_omitted_segmentation_size_is_not_replaced_by_a_literal(self, tmp_path):
        """B11. The defect this alone catches: ``planning.py:447`` inventing a
        value for a key the framework declares itself unable to interpret.

        Asserted as ``!= 10000`` rather than ``== 40000`` deliberately -- BOTH
        candidate fixes must pass. Omitting the key (so the task refuses) and
        resolving it through ``resolve_model_field`` (so the scope matches the
        model that will be built) are different decisions with different
        consequences for a legacy run, and this test is about the authoring,
        not about which decision is taken.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES: the recorded request's
        ``task_parameters['seg_size']`` is 10000 again -- a number no plan
        stated, no config class declares, and no model will be built with.
        """
        impl = _ScopeRecorder()
        _prepare(impl, tmp_path)

        assert impl.requests, "the composed run must have asked for a scope"
        seg = impl.requests[0].task_parameters.get("seg_size")
        assert seg != AUTHORED_LITERAL, (
            f"the framework authored seg_size={seg!r} into task_parameters for "
            "a plan that never declared segmentation_size. That channel is "
            "OPAQUE to the framework, and its only reader "
            "(tidmad_data_path.py:383-395) explicitly refuses to guess this "
            f"value. The model will be constructed at "
            f"{WAVENET_DECLARED_SEG_SIZE} regardless."
        )

    def test_a_declared_segmentation_size_still_travels_unchanged(self, tmp_path):
        """Guards the FIX, not the defect: whatever C12-P does to the absent
        case must leave the PRESENT case exactly as it is. Every production
        plan states this field, so this is where "behaviour-preserving" is
        actually measured.

        HOW IT FAILS: a fix that routes the present value through a resolver
        with the wrong precedence, or that starts preferring the class default
        over the plan, changes 8000 into 40000.

        Expected to PASS today.
        """
        impl = _ScopeRecorder()
        agent_input = _composed_input()

        class _DeclaringBrain(_Brain):
            def plan(self, memory_history, **kwargs):
                decision = super().plan(memory_history, **kwargs)
                decision["model_cfg"]["segmentation_size"] = 8_000
                return decision

        bindings = _bindings(agent_input, tmp_path)
        object.__setattr__(bindings, "brain", _DeclaringBrain())
        with bind_task_data_path(impl):
            prepare_attempt(
                bindings,
                iteration=1,
                attempt_in_round=1,
                total_attempts=1,
                attempts_this_round=1,
                is_formal_round=False,
                formal_trial_winner=None,
            )

        assert impl.requests
        assert impl.requests[0].task_parameters["seg_size"] == 8_000


class _UndeclaredModelBrain(_Brain):
    """A plan that omits the key AND names a model nothing declares for.

    ``get_config_class`` returns ``None`` for an unregistered model type, so
    no authority anywhere states a ``segmentation_size``. This is REGIME C.
    """

    def plan(self, memory_history, **kwargs):
        decision = super().plan(memory_history, **kwargs)
        decision["model_type"] = "c12p_b11_model_no_config_class_v1"
        return decision


class TestTheTaskRefusalIsReachable:
    """C12-P / F-C12P-B11-2, operator ruling 1B — REGIME C.

    REWORKED, not retired, under the transition this test's own docstring
    reserved: *"if C12-P instead resolves through ``resolve_model_field``
    this test must be reworked rather than allowed to drift."* The operator
    approved that transition; the INVARIANT below is unchanged and the
    refusal assertion is still here.

    What changed is only WHICH state reaches the refusal. It used to be
    "the plan omitted the key". That was wrong: a plan omitting the key does
    NOT mean the model has no declared segmentation geometry — for
    ``wavenet`` the config class declares 40000 and the model is CONSTRUCTED
    at it. Refusing there made every such run die at scope construction
    (F-C12P-B11-2). The refusal now fires on the state that genuinely
    warrants it: nothing, anywhere, declares a value.
    """

    def test_the_task_gets_to_refuse_a_seg_size_no_authority_declares(self, tmp_path):
        """DEFECT THIS TEST ALONE CATCHES
            A REFUSAL that production can never reach. ``tidmad_data_path``
            raises a carefully-worded ``ValueError`` for an absent
            ``seg_size``. Before B11 the framework's literal guaranteed the
            key was always present, so that branch was dead code in every run
            this repository had ever executed. If the resolver ever grows a
            central default, it becomes dead again — silently.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The framework supplies a value for a model nothing declares for
            (a reinstated literal, or a non-zero ``safety_margin`` leaking out
            as a real size), no exception is raised, and ``pytest.raises``
            reports ``DID NOT RAISE``.
        """
        impl = _RefusingScope()
        agent_input = _composed_input()
        bindings = _bindings(agent_input, tmp_path)
        object.__setattr__(bindings, "brain", _UndeclaredModelBrain())
        # The EFFECTIVE model type is the force_model override when one is
        # set, not the plan's -- which is precisely why the repair resolves
        # `model_type` before asking for a declared default. Overriding the
        # brain alone would leave this run on `wavenet` (declares 40000) and
        # the refusal would never be reached, so the fixture would pass for
        # the wrong reason.
        object.__setattr__(bindings, "model_type_setting", "c12p_b11_model_no_config_class_v1")
        with pytest.raises(ValueError, match="seg_size"), bind_task_data_path(impl):
            prepare_attempt(
                bindings,
                iteration=1,
                attempt_in_round=1,
                total_attempts=1,
                attempts_this_round=1,
                is_formal_round=False,
                formal_trial_winner=None,
            )

    def test_regime_B_a_model_declared_size_is_used_instead_of_refusing(self, tmp_path):
        """REGIME B, and the F-C12P-B11-2 regression itself, at unit scale.

        DEFECT THIS TEST ALONE CATCHES
            Treating "the plan omitted the key" as "nobody declared a size",
            so a run whose model DOES declare one is refused at scope
            construction and dies on every attempt. That is the regression
            this repair closes, and no other case in this file sees it: the
            refusal test above is satisfied by refusing, and the literal
            tests are satisfied by any non-10000 value.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            ``_RefusingScope`` raises, and this test reports the ValueError
            instead of a scope request — i.e. the exact production failure.
        """
        impl = _RefusingScope()
        _prepare(impl, tmp_path)

        assert impl.requests, (
            "no scope request was built: the task refused a seg_size for a "
            "plan that omitted the key even though the model's config class "
            "declares one. This is F-C12P-B11-2 — the run dies here, on every "
            "attempt, and never reaches the reflector."
        )
        assert impl.requests[0].task_parameters["seg_size"] == 40_000, (
            "the size that travelled is not wavenet's DECLARED default. It "
            "must be the value the model is actually constructed with."
        )


class TestOnlyTheStatedSizeIsValidated:
    """C12-P / B11, the SECOND ``planning.py`` site.

    ``_validate_data_config`` was handed ``.get("segmentation_size", 10000)``.
    The number it checked therefore had no relationship to the run: an omitted
    key makes the model be CONSTRUCTED at its config class's declared default
    (``config_cls(**model_config)`` — wavenet 40000, transformer 20000), and
    the geometry rule was applied to 10000 instead.

    THE TRAP THIS DELIBERATELY AVOIDS. TIDMAD's ``psd_segment_length`` is
    10,000,000, and 10000 **and** 40000 both divide it evenly. So a falsifier
    built on "does the divisibility check pass" cannot tell the invented value
    from the real one and would go green for the wrong reason. The third test
    below therefore uses a topology where the two verdicts genuinely DIFFER,
    and the first two assert WHICH number reaches the rule rather than what
    the rule then says about it.
    """

    @staticmethod
    def _validated_sizes(monkeypatch, tmp_path, brain=None) -> list:
        """Every value ``prepare_attempt`` hands the geometry rule."""
        # The module that CALLS the rule, resolved from the production symbol
        # this file already imports. `nodes.ml_hyperparameter_tune_agent` is
        # aliased to the node's main module, so an attribute import of
        # `planning` off it does not resolve.
        import sys

        planning = sys.modules[prepare_attempt.__module__]

        seen: list = []
        monkeypatch.setattr(
            planning,
            "_validate_data_config",
            lambda trial_config, segmentation_size, dataset_config: seen.append(segmentation_size),
        )
        impl = _ScopeRecorder()
        bindings = _bindings(_composed_input(), tmp_path)
        if brain is not None:
            object.__setattr__(bindings, "brain", brain)
        with bind_task_data_path(impl):
            prepare_attempt(
                bindings,
                iteration=1,
                attempt_in_round=1,
                total_attempts=1,
                attempts_this_round=1,
                is_formal_round=False,
                formal_trial_winner=None,
            )
        return seen

    def test_an_omitted_size_is_validated_as_the_MODEL_declared_one(self, monkeypatch, tmp_path):
        """REWORKED under operator ruling 1C — REGIME B at the geometry rule.

        This previously asserted ``== []``: with the key omitted and the
        literal gone, nothing was validated. That encoded the omit-the-key
        design, and this test's sibling reserved the transition explicitly.

        The INVARIANT is unchanged and is what the message still names: the
        framework must never apply the task's geometry rule to a number
        **nothing declares and no model is built with**. 10000 was exactly
        that. wavenet's 40000 is the opposite — it is the value
        ``config_cls(**model_config)`` constructs the model at, so validating
        it is validating the run.

        DEFECT THIS TEST ALONE CATCHES
            The geometry rule being applied to an invented number. The
            scope-authoring tests cannot see it: they observe the request, and
            this site never reaches one.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            ``[10000]`` is recorded — naming the invented value directly — or
            ``[]``, meaning the run's real geometry is no longer checked at
            all.
        """
        seen = self._validated_sizes(monkeypatch, tmp_path)

        assert 10_000 not in seen, (
            "the framework validated 10000: a number no plan stated, no "
            "config class declares, and no model is built with."
        )
        assert seen == [40_000], (
            f"expected the geometry rule to check wavenet's DECLARED default, "
            f"got {seen}. An empty list means the run's real geometry is not "
            f"checked at all; any other value means something invented it."
        )

    def test_a_stated_size_is_still_validated_unchanged(self, monkeypatch, tmp_path):
        """CONTROL. Every production plan states this field, so this is where
        "behaviour-preserving" is actually measured.

        HOW IT FAILS: dropping the literal also drops the CHECK, and 8000
        never reaches the rule — a silent loss of the geometry guard for the
        case that matters.
        """

        class _DeclaringBrain(_Brain):
            def plan(self, memory_history, **kwargs):
                decision = super().plan(memory_history, **kwargs)
                decision["model_cfg"]["segmentation_size"] = 8_000
                return decision

        assert self._validated_sizes(monkeypatch, tmp_path, _DeclaringBrain()) == [8_000]

    def test_the_invented_value_and_a_real_one_reach_different_verdicts(self):
        """DISCRIMINATION. Proves the number this site is given is OBSERVABLE,
        so the two tests above are not cosmetic.

        Under TIDMAD both candidate values divide ``psd_segment_length``
        evenly, which is exactly why the defect was silent for years. This
        topology is chosen so they do not: 45,000 is divisible by 15,000 and
        NOT by 10,000. Hand-computed, hardcoded, and stated here rather than
        derived from the object under test.

        HOW IT FAILS: ``_validate_data_config`` stops distinguishing them —
        i.e. the geometry rule itself has been weakened, which would make
        every other assertion in this class vacuous.
        """
        from execute_tools.dataset_config import DatasetConfig
        from nodes.ml_hyperparameter_tune_agent.policy import _validate_data_config

        topology = DatasetConfig(
            psd_segment_length=45_000,
            segments_per_file=100,
            num_files=4,
            sampling_frequency=10_000.0,
        )
        trial_config = _trial_config_for(topology)

        # 45_000 % 15_000 == 0 — legal, and no exception.
        _validate_data_config(trial_config, 15_000, topology)

        # 45_000 % 10_000 == 5_000 — the invented value is ILLEGAL here, so a
        # plan that merely omitted the key would have been refused on the
        # strength of a number it never contained.
        with pytest.raises(ValueError, match="10000"):
            _validate_data_config(trial_config, 10_000, topology)


def _trial_config_for(topology):
    """A minimal validated ``TrialConfig`` for a direct geometry-rule call."""
    from agent.schemas.hyperparam_tuning import TrialConfig

    return TrialConfig(
        mode="trial",
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.1,
        train_portion=1.0,
        eval_strategy="snapshot",
        eval_portion=0.1,
        target_files=list(range(topology.num_files)),
        train_sampling_seed=0,
        eval_sampling_seed=0,
        train_base_seed=0,
    )
