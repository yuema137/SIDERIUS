"""The tuner really resolves a capability, and an unavailable one says why.

V20 PR C1 / C-C3b.

C-C3a built the boundary; this proves the production path uses it. Without
that, the boundary is a component built, tested and never called -- the
shape of #156, #157, #159 and the A5 field-drop, three of which were found
during this very PR's audit.

The concrete risk being guarded: `_resolve_time_check_probe_request` used to
call `probe_runner_availability()` with no argument, which reached for
`TIDMAD_DATA_DIR` itself and returned a bare False on any other task. If the
tuner ever reverts to the no-argument form, generic runtime-control answers
"no capability was resolved by the caller" and the measured-evidence path
goes off again -- silently, unless something asserts otherwise.

Verified during C-C3b that the existing suite did NOT catch that: reverting
the call site to `probe_runner_availability()` left all 23 launch-guard
tests green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import nodes.ml_hyperparameter_tune_agent as tuner
from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
from core.runtime_control.probe_wiring import probe_runner_availability
from execute_tools.data_paths import resolve_tidmad_measurement_capability


def _resolver_call() -> ast.Call:
    """The `probe_runner_availability(...)` call inside the tuner."""
    tree = ast.parse(Path(tuner.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "probe_runner_availability":
                return node
    raise AssertionError("the tuner no longer calls probe_runner_availability at all")


class TestTheTunerResolvesACapability:
    def test_the_call_site_passes_one(self):
        """The reachability assertion. Reverting the tuner to the
        no-argument form -- which is what silently disabled the measured
        path on non-TIDMAD tasks -- fails here."""
        call = _resolver_call()
        assert call.args or call.keywords, (
            "the tuner calls probe_runner_availability() with no capability; "
            "generic runtime-control then reports that none was resolved and "
            "the measured-evidence path switches itself off"
        )

    def test_it_resolves_through_the_task_owned_adapter(self):
        """Generic code must not pick the dataset. The task layer does, and
        the tuner is where the task is known."""
        source = Path(tuner.__file__).read_text()
        tree = ast.parse(source)
        imported = {
            f"{node.module}.{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        assert "execute_tools.data_paths.resolve_tidmad_measurement_capability" in imported

    def test_the_resolved_root_is_the_one_the_probe_will_use(self):
        """`data_dir` is already a parameter of the enclosing function, so
        the capability describes the dataset the probe actually runs on --
        not a second, independently resolved path that could disagree."""
        call = _resolver_call()
        # The capability handed over must be the local resolved from data_dir,
        # not a fresh no-argument resolution.
        assert any(isinstance(a, ast.Name) and a.id == "capability" for a in call.args)


class TestAnUnavailableCapabilityExplainsItself:
    def test_generic_code_refuses_rather_than_choosing_a_dataset(self):
        available, detail = probe_runner_availability(None)
        assert available is False
        assert "no measurement capability was resolved" in detail

    def test_a_missing_dataset_root_reports_a_reason(self, tmp_path):
        cap = resolve_tidmad_measurement_capability(dataset_root=str(tmp_path / "absent"))
        assert cap.probe_available is False
        assert cap.unavailability_reason
        available, detail = probe_runner_availability(cap)
        assert available is False
        assert cap.unavailability_reason in detail

    def test_the_task_identity_survives_an_unavailable_verdict(self, tmp_path):
        """ "We cannot measure tidmad_denoise" beats "we cannot measure": the
        record of WHY the path was off has to name what was being measured.
        """
        cap = resolve_tidmad_measurement_capability(dataset_root=str(tmp_path / "absent"))
        assert cap.task_identity == "tidmad_denoise"
        assert cap.data_shape_class

    def test_the_tuner_records_the_reason_not_a_bare_false(self):
        """The unavailable branch stamps the task and the reason into the
        breakdown. A bare `probe_resolution="unavailable"` is what let the
        V19 posture persist without anyone noticing which task was silently
        unmeasurable."""
        source = Path(tuner.__file__).read_text()
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        assert 'breakdown["probe_capability_reason"]' in code
        assert 'breakdown["probe_capability_task"]' in code


class TestTheBoundaryStaysGeneric:
    def test_probe_wiring_no_longer_imports_the_task_dataset(self):
        """AST, not text: `probe_wiring`'s docstring names `TIDMAD_DATA_DIR`
        while explaining what it stopped doing, and commentary about a
        symbol is not a use of it."""
        import core.runtime_control.probe_wiring as mod

        tree = ast.parse(Path(mod.__file__).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)

        offenders = sorted(n for n in imported if "data_paths" in n or "dataset_config" in n)
        assert offenders == [], f"generic probe wiring imports task-owned modules: {offenders}"

    def test_the_capability_type_is_what_crosses_the_boundary(self):
        cap = resolve_tidmad_measurement_capability(dataset_root=None)
        assert isinstance(cap, ResolvedMeasurementCapability)


class TestTheWorkflowResolvesACapabilityToo:
    """The OTHER call site, missed when C-C3b fixed the tuner's.

    `workflows/model_exploration.py` calls `run_launch_self_test(...)`,
    whose `capability` parameter defaults to `None`. Generic
    runtime-control then reports "no measurement capability was resolved
    by the caller" and — because a real launch passes
    `require_probe_runner=True` — raises `LaunchGuardFailure` and aborts
    the chain before any LLM call.

    Measured, not theorised: a bounded real chain launch aborted with
    exactly that message while
    `resolve_tidmad_measurement_capability()` reported the dataset as
    available. The class above proved the tuner resolves one; nothing
    asserted the same of the workflow, which is precisely the gap its own
    docstring warns about.
    """

    @staticmethod
    def _launch_self_test_call() -> ast.Call:
        import workflows.model_exploration as workflow

        tree = ast.parse(Path(workflow.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name == "run_launch_self_test":
                    return node
        raise AssertionError("the workflow no longer calls run_launch_self_test at all")

    def test_the_workflow_passes_a_capability(self):
        """MUTATION TARGET: dropping the argument again.

        Without it a real launch can never satisfy the guard, however
        available the dataset actually is.
        """
        call = self._launch_self_test_call()
        keywords = {kw.arg for kw in call.keywords}
        assert "capability" in keywords, (
            "the workflow calls run_launch_self_test() without a capability; "
            "a real launch will abort with LaunchGuardFailure even when the "
            "measurement capability is available"
        )

    def test_it_resolves_through_the_task_owned_adapter(self):
        import workflows.model_exploration as workflow

        source = Path(workflow.__file__).read_text()
        assert "resolve_tidmad_measurement_capability" in source, (
            "generic workflow code must not choose a task's dataset itself; "
            "it resolves through the task-owned adapter"
        )

    def test_a_real_launch_would_now_find_the_capability_available(self):
        """End to end for the property that actually failed: with the
        capability resolved the way the workflow now resolves it, the
        guard's availability check passes on this machine."""
        capability = resolve_tidmad_measurement_capability()
        available, detail = probe_runner_availability(capability)
        assert available, f"probe runner unavailable: {detail}"
        assert "no measurement capability was resolved" not in detail
