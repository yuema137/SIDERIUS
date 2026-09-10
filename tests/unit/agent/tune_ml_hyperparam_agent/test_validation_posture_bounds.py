"""The Gate workload envelope: bound the work, not the planner.

Step 03's Gate 2 established, across three attempts, that the knobs a
Gate command reaches for do not bound anything:

    --no-force_formal_round   stops the HARNESS forcing formal. The
                              PLANNER may still ELECT formal, and did.
    --trial_portion 0.01      the planner chose 0.05; and 1 % of the
                              scope still resolved to 12,500 steps,
                              because samples-per-PSD is
                              psd_segment_length // seg_size and
                              seg_size is the planner's.
    --trial_time_budget       forecast-based ADMISSION. One round ran
                              33m53s under a "5 minute" budget.
    --max_steps_per_attempt   REJECTS. Set below the planner's normal
                              solution, every round SKIPPED and no
                              training ran at all.

The design that survives all four: let the planner decide whatever it
decides, and clamp how much real work that decision may EXECUTE — before
launch, because a bound enforced by killing a 25-minute run yields no
evidence and wastes the attempt.

Each test names one way that envelope could leak.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.runtime_control.session import RuntimeControlPolicy
from execute_tools.workload_resolvers import resolve_training_workload
from nodes.ml_hyperparameter_tune_agent import (
    _build_runtime_policy,
    _resolve_guardrail_steps,
    _resolve_sample_set_cfg,
)
from tests.helpers.two_family_profile import make_two_family_profile

#: Six partitions by 200 physical segments: enough neutral work to distinguish
#: a fractional portion from an absolute execution ceiling.
FULL_SCOPE = {str(i): list(range(200)) for i in range(4, 10)}
PROFILE = make_two_family_profile(
    num_files=12,
    psd_segment_length=1_600_000,
    segments_per_file=200,
)


def _input(tmp_path, **over) -> HyperparamTuningInput:
    payload = dict(
        model_type="punet",
        file_index=6,
        max_rounds=1,
        is_trial=True,
        expert_advice="",
        llm_provider="openai",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="posture"),
        ),
        progress_bar=False,
    )
    payload.update(over)
    return HyperparamTuningInput(**payload)


class _Plan:
    """The planner's side of ``_resolve_sample_set_cfg``, minimally."""

    def __init__(self, portion: float):
        self.trial_strategy = "snapshot"
        self.trial_portion = portion
        self.train_portion = portion
        self.eval_strategy = "snapshot"
        self.eval_portion = portion


# ---------------------------------------------------------------------
# The envelope covers BOTH round modes
# ---------------------------------------------------------------------


def test_formal_mode_resolves_the_same_three_portion_values_as_trial(tmp_path):
    """Why one clamp can cover both modes at all.

    Trial portions come from the PLAN and formal portions from
    ``formal_*`` operator input, but both land in the same three
    variables the clamp then reduces. If a future change gave formal its
    own path, the clamp would silently stop covering it — and a Gate
    would believe it was bounded while a formal round ran at full scope.
    """
    agent_input = _input(tmp_path, formal_portion=0.5, formal_train_portion=1.0)

    trial = _resolve_sample_set_cfg("trial", agent_input, _Plan(0.3))
    formal = _resolve_sample_set_cfg("formal", agent_input, _Plan(0.3))

    assert set(trial) == set(formal)
    assert trial["trial_portion"] == 0.3  # from the plan
    assert formal["trial_portion"] == 0.5  # from formal_* operator input


def test_formal_full_scope_eval_default_is_exactly_what_the_ceiling_must_reduce(tmp_path):
    """A formal round defaults ``formal_eval_portion`` to 1.0.

    That default is the reason the envelope may not be trial-only: if the
    planner elects formal in a smoke Gate, the eval side asks for the
    whole scope. Pinned here so nobody concludes formal portions are
    "already small because they come from operator input".
    """
    formal = _resolve_sample_set_cfg("formal", _input(tmp_path), _Plan(0.01))

    assert formal["eval_portion"] == 1.0
    assert min(formal["eval_portion"], 0.01) == 0.01


# ---------------------------------------------------------------------
# The absolute ceiling: what a fraction cannot do
# ---------------------------------------------------------------------


def test_a_one_percent_portion_still_resolves_to_a_huge_step_count():
    """The Step-03 arithmetic, pinned.

    Without this, the absolute ceiling looks redundant next to
    ``validation_max_portion`` — and it is exactly this number that
    proves it is not.
    """
    resolved = resolve_training_workload(
        FULL_SCOPE,
        seg_size=1000,  # planner-chosen: 1,600 model segments per physical segment
        batch_size=1,  # planner-chosen
        train_portion=0.01,
        epochs=1,
        profile=PROFILE,
    )

    assert resolved.unit_count > 10_000


def test_the_absolute_ceiling_bounds_the_step_count_whatever_the_planner_chose():
    """THE property: the executed workload is harness-owned.

    Fails when: the ceiling stops being applied in the resolver, and the
    figure a Gate uses to predict its own cost silently reverts to the
    planner's.
    """
    resolved = resolve_training_workload(
        FULL_SCOPE,
        seg_size=1000,
        batch_size=1,
        train_portion=1.0,  # planner asked for everything
        epochs=1,
        max_samples=1000,
        profile=PROFILE,
    )

    assert resolved.unit_count == 1000
    assert resolved.detail["samples_per_epoch"] == 1000


