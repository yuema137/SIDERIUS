"""Step 12 / PR-12d — F-12d-27: the TRAINING child's composed-scope transport.

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q D-12d-51.

**The defect.** PR-12bc B6 gave all three children the composed run's
task-built scopes, and PR-12d seam C (B9) added the declared validation row
count. Both emitters were placed, for training only, INSIDE
``sandbox_executor.execute_training``'s ``if sample_set is not None:`` block —
coupling the COMPOSED transport to the presence of a LEGACY TIDMAD SampleSet.

A composed task without legacy physical geometry has ``sample_set=None`` **by construction**:
``planning.py`` builds one only when the run's profile
``declares_physical_geometry``. So the
training child received **no scope at all**, fell into its own legacy branch,
and hit ``tidmad_topology(dataset_profile)`` — which fails closed for a task
that declares no TIDMAD topology.

The inference and scoring spawns already splat the same emitter
unconditionally. **Training was the only one of the three that did not**, and
that asymmetry was the whole defect — which is why the fix is a hoist, not a
new branch.

**Why no existing test caught it.** Every prior test of the scope transport
passed a SampleSet, because TIDMAD always has one. The one configuration that
exercises the seam this transport was BUILT for — a composed task with no
physical geometry — was the one configuration never asserted.

Each test names a defect only it can catch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import core.sandbox_executor as se
from core.training_execution_bindings import TrainingExecutionBindings

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "synthetic_masked_regression.yaml"


def _composed_scopes_and_sandbox():
    """Build real composed scopes from the minimal regression pack.

    The defect is that a task with no legacy physical geometry was transported
    differently. The minimal pack declares its own non-TIDMAD scope and keeps
    that distinguishing input without requiring private data.
    """
    from execute_tools.task_data_path import ScopeBuildRequest, active_task_data_path
    from nodes.ml_hyperparameter_tune_agent.scope_acquisition import AttemptScopes
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    composition = compose_run_task_bindings(str(SYNTHETIC_MANIFEST))
    return (
        composition,
        AttemptScopes,
        ScopeBuildRequest,
        active_task_data_path,
        bind_run_task_composition,
    )


def _training_argv(*, sample_set, with_scopes: bool, data_root: Path) -> list[str]:
    """Capture the argv `execute_training` would launch, without launching.

    Patches ``_run_observed_subprocess`` — the symbol BOTH launch branches
    actually call. An earlier probe patched ``subprocess.run``, which this
    module does not use, so the real training subprocess ran to completion
    instead of being intercepted; the capture came back empty and looked
    exactly like the defect it was meant to measure.
    """
    (
        composition,
        AttemptScopes,
        ScopeBuildRequest,
        active_task_data_path,
        bind_run_task_composition,
    ) = _composed_scopes_and_sandbox()

    captured: dict[str, list[str]] = {}

    def _stop(cmd, **_kwargs):
        captured["cmd"] = cmd
        raise SystemExit("argv captured")

    data_root.mkdir(parents=True, exist_ok=True)
    task_module = sys.modules[type(composition.task_data_path).__module__]
    task_module.write_data_dir(data_root)
    with bind_run_task_composition(composition, physical_data_root=str(data_root)):
        scopes = AttemptScopes()
        if with_scopes:
            tdp = active_task_data_path()
            request = ScopeBuildRequest(
                round_kind="formal", selection_strategy="snapshot", portion=1.0, seed=0
            )
            scopes = AttemptScopes(
                training=tdp.build_training_scope(request),
                evaluation=tdp.build_eval_scope(request),
            )
        sandbox = se.TidmadSandbox(
            metadata_source="local",
            run_name="probe",
            workspace=str(data_root.parent / "workspace"),
            file_index=6,
        )
        with patch.object(se, "_run_observed_subprocess", side_effect=_stop):
            try:
                sandbox.execute_training(
                    exp_id="e1",
                    run_name="probe",
                    model_type="masked_reference_mlp",
                    m_cfg={
                        "model_type": "masked_reference_mlp",
                        "segmentation_size": 3,
                        "hidden_dim": 8,
                    },
                    t_cfg={
                        "epochs": 1,
                        "batch_size": 4,
                        "lr": 1e-4,
                        "optimizer_type": "adamw",
                    },
                    l_cfg={"loss_type": "custom", "loss_name": "synthetic_masked_mse"},
                    sample_set=sample_set,
                    execution_bindings=TrainingExecutionBindings(task_scopes=scopes),
                )
            except BaseException:
                pass
    return [c for c in captured.get("cmd", []) if isinstance(c, str)]


class TestComposedScopeReachesTheTrainingChildWithoutASampleSet:
    """THE regression, and the exact shape a composed contrast round has."""

    def test_scope_refs_are_emitted_when_sample_set_is_none(self, tmp_path):
        argv = _training_argv(sample_set=None, with_scopes=True, data_root=tmp_path / "data")
        assert "--task_scope_ref" in argv
        assert "--task_eval_scope_ref" in argv

    def test_validation_row_count_is_emitted_when_sample_set_is_none(self, tmp_path):
        """Seam C (B9): the explicit-eval-scope leg requires this and nothing
        in production emitted it for a scope-only round."""
        assert "--validation_requested_rows" in _training_argv(
            sample_set=None, with_scopes=True, data_root=tmp_path / "data"
        )

    def test_the_legacy_sample_set_flag_is_correctly_absent(self, tmp_path):
        """Proves the transport is genuinely decoupled: the composed round
        gets its scope WITHOUT acquiring a legacy SampleSet it has no
        geometry to build."""
        assert "--sample_set_json" not in _training_argv(
            sample_set=None, with_scopes=True, data_root=tmp_path / "data"
        )


class TestUncomposedArgvIsUnchanged:
    def test_no_scope_flags_when_nothing_is_composed(self, tmp_path):
        """The hoist must be a no-op for an un-composed run — both emitters
        return [] for absent scopes, which is what makes this a hoist rather
        than a new branch. If this fails, every legacy TIDMAD argv changed."""
        argv = _training_argv(sample_set=None, with_scopes=False, data_root=tmp_path / "data")
        assert "--task_scope_ref" not in argv
        assert "--task_eval_scope_ref" not in argv
        assert "--validation_requested_rows" not in argv


class TestTheChildDispatchesOnTheScopeNotOnlyTheSampleSet:
    """Child side. Fixing the parent alone leaves the child in its legacy
    branch, where `tidmad_topology()` fails closed for a contrast task."""

    def test_a_transported_scope_alone_selects_the_scope_branch(self):
        """THE child-side regression: no SampleSet, but a scope reference —
        which is exactly a composed contrast round."""
        import argparse

        from execute_tools.train_engine_sandbox import _has_scope_to_train_from

        args = argparse.Namespace(task_scope_ref="/tmp/scope.json")
        assert _has_scope_to_train_from(args, None) is True

    def test_a_legacy_sample_set_alone_still_selects_it(self):
        import argparse

        from execute_tools.train_engine_sandbox import _has_scope_to_train_from

        args = argparse.Namespace(task_scope_ref=None)
        assert _has_scope_to_train_from(args, {"0": [1, 2]}) is True

    def test_neither_selects_the_legacy_branch(self):
        """Boundary: an un-composed TIDMAD run with no SampleSet is still
        dispatched exactly as before — this is the only remaining route into
        the legacy `TIDMADDataset` construction."""
        import argparse

        from execute_tools.train_engine_sandbox import _has_scope_to_train_from

        args = argparse.Namespace(task_scope_ref=None)
        assert _has_scope_to_train_from(args, None) is False

    def test_main_dispatches_through_the_predicate(self):
        """Reachability: the predicate must be what `main` actually calls, or
        the three behavioural tests above guard an unreachable function."""
        import inspect

        from execute_tools import train_engine_sandbox

        assert "_has_scope_to_train_from(args, sample_set)" in inspect.getsource(
            train_engine_sandbox.main
        )
