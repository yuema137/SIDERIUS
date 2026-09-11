"""C9d — launch guard, production probe wiring, and the legacy-workspace rule.

The guard's job is to fail a launch whose runtime-control subsystem is
not actually wired. Existence proves nothing — during the V19 wave-1
incident every class existed and none of them was on the production
path — so the guard EXERCISES the lifecycle through the same entry point
production calls.

The legacy rule is the other half: a Pydantic default that lets an old
lock file PARSE must never be read as "this workspace is compatible".
"""

from __future__ import annotations

import json

import pytest

from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    ensure_run_invariants,
    validate_run_invariants,
    write_run_invariants,
)
from core.runtime_control.decision_policy import RuntimeBudget, RuntimeMode
from core.runtime_control.launch_guard import (
    LaunchGuardFailure,
    run_launch_self_test,
)
from core.runtime_control.probe_lifecycle import ProbeInfrastructureError, ProbeRequest
from core.runtime_control.probe_wiring import (
    build_production_probe_runner,
    probe_runner_availability,
    resolve_request_probe,
)

FORMAL = RuntimeMode(phase="formal", candidate_stage="post_implementation")


def _tuner_module():
    """The tuner MODULE (the package re-exports its symbols, so a plain
    `from ... import ml_hyperparameter_tune_agent` resolves to a name
    inside the module rather than the module itself)."""
    from importlib import import_module

    return import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")


class TestLaunchSelfTest:
    def test_it_passes_and_reports_what_it_proved(self):
        report = run_launch_self_test(require_probe_runner=False)
        assert report.estimator_identity.startswith("runtime_estimator@")
        assert report.policy_identity.startswith("runtime_decision_policy@")
        assert len(report.checks) >= 7
        assert report.elapsed_seconds < 5.0  # startup cost, not a test suite

    def test_it_is_cheap_and_offline(self, monkeypatch):
        """No LLM, no network, no GPU work: the availability probe only
        asks whether a device and dataset EXIST."""
        import subprocess

        def _no_subprocess(*a, **k):
            raise AssertionError("the launch guard must not shell out")

        monkeypatch.setattr(subprocess, "run", _no_subprocess)
        monkeypatch.setattr(subprocess, "Popen", _no_subprocess)
        run_launch_self_test(require_probe_runner=False)

    def test_it_refuses_a_production_launch_that_cannot_probe(self, monkeypatch):
        import core.runtime_control.launch_guard as guard

        monkeypatch.setattr(
            guard,
            "_probe_runner_availability",
            lambda capability=None: (False, "no CUDA device is visible"),
        )
        with pytest.raises(LaunchGuardFailure, match="requires a real bounded-probe runner"):
            run_launch_self_test(require_probe_runner=True)

    def test_it_catches_a_policy_that_lets_static_evidence_block(self, monkeypatch):
        """The wave-1 regression, caught at startup instead of mid-campaign."""
        import core.runtime_control.launch_guard as guard

        def _blocking(policy):
            raise LaunchGuardFailure("static evidence produced REJECT")

        monkeypatch.setattr(guard, "_assert_static_cannot_block", _blocking)
        with pytest.raises(LaunchGuardFailure, match="static evidence"):
            run_launch_self_test(require_probe_runner=False)

    def test_it_catches_an_unwired_probe_lifecycle(self, monkeypatch):
        """If REQUEST_PROBE stops resolving, the guard fails the launch —
        this is the check that the C8 audit found nobody was making."""
        import core.runtime_control.launch_guard as guard

        def _unwired():
            raise LaunchGuardFailure("REQUEST_PROBE did not resolve")

        monkeypatch.setattr(guard, "_assert_request_probe_resolves", _unwired)
        with pytest.raises(LaunchGuardFailure, match="did not resolve"):
            run_launch_self_test(require_probe_runner=False)


