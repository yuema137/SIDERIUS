"""A declared parent pool contains every Trial and is exactly Formal."""

from __future__ import annotations

import pytest

from execute_tools.task_data_path import bind_task_data_path
from execute_tools.training_pool import FrozenTrainingPool, FrozenTrainingPoolError
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import acquire_attempt_scopes


class _Task:
    task_data_path_id = "synthetic_frozen_pool"

    def build_training_scope(self, request):
        raise AssertionError("pooled runs must not use the unbounded builder")

    def build_eval_scope(self, request):
        return ("validation", request.portion)

    def build_frozen_training_pool(self, request):
        return FrozenTrainingPool(scope=(2, 4, 6, 8), source_portion=0.1)

    def sample_training_pool(self, pool, request):
        return tuple(pool[: round(len(pool) * request.portion)])

    def training_scope_is_contained(self, child, pool):
        return set(child) <= set(pool)

    def serialize_scope(self, scope):
        return repr(scope)

    def deserialize_scope(self, payload):
        raise AssertionError("not used")


_KNOBS = dict(
    composed=True,
    mode="trial",
    trial_strategy="snapshot",
    trial_portion=0.5,
    eval_strategy="snapshot",
    eval_portion=1.0,
    train_sampling_seed=11,
    eval_sampling_seed=22,
    target_files=None,
    subset=None,
    validation_max_samples=None,
    task_parameters={},
)


def test_trial_portion_is_relative_to_parent_and_eval_remains_independent():
    with bind_task_data_path(_Task()):
        got = acquire_attempt_scopes(**_KNOBS)
    assert got.training == (2, 4)
    assert got.evaluation == ("validation", 1.0)


def test_formal_uses_exact_parent_not_a_second_draw():
    with bind_task_data_path(_Task()):
        got = acquire_attempt_scopes(**{**_KNOBS, "mode": "formal", "trial_portion": 0.1})
    assert got.training == (2, 4, 6, 8)


def test_formal_mismatched_portion_refuses():
    with bind_task_data_path(_Task()):
        with pytest.raises(FrozenTrainingPoolError, match="does not match"):
            acquire_attempt_scopes(**{**_KNOBS, "mode": "formal"})


def test_escaping_child_refuses_before_evaluation():
    class Escaping(_Task):
        def sample_training_pool(self, pool, request):
            return (99,)

        def build_eval_scope(self, request):
            raise AssertionError("should refuse before eval")

    with bind_task_data_path(Escaping()):
        with pytest.raises(FrozenTrainingPoolError, match="escapes"):
            acquire_attempt_scopes(**_KNOBS)


def test_partial_capability_refuses_instead_of_falling_back():
    class Partial(_Task):
        sample_training_pool = None

    with bind_task_data_path(Partial()):
        with pytest.raises(FrozenTrainingPoolError, match="sample_training_pool"):
            acquire_attempt_scopes(**_KNOBS)
