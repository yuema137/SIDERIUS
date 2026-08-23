"""Step 12 / PR-12bc — B5: composed-path scope acquisition.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §M / B5; ledger §Q.B5 (D-BC-13).

The boundary ``prepare_attempt`` CALLS. What it owns:

* **a composed run's scopes come from the BOUND implementation**, with a
  request derived from the same values the legacy path passes to
  ``build_sample_set``;
* **an un-composed run acquires nothing** — a STATEMENT, not a missing value;
* **discrimination is by composition PRESENCE**, never by task name;
* **capability-absent refuses parent-side**, while the attempt is being
  prepared, so a composed run that cannot build its own scopes never reaches a
  spawn.

**Not here, by D-BC-13**: the "``build_sample_set`` is not called on the
composed path" spy. The legacy sample sets are still consumed by the training
spawn, both inference spawns and the validation-expectation decision, so
making them ``None`` at B5 would break a composed run before a replacement
existed. B6 flips those consumers and carries that spy.
"""

from __future__ import annotations

import pytest

from execute_tools.dataset_config import DataScope
from execute_tools.task_data_path import (
    ScopeBuildRequest,
    TaskScopeCapabilityError,
    bind_task_data_path,
)
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
    AttemptScopes,
    acquire_attempt_scopes,
)


class _Recorder:
    """A data path that records the requests it is asked to build from."""

    task_data_path_id = "b5_recorder"

    def __init__(self):
        self.requests: list[tuple[str, ScopeBuildRequest]] = []

    def training_dataset(self, scope, params):  # pragma: no cover
        raise AssertionError("B5 never materializes")

    def validation_dataset(self, scope, params):  # pragma: no cover
        raise AssertionError("B5 never materializes")

    def write_deliverable(self, outputs, request):  # pragma: no cover
        raise AssertionError("B5 never writes")

    def read_evaluation_payload(self, request):  # pragma: no cover
        raise AssertionError("B5 never reads")

    def build_training_scope(self, request):
        self.requests.append(("training", request))
        return {"leg": "training", "portion": request.portion}

    def build_eval_scope(self, request):
        self.requests.append(("evaluation", request))
        return {"leg": "evaluation", "portion": request.portion}

    def serialize_scope(self, scope):  # pragma: no cover
        raise AssertionError("B5 never serializes")

    def deserialize_scope(self, payload):  # pragma: no cover
        raise AssertionError("B5 never deserializes")


class _NoCapability(_Recorder):
    task_data_path_id = "b5_no_capability"
    build_training_scope = None  # type: ignore[assignment]
    build_eval_scope = None  # type: ignore[assignment]
    serialize_scope = None  # type: ignore[assignment]
    deserialize_scope = None  # type: ignore[assignment]


KNOBS = {
    "mode": "trial",
    "trial_strategy": "snapshot",
    "trial_portion": 0.1,
    "eval_strategy": "snapshot",
    "eval_portion": 0.5,
    "train_sampling_seed": 11,
    "eval_sampling_seed": 22,
    "target_files": None,
    "subset": None,
    "validation_max_samples": None,
    "task_parameters": {"seg_size": 10_000},
}


class TestAnUnComposedRunAcquiresNothing:
    def test_it_returns_a_declared_absence(self):
        got = acquire_attempt_scopes(composed=False, **KNOBS)
        assert got == AttemptScopes()
        assert got.acquired is False

    def test_it_never_touches_the_binding(self):
        """An un-composed run must not consult a data path at all — otherwise
        a stray registration could start changing legacy behaviour.
        """
        impl = _Recorder()
        with bind_task_data_path(impl):
            acquire_attempt_scopes(composed=False, **KNOBS)
        assert impl.requests == []

    def test_single_file_acquires_nothing_even_when_composed(self):
        """`planning.py:423-424` sets both sample sets to ``None`` in that
        mode; a task is never asked for a scope it has no round for.
        """
        impl = _Recorder()
        with bind_task_data_path(impl):
            got = acquire_attempt_scopes(composed=True, **{**KNOBS, "mode": "single_file"})
        assert got == AttemptScopes()
        assert impl.requests == []