class TestProductionWiring:
    def test_the_guard_and_production_share_one_entry_point(self):
        """A guard that validated a different path than production runs
        would prove nothing."""
        import inspect

        import core.runtime_control.launch_guard as guard

        tuner = _tuner_module()

        guard_source = inspect.getsource(guard)
        tuner_source = inspect.getsource(tuner._resolve_time_check_probe_request)
        assert "resolve_request_probe" in guard_source
        assert "resolve_request_probe" in tuner_source

    def test_the_tuner_resolves_request_probe_and_persists(self, monkeypatch):
        """The production edge end to end, with the real resolver and a
        fake runner: probe -> persist -> rebuild -> re-decide."""
        tuner = _tuner_module()

        from .test_c9d_helpers import fake_ok_probe

        calls, persisted = [], []
        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.probe_runner_availability",
            lambda capability=None: (True, "test"),
        )
        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.build_production_probe_runner",
            lambda **kw: lambda req: (calls.append(req), fake_ok_probe())[1],
        )
        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.build_registry_persist",
            lambda **kw: lambda result, req: (persisted.append(result), ("sha256:x",))[1],
        )
        time_check = {
            "feasible": True,
            "breakdown": {"runtime_decision": "REQUEST_PROBE", "total_train_steps": 10},
        }
        action = tuner._resolve_time_check_probe_request(
            time_check,
            model_type="candidate",
            active_params={"train_config": {"batch_size": 8}, "model_config": {}},
            time_budget_minutes=60.0,
            is_trial=False,
            data_dir=None,
            run_name="r",
            exp_id="e",
        )
        assert action == "proceed"
        assert len(calls) == 1
        assert persisted
        assert time_check["breakdown"]["probe_resolution"] == "ALLOW"
        assert time_check["breakdown"]["probe_observation_ids"] == ["sha256:x"]

    def test_a_probe_rejection_stays_attempt_local(self, monkeypatch):
        tuner = _tuner_module()

        from .test_c9d_helpers import fake_ok_probe

        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.probe_runner_availability",
            lambda capability=None: (True, "test"),
        )
        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.build_production_probe_runner",
            lambda **kw: lambda req: fake_ok_probe(train_ms_per_step=100_000.0),
        )
        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.build_registry_persist",
            lambda **kw: lambda result, req: ("sha256:x",),
        )
        time_check = {
            "feasible": True,
            "breakdown": {"runtime_decision": "REQUEST_PROBE", "total_train_steps": 1000},
        }
        action = tuner._resolve_time_check_probe_request(
            time_check,
            model_type="candidate",
            active_params={},
            time_budget_minutes=1.0,
            is_trial=False,
            data_dir=None,
            run_name="r",
            exp_id="e",
        )
        assert action == "skip"  # attempt-local, NOT a chain halt
        assert time_check["feasible"] is False

    def test_an_infrastructure_failure_asks_for_a_chain_abort(self, monkeypatch):
        tuner = _tuner_module()

        def _broken(**kw):
            def _run(_request):
                raise ProbeInfrastructureError("registry unreachable")

            return _run

        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.probe_runner_availability",
            lambda capability=None: (True, "test"),
        )
        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.build_production_probe_runner", _broken
        )
        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.build_registry_persist",
            lambda **kw: lambda result, req: (),
        )
        time_check = {"feasible": True, "breakdown": {"runtime_decision": "REQUEST_PROBE"}}
        action = tuner._resolve_time_check_probe_request(
            time_check,
            model_type="candidate",
            active_params={},
            time_budget_minutes=60.0,
            is_trial=False,
            data_dir=None,
            run_name="r",
            exp_id="e",
        )
        assert action == "abort"
        assert time_check["breakdown"]["probe_resolution"] == "ABORT"

    def test_an_unprobeable_environment_is_typed_not_silent(self, monkeypatch):
        tuner = _tuner_module()

        monkeypatch.setattr(
            "core.runtime_control.probe_wiring.probe_runner_availability",
            lambda capability=None: (False, "no CUDA device is visible"),
        )
        time_check = {"feasible": True, "breakdown": {"runtime_decision": "REQUEST_PROBE"}}
        action = tuner._resolve_time_check_probe_request(
            time_check,
            model_type="c",
            active_params={},
            time_budget_minutes=60.0,
            is_trial=True,
            data_dir=None,
            run_name="r",
            exp_id="e",
        )
        assert action == "proceed"
        assert time_check["breakdown"]["probe_resolution"] == "unavailable"
        assert "no CUDA" in time_check["breakdown"]["probe_resolution_detail"]

    def test_other_decisions_are_left_untouched(self):
        tuner = _tuner_module()

        for kind in ("ALLOW", "ADVISORY", "REJECT"):
            time_check = {"feasible": True, "breakdown": {"runtime_decision": kind}}
            assert (
                tuner._resolve_time_check_probe_request(
                    time_check,
                    model_type="c",
                    active_params={},
                    time_budget_minutes=60.0,
                    is_trial=True,
                    data_dir=None,
                    run_name="r",
                    exp_id="e",
                )
                == "proceed"
            )
            assert "probe_resolution" not in time_check["breakdown"]

    def test_the_runner_builder_reports_assembly_failure_as_infrastructure(self, monkeypatch):
        """Assembly failure — no CUDA, unknown device VRAM, unloadable
        plugin — is an evidence-channel failure, not a candidate verdict.

        The executors are patched so this never touches a real device:
        `production_probe_executors` builds LAZILY, so calling the runner
        for real would start an actual 10-second contention window and a
        live probe, which a unit test must never do.
        """
        monkeypatch.setattr(
            "core.runtime_control.probe_production.production_probe_executors",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("no CUDA device")),
        )
        runner = build_production_probe_runner(
            model_type="a_model_that_does_not_exist",
            model_config={},
            train_config={},
            loss_config={},
        )
        with pytest.raises(ProbeInfrastructureError, match="could not assemble"):
            runner(ProbeRequest(model_identity="x", train_steps=1, inference_batches=1))

    def test_a_probe_that_cannot_load_the_candidate_aborts(self):
        """The other half: assembly succeeded but the probe could not
        produce evidence. Still ABORT, still not a candidate verdict."""
        from .test_c9d_helpers import fake_ok_probe

        broken = fake_ok_probe().model_copy(
            update={
                "status": "load_failure",
                "error": "plugin import failed",
                "train_ms_per_step": None,
                "train_ms_spread": None,
            }
        )
        resolution = resolve_request_probe(
            request=ProbeRequest(model_identity="x", train_steps=1, inference_batches=1),
            budget=RuntimeBudget(time_seconds=600.0),
            mode=FORMAL,
            run_probe=lambda _r: broken,
            persist=None,
        )
        assert resolution.decision.kind == "ABORT"

    def test_availability_never_raises(self):
        available, detail = probe_runner_availability()
        assert isinstance(available, bool)
        assert detail