def test_the_ceiling_survives_a_full_scope_formal_plan():
    """Same ceiling, the worst plan the planner can produce.

    ``train_portion=1.0`` over the full scope is what a formal round with
    ``full_clone`` inheritance looks like. Switching trial -> formal must
    not turn a functional Gate into a scientific run — the single
    regression this whole design exists to prevent.
    """
    unbounded = resolve_training_workload(
        FULL_SCOPE, seg_size=1000, batch_size=8, train_portion=1.0, epochs=1, profile=PROFILE
    )
    bounded = resolve_training_workload(
        FULL_SCOPE,
        seg_size=1000,
        batch_size=8,
        train_portion=1.0,
        epochs=1,
        max_samples=2000,
        profile=PROFILE,
    )

    assert unbounded.unit_count > 100_000
    assert bounded.unit_count == 250  # 2000 samples // batch 8


def test_the_ceiling_is_a_maximum_never_a_target():
    """A generous ceiling must leave a small plan alone.

    Fails when: the comparison is inverted and the envelope starts
    padding runs out to the ceiling, or truncating ordinary campaigns.
    """
    small = {"4": list(range(2))}

    with_ceiling = resolve_training_workload(
        small,
        seg_size=10000,
        batch_size=1,
        train_portion=1.0,
        epochs=1,
        max_samples=10**9,
        profile=PROFILE,
    )
    without = resolve_training_workload(
        small, seg_size=10000, batch_size=1, train_portion=1.0, epochs=1, profile=PROFILE
    )

    assert with_ceiling.unit_count == without.unit_count


# ---------------------------------------------------------------------
# Clamp, never reject
# ---------------------------------------------------------------------


def test_the_step_guardrail_judges_the_executed_workload_not_the_planned_one(tmp_path):
    """The failure that made Gate-2 attempt 3 produce nothing.

    ``max_steps_per_attempt`` REJECTS, so judging the planner's unclamped
    figure would skip an attempt whose real workload is already inside
    the envelope. The Gate would report "bounded" and never train.

    Fails when: the ceiling stops reaching the guardrail resolver.
    """
    planned = _resolve_guardrail_steps(
        FULL_SCOPE,
        {"segmentation_size": 1000},
        {"batch_size": 1, "epochs": 1},
        1.0,
        dataset_profile=PROFILE,
    )
    executed = _resolve_guardrail_steps(
        FULL_SCOPE,
        {"segmentation_size": 1000},
        {"batch_size": 1, "epochs": 1},
        1.0,
        max_samples=1000,
        dataset_profile=PROFILE,
    )

    assert planned is not None and planned > 100_000
    assert executed == 1000


# ---------------------------------------------------------------------
# Transport, defaults and the fuse
# ---------------------------------------------------------------------


def test_both_validation_bounds_reach_the_policy_the_trainer_reads(tmp_path):
    """producer -> policy dict -> validated policy, in one hop.

    The trainer reads ``runtime_session.policy.validation_max_train_samples``
    and the executor reads ``policy.watchdog.max_phase_seconds``. If the
    tuner does not put them on the dict the executor validates, both are
    CLI flags that bound nothing — and the Gate would report a bounded
    run it never had.
    """
    agent_input = _input(
        tmp_path,
        validation_max_train_samples=1000,
        validation_max_phase_seconds=1200.0,
        runtime_watchdog_enabled=True,
    )

    policy = _build_runtime_policy(
        agent_input, chosen_time_budget=None, is_trial=True, base_dir=str(tmp_path)
    )
    validated = RuntimeControlPolicy(**policy)

    assert validated.validation_max_train_samples == 1000
    assert validated.watchdog.max_phase_seconds == 1200.0


def test_an_ordinary_run_ships_neither_bound(tmp_path):
    """Both defaults must survive the whole transport as None.

    Fails when: a default is introduced anywhere on the path, which would
    put a workload ceiling or a kill deadline on real science.
    """
    policy = _build_runtime_policy(
        _input(tmp_path), chosen_time_budget=None, is_trial=True, base_dir=str(tmp_path)
    )
    validated = RuntimeControlPolicy(**policy)

    assert validated.validation_max_train_samples is None
    assert validated.watchdog.max_phase_seconds is None


def test_forecast_trial_keeps_measured_runtime_record_only(tmp_path):
    """Forecast admission must not gain a second measured refusal authority.

    The selected advance forecast owns admission. The in-process verifier may
    still record evidence, but its operator budget must remain absent.
    """
    policy = _build_runtime_policy(
        _input(tmp_path),
        chosen_time_budget=5.0,
        admission_source="forecast",
        is_trial=True,
        base_dir=str(tmp_path),
    )

    assert policy["operator_budget_seconds"] is None


def test_a_wall_clock_fuse_without_the_watchdog_is_refused(tmp_path):
    """A recorded bound that nothing enforces is worse than no bound.

    The watchdog is disabled by default and is the only thing that
    enforces the deadline, so this combination would let a Gate command
    claim a wall-clock limit, run past it, and still report bounded.
    """
    with pytest.raises(ValidationError, match="runtime_watchdog_enabled"):
        _input(tmp_path, validation_max_phase_seconds=600.0)