class TestAComposedRunAsksTheBoundImplementation:
    @pytest.mark.parametrize("mode", ["trial", "formal"])
    def test_both_legs_are_built_by_the_capability(self, mode):
        impl = _Recorder()
        with bind_task_data_path(impl):
            got = acquire_attempt_scopes(composed=True, **{**KNOBS, "mode": mode})
        assert [leg for leg, _ in impl.requests] == ["training", "evaluation"]
        assert got.training == {"leg": "training", "portion": 0.1}
        assert got.evaluation == {"leg": "evaluation", "portion": 0.5}
        assert got.acquired is True

    def test_the_request_carries_the_values_the_legacy_path_uses(self):
        """Each leg gets its OWN strategy, portion and seed — the same split
        `planning.py:397-414` already makes. A boundary that fed both legs one
        seed would make train and eval select identically and nothing would
        raise.
        """
        impl = _Recorder()
        with bind_task_data_path(impl):
            acquire_attempt_scopes(
                composed=True,
                **{
                    **KNOBS,
                    "trial_strategy": "anchors",
                    "trial_portion": 0.25,
                    "train_sampling_seed": 101,
                    "eval_strategy": "snapshot",
                    "eval_portion": 1.0,
                    "eval_sampling_seed": 202,
                },
            )
        train = dict(impl.requests)["training"]
        evaluation = dict(impl.requests)["evaluation"]
        assert (train.selection_strategy, train.portion, train.seed) == ("anchors", 0.25, 101)
        assert (evaluation.selection_strategy, evaluation.portion, evaluation.seed) == (
            "snapshot",
            1.0,
            202,
        )

    def test_the_row_ceiling_bounds_the_EVAL_leg_only(self):
        """07c C6's ceiling is a VALIDATION posture. A training scope carrying
        it would silently shrink training too, and the run would look like it
        had simply chosen a smaller plan.
        """
        impl = _Recorder()
        with bind_task_data_path(impl):
            acquire_attempt_scopes(composed=True, **{**KNOBS, "validation_max_samples": 4096})
        assert dict(impl.requests)["training"].max_samples is None
        assert dict(impl.requests)["evaluation"].max_samples == 4096

    def test_the_target_list_is_normalized_by_the_boundary(self):
        """``None`` and ``[]`` both mean "no explicit subset"; normalizing
        here is what keeps ``prepare_attempt``'s branch count flat (§J).
        """
        for supplied in (None, [], [2, 5]):
            impl = _Recorder()
            with bind_task_data_path(impl):
                acquire_attempt_scopes(composed=True, **{**KNOBS, "target_files": supplied})
            assert dict(impl.requests)["training"].target_partitions == tuple(supplied or ())

    def test_the_operator_subset_crosses_as_an_opaque_string(self):
        impl = _Recorder()
        with bind_task_data_path(impl):
            acquire_attempt_scopes(composed=True, **{**KNOBS, "subset": DataScope.from_cli("4-9")})
        assert dict(impl.requests)["training"].subset_ref == "4,5,6,7,8,9"

    def test_the_per_attempt_task_knobs_cross_opaquely(self):
        impl = _Recorder()
        with bind_task_data_path(impl):
            acquire_attempt_scopes(
                composed=True, **{**KNOBS, "task_parameters": {"seg_size": 512, "x": [1]}}
            )
        assert dict(impl.requests)["training"].task_parameters == {"seg_size": 512, "x": [1]}


class TestFailClosed:
    def test_a_composed_run_without_the_capability_refuses_parent_side(self):
        """Named, and BEFORE any subprocess — the whole point of resolving the
        capability while the attempt is being prepared.
        """
        with bind_task_data_path(_NoCapability()):
            with pytest.raises(TaskScopeCapabilityError) as exc:
                acquire_attempt_scopes(composed=True, **KNOBS)
        assert "b5_no_capability" in str(exc.value)
        assert "before any subprocess was launched" in str(exc.value)

    def test_composed_with_no_binding_is_a_wiring_contradiction(self):
        """Not a regime-A run: the composition is what named the task, so a
        composed run reaching here unbound is a wiring bug, and saying so is
        more useful than silently building TIDMAD's scope.
        """
        with pytest.raises(RuntimeError, match="wiring contradiction"):
            acquire_attempt_scopes(composed=True, **KNOBS)


class TestNoTaskNameDispatch:
    def test_the_module_never_names_a_task(self):
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[4]
            / "nodes"
            / "ml_hyperparameter_tune_agent"
            / "scope_acquisition.py"
        ).read_text(encoding="utf-8")
        code = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
        for task in ("tidmad", "pets", "davis", "oxford"):
            assert task not in code.lower().split('"""')[-1], (
                f"{task!r} appears in executable code — discrimination is by "
                f"composition PRESENCE, never by task name"
            )