class TestLegacyWorkspaceRejection:
    """Defaults exist to PARSE an old lock, never to declare it compatible."""

    def _current(self, **over) -> RunInvariants:
        base = dict(
            resolved_data_scope=[0, 1],
            health_gate_enabled=False,
            health_config_sha256=None,
            runtime_estimator_identity="runtime_estimator@1.0.0+abc",
            runtime_policy_identity="runtime_decision_policy@1.0.0+def",
        )
        base.update(over)
        return RunInvariants(**base)

    def _legacy(self) -> RunInvariants:
        return RunInvariants(
            resolved_data_scope=[0, 1],
            health_gate_enabled=False,
            health_config_sha256=None,
        )

    def test_a_legacy_lock_still_parses(self, tmp_path):
        legacy = {
            "resolved_data_scope": [0, 1],
            "health_gate_enabled": False,
            "health_config_sha256": None,
        }
        parsed = RunInvariants.model_validate(legacy)
        assert parsed.runtime_estimator_identity is None
        assert parsed.runtime_policy_identity is None

    def test_resuming_a_legacy_workspace_is_refused_by_name(self, tmp_path):
        write_run_invariants(str(tmp_path), self._legacy())
        with pytest.raises(RunInvariantsViolation) as exc:
            validate_run_invariants(str(tmp_path), self._current())
        message = str(exc.value)
        assert "runtime_estimator_identity" in message
        assert "runtime_policy_identity" in message
        assert "FRESH workspace" in message
        assert "never to declare it compatible" in message

    def test_the_refusal_happens_through_ensure_too(self, tmp_path):
        write_run_invariants(str(tmp_path), self._legacy())
        with pytest.raises(RunInvariantsViolation):
            ensure_run_invariants(str(tmp_path), self._current())

    def test_a_fresh_workspace_records_the_identities(self, tmp_path):
        assert ensure_run_invariants(str(tmp_path), self._current()) == "created"
        payload = json.loads((tmp_path / "run_invariants_lock.json").read_text())
        assert payload["runtime_estimator_identity"] == "runtime_estimator@1.0.0+abc"
        assert payload["runtime_policy_identity"] == "runtime_decision_policy@1.0.0+def"
        assert ensure_run_invariants(str(tmp_path), self._current()) == "validated"

    def test_a_changed_policy_identity_is_a_violation(self, tmp_path):
        ensure_run_invariants(str(tmp_path), self._current())
        with pytest.raises(RunInvariantsViolation, match="runtime_policy_identity"):
            validate_run_invariants(
                str(tmp_path),
                self._current(runtime_policy_identity="runtime_decision_policy@2.0.0+zzz"),
            )

    def test_legacy_tooling_can_still_read_a_legacy_workspace(self, tmp_path):
        """The refusal fires only when THIS run carries the identities."""
        write_run_invariants(str(tmp_path), self._legacy())
        validate_run_invariants(str(tmp_path), self._legacy())  # no raise


class TestProbeRequirementIsExplicit:
    """C9d follow-up: the probe requirement is an explicit launch decision,
    never inferred from incidental arguments.

    The first version derived it from `sandbox_factory is None`, which made
    workflow startup silently GPU-dependent: it passed on a GPU dev box and
    failed in CI, where no CUDA device exists. Factory identity says
    nothing about whether a launch will do formal training.
    """

    def test_run_workflow_defaults_to_not_requiring_a_device(self):
        # Step 09.5a C3 / Amendment A: `require_probe_runner` is a bool launch
        # flag, so it lives on WorkflowLaunchConfig. Its default — and the
        # fail-open-by-default posture this guards — is unchanged.
        import dataclasses
        import inspect

        from workflows.model_exploration import run_workflow
        from workflows.run_config import WorkflowLaunchConfig

        parameter = next(
            f for f in dataclasses.fields(WorkflowLaunchConfig) if f.name == "require_probe_runner"
        )
        assert parameter.default is False

    def test_the_real_launch_path_opts_in_explicitly(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src" / "workflows" / "run_one_iteration.py"
        ).read_text(encoding="utf-8")
        assert "require_probe_runner=not (args.is_pseudo_training or args.is_pseudo_llm)" in source

    def test_the_guard_still_runs_every_behavioral_check_without_a_device(self, monkeypatch):
        """Not requiring a device must not mean skipping the checks."""
        import core.runtime_control.launch_guard as guard

        monkeypatch.setattr(
            guard,
            "_probe_runner_availability",
            lambda capability=None: (False, "no CUDA device is visible"),
        )
        report = run_launch_self_test(require_probe_runner=False)
        assert report.probe_runner_available is False
        assert len(report.checks) >= 7
        assert any("REQUEST_PROBE resolves" in c for c in report.checks)
